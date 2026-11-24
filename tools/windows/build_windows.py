"""Build the standalone Windows (10/11, 64-bit) version of ReSrijan on Linux.

    python tools/windows/build_windows.py            # → build/windows/ReSrijan-<version>-Setup.exe

Everything comes from conda-forge's Windows builds (no Windows machine needed):
Python, Qt (PySide6), NumPy/SciPy/Matplotlib/OpenCV/scikit-image/PyMuPDF, Tesseract (OCR),
Ghostscript (EPS/PS) and librsvg (SVG). The installer is made with NSIS (``apt install nsis``).

Needs: ``pip install py-rattler pillow`` and ``makensis`` on PATH.

Layout of the installed program (per user, no administrator rights):
    %LOCALAPPDATA%\\Programs\\ReSrijan\\
        runtime\\            Python environment (conda-forge, win-64) with ReSrijan inside
        resrijan.cmd        the command line:  resrijan digitize figure.pdf …
        resrijan.ico
        licenses\\          licences of ReSrijan and of the bundled programs
"""
from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

# pinned to the versions the test suite runs with
SPECS = [
    "python 3.13.*", "pyside6 6.12.*", "numpy 2.5.*", "scipy 1.18.*", "matplotlib-base 3.11.*",
    "libblas * *openblas", "liblapack * *openblas",           # OpenBLAS: ~40 MB instead of MKL's ~600 MB
    "scikit-image 0.26.*", "scikit-learn 1.9.*", "pymupdf 2.1.*", "pillow >=12,<14",
    "pytesseract 0.3.*", "pyyaml 6.*", "tesseract 5.*", "ghostscript 10.*", "librsvg 2.*",
    "fonts-conda-ecosystem",
]

# from PyPI instead of conda-forge: the headless OpenCV wheel is self-contained and small
# (conda-forge's OpenCV brings video codecs and OpenVINO, ~300 MB, that ReSrijan never uses)
WHEELS = ["opencv-python-headless==5.1.*"]

# large parts of the environment that ReSrijan never uses
PRUNE_DIRS = ["Library/include", "Library/share/doc", "Library/share/man", "Library/share/gtk-doc", "include",
              "Library/share/info", "pkgs", "Library/cmake", "Library/lib/cmake", "Library/lib/pkgconfig"]
PRUNE_GLOBS = ["**/__pycache__", "Lib/site-packages/*/tests", "Lib/site-packages/*/*/tests",
               "Lib/site-packages/*/testing", "Lib/test", "Lib/idlelib", "Lib/tkinter", "Lib/turtledemo",
               "Lib/site-packages/PySide6/examples", "Lib/site-packages/PySide6/include",
               "Library/lib/*.lib", "**/*.pdb", "Lib/site-packages/PySide6/Qt*Designer*",
               "Lib/site-packages/PySide6/designer.exe", "Lib/site-packages/PySide6/linguist.exe",
               "Lib/site-packages/PySide6/assistant.exe",
               "Library/bin/libclang*.dll", "Library/bin/clang*.exe",        # Qt binding generator only
               "Lib/site-packages/shiboken6_generator", "Library/bin/shiboken6.exe",
               "Library/bin/qdoc.exe", "Library/bin/lupdate.exe", "Library/bin/lrelease.exe",
               # video I/O of OpenCV (ReSrijan reads still images only)
               "Lib/site-packages/cv2/opencv_videoio_ffmpeg*.dll",
               # Qt developer tools and the Qt Quick/QML stack (the GUI uses Qt Widgets only)
               "Library/lib/qt6/bin", "Library/lib/qt6/qml", "Library/lib/qt6/metatypes", "Library/lib/qt6/mkspecs",
               "Library/lib/qt6/sbom", "Library/lib/qt6/*.exe", "Library/lib/qt6/plugins/designer",
               "Library/lib/qt6/plugins/qmllint", "Library/lib/qt6/plugins/qmlls", "Library/lib/qt6/plugins/qmltooling",
               "Library/lib/qt6/plugins/sqldrivers", "Library/lib/qt6/plugins/help",
               "Library/bin/Qt6Quick*.dll", "Library/bin/Qt6Qml*.dll", "Library/bin/Qt6Designer*.dll",
               "Library/bin/Qt6ShaderTools.dll", "Library/bin/Qt6Labs*.dll", "Library/bin/Qt6QuickControls2*.dll",
               "Library/bin/Qt6Help.dll", "Library/bin/Qt6UiTools.dll", "Library/bin/Qt6Test.dll",
               "Library/bin/designer.exe", "Library/bin/assistant.exe", "Library/bin/linguist.exe",
               "Library/bin/qml*.exe", "Library/bin/qmlls.exe",
               "Lib/site-packages/PySide6/Qt6Quick*.dll", "Lib/site-packages/PySide6/Qt6Qml*.dll"]

SITECUSTOMIZE = r'''"""ReSrijan runtime: make the bundled programs and libraries findable (the environment is
used without "conda activate")."""
import os
import sys
from pathlib import Path

_p = Path(sys.prefix)
_dirs = [_p / "Library" / "mingw-w64" / "bin", _p / "Library" / "usr" / "bin", _p / "Library" / "bin",
         _p / "Scripts", _p]
os.environ["PATH"] = os.pathsep.join([str(d) for d in _dirs if d.is_dir()] + [os.environ.get("PATH", "")])
for _d in _dirs:
    if _d.is_dir() and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(_d))
        except OSError:
            pass
for _t in (_p / "Library" / "share" / "tessdata", _p / "share" / "tessdata"):
    if _t.is_dir():
        os.environ.setdefault("TESSDATA_PREFIX", str(_t))
        break
for _g in (_p / "Library" / "share" / "ghostscript",):
    if _g.is_dir():
        _lib = [str(x / "lib") for x in sorted(_g.iterdir()) if (x / "lib").is_dir()]
        _res = [str(x / "Resource" / "Init") for x in sorted(_g.iterdir()) if (x / "Resource" / "Init").is_dir()]
        if _lib or _res:
            os.environ.setdefault("GS_LIB", os.pathsep.join(_res + _lib))
# Qt plugins (also in qt6.conf, relative)
_plug = _p / "Library" / "lib" / "qt6" / "plugins"
if _plug.is_dir():
    os.environ.setdefault("QT_PLUGIN_PATH", str(_plug))
# librsvg's image decoders: the cache lists absolute paths, written for this installation on first use
_cache = _p / "Library" / "lib" / "gdk-pixbuf-2.0" / "2.10.0" / "loaders.cache.in"
if _cache.is_file():
    try:
        _dst = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "resrijan" / "pixbuf-loaders.cache"
        _txt = _cache.read_text(encoding="utf-8").replace("@RESRIJAN_PREFIX@", str(_p).replace("\\", "/"))
        if not _dst.is_file() or _dst.read_text(encoding="utf-8") != _txt:
            _dst.parent.mkdir(parents=True, exist_ok=True)
            _dst.write_text(_txt, encoding="utf-8")
        os.environ.setdefault("GDK_PIXBUF_MODULE_FILE", str(_dst))
    except OSError:
        pass
'''

CMD = r'''@echo off
rem ReSrijan command line: resrijan digitize figure.pdf, resrijan gui, resrijan --help
"%~dp0runtime\python.exe" -m resrijan %*
'''


def version() -> str:
    s = (ROOT / "resrijan" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', s).group(1)


async def make_env(prefix: Path, cache: Path):
    from rattler import (BuildString, Channel, GenericVirtualPackage, PackageName, Platform, Version, install,
                         solve)
    print("solving the Windows environment …")
    win = [GenericVirtualPackage(PackageName("__win"), Version("0"), BuildString("0")),
           GenericVirtualPackage(PackageName("__archspec"), Version("1"), BuildString("x86_64"))]
    records = await solve(sources=[Channel("conda-forge")], specs=SPECS, virtual_packages=win,
                          platforms=[Platform("win-64"), Platform("noarch")])
    print(f"  {len(records)} packages; installing into {prefix}")
    await install(records, target_prefix=str(prefix), cache_dir=str(cache), platform=Platform("win-64"),
                  show_progress=False)
    return records


def add_wheels(prefix: Path, cache: Path):
    """Unpack Windows wheels from PyPI straight into site-packages (pure files, no installer)."""
    import zipfile
    dl = cache / "wheels"
    dl.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "download", "-q", "--no-deps", "--only-binary=:all:",
                    "--platform", "win_amd64", "--python-version", "3.13", "-d", str(dl)] + WHEELS, check=True)
    site = prefix / "Lib" / "site-packages"
    for whl in sorted(dl.glob("*.whl")):
        with zipfile.ZipFile(whl) as z:
            z.extractall(site)
        print("  wheel:", whl.name)


# PySide6 modules ReSrijan uses (+ what they need); the wrappers for other Qt add-ons are removed
PYSIDE_KEEP = {"QtCore", "QtGui", "QtWidgets", "QtSvg", "QtSvgWidgets", "QtPrintSupport", "QtNetwork",
               "QtOpenGL", "QtOpenGLWidgets", "QtConcurrent", "QtXml", "QtDBus"}


QT_CONF = """[Paths]
Prefix = {prefix}
Libraries = Library/lib
LibraryExecutables = Library/lib/qt6
Binaries = Library/lib/qt6/bin
Plugins = Library/lib/qt6/plugins
Translations = Library/share/qt6/translations
Data = Library/lib/qt6
ArchData = Library/lib/qt6
"""


def relocate(prefix: Path):
    """conda packages embed the install path; make the runtime work wherever it is installed."""
    for conf, rel in ((prefix / "qt6.conf", "."), (prefix / "qt.conf", "."),
                      (prefix / "Library" / "bin" / "qt6.conf", "../.."), (prefix / "Library" / "bin" / "qt.conf", "../..")):
        conf.write_text(QT_CONF.format(prefix=rel), encoding="ascii")
    cache = prefix / "Library" / "lib" / "gdk-pixbuf-2.0" / "2.10.0" / "loaders.cache"
    if cache.is_file():
        txt = cache.read_text(encoding="utf-8").replace(str(prefix), "@RESRIJAN_PREFIX@")
        (cache.parent / "loaders.cache.in").write_text(txt, encoding="utf-8")
        cache.unlink()
    left = [str(f.relative_to(prefix)) for f in prefix.rglob("*.conf") if f.is_file()
            and str(prefix) in f.read_text(encoding="utf-8", errors="ignore")]
    if left:
        print("  note: build path still in", ", ".join(left))


def prune_pyside(prefix: Path):
    pyside = prefix / "Lib" / "site-packages" / "PySide6"
    for f in list(pyside.glob("Qt*.pyd")) + list(pyside.glob("Qt*.pyi")):
        if f.name.split(".")[0] not in PYSIDE_KEEP:
            f.unlink()
    for f in prefix.glob("Library/bin/pyside6qml*.dll"):
        f.unlink()
    for d in ("Library/shiboken6_generator", "Library/bin/Qt6WebChannel.dll", "Library/bin/Qt6WebChannelQuick.dll"):
        q = prefix / d
        shutil.rmtree(q, ignore_errors=True) if q.is_dir() else (q.unlink() if q.exists() else None)


def prune(prefix: Path):
    before = du(prefix)
    prune_pyside(prefix)
    # Windows paths ignore case: lib\site-packages and Lib\site-packages are one folder there
    low, up = prefix / "lib" / "site-packages", prefix / "Lib" / "site-packages"
    if low.is_dir() and low != up and up.is_dir():
        for item in low.iterdir():
            dst = up / item.name
            if not dst.exists():
                shutil.move(str(item), str(dst))
        shutil.rmtree(prefix / "lib", ignore_errors=True)
    # OCR language data: English (labels, numbers, units) and orientation only
    for td in (prefix / "share" / "tessdata", prefix / "Library" / "share" / "tessdata"):
        if td.is_dir():
            for f in td.glob("*.traineddata"):
                if f.stem not in ("eng", "osd"):
                    f.unlink()
            for d in ("script",):
                shutil.rmtree(td / d, ignore_errors=True)
    for d in PRUNE_DIRS:
        shutil.rmtree(prefix / d, ignore_errors=True)
    for g in PRUNE_GLOBS:
        for p in prefix.glob(g):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink()
    print(f"  pruned {before - du(prefix):.0f} MB → {du(prefix):.0f} MB")


def du(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6


def add_resrijan(app: Path):
    site = app / "runtime" / "Lib" / "site-packages"
    dst = site / "resrijan"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(ROOT / "resrijan", dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (site / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    for c in site.glob("__pycache__/sitecustomize*.pyc"):
        c.unlink()
    (app / "resrijan.cmd").write_text(CMD.replace("\n", "\r\n"), encoding="ascii")
    # icon for shortcuts and the installer
    from PIL import Image
    Image.open(ROOT / "resrijan" / "gui" / "assets" / "resrijan-icon-512.png").save(
        app / "resrijan.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    lic = app / "licenses"
    lic.mkdir(exist_ok=True)
    shutil.copy(ROOT / "LICENSE", lic / "ReSrijan-LICENSE.txt")
    (lic / "THIRD-PARTY.txt").write_text(THIRD_PARTY, encoding="utf-8")
    # licences of the conda packages travel with them (runtime/info/licenses, conda-meta)


THIRD_PARTY = """ReSrijan for Windows bundles these programs and libraries (from conda-forge):

* Python (PSF licence), Qt 6 / PySide6 (LGPL v3), NumPy, SciPy, Matplotlib, scikit-image,
  scikit-learn, Pillow, PyYAML (BSD/MIT-style), OpenCV (Apache 2.0),
* PyMuPDF / MuPDF (AGPL v3), Ghostscript (AGPL v3), Tesseract OCR (Apache 2.0), librsvg (LGPL v2+),
  pytesseract (Apache 2.0) and their dependencies.

The licence text of every package is in runtime\\info\\licenses\\ or in the package's
folder in runtime\\conda-meta\\. Source code: https://github.com/rbiswasgroup/resrijan
(ReSrijan) and https://conda-forge.org (all other packages).
"""


def wizard_images(build: Path):
    """Installer side image (164×314) and header image (150×57) in the GUI's colours."""
    from PIL import Image, ImageDraw
    icon = Image.open(ROOT / "resrijan" / "gui" / "assets" / "resrijan-icon-512.png").convert("RGBA")
    navy = (11, 17, 32)
    side = Image.new("RGB", (164, 314), navy)
    d = ImageDraw.Draw(side)
    for y in range(314):                       # subtle vertical gradient
        t = y / 313
        d.line([(0, y), (163, y)], fill=(int(11 + 10 * t), int(17 + 14 * t), int(32 + 26 * t)))
    ic = icon.resize((120, 120), Image.LANCZOS)
    side.paste(ic, (22, 70), ic)
    d.line([(22, 214), (142, 214)], fill=(25, 195, 177), width=2)
    side.save(build / "wizard.bmp")
    head = Image.new("RGB", (150, 57), navy)
    ic = icon.resize((46, 46), Image.LANCZOS)
    head.paste(ic, (98, 5), ic)
    head.save(build / "header.bmp")


def nsis(app: Path, out: Path, ver: str):
    nsi = (HERE / "installer.nsi").read_text(encoding="utf-8")
    script = app.parent / "installer.nsi"
    script.write_text(nsi, encoding="utf-8")
    cmd = ["makensis", "-V2", f"-DVERSION={ver}", f"-DAPPDIR={app}", f"-DOUTFILE={out}",
           f"-DROOT={ROOT}", str(script)]
    print("building the installer …")
    subprocess.run(cmd, check=True)
    print(f"  {out}  ({out.stat().st_size / 1e6:.0f} MB)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", default=str(ROOT / "build" / "windows"))
    ap.add_argument("--skip-env", action="store_true", help="reuse the existing runtime (only refresh ReSrijan)")
    ap.add_argument("--no-installer", action="store_true")
    a = ap.parse_args()
    build = Path(a.build)
    app = build / "ReSrijan"
    ver = version()
    if not a.skip_env:
        shutil.rmtree(app, ignore_errors=True)
        app.mkdir(parents=True)
        asyncio.run(make_env(app / "runtime", build / "cache"))
        add_wheels(app / "runtime", build / "cache")
        prune(app / "runtime")
        relocate(app / "runtime")
    add_resrijan(app)
    if not a.no_installer:
        if not shutil.which("makensis"):
            sys.exit("makensis not found: sudo apt install nsis")
        wizard_images(build)
        nsis(app, build / f"ReSrijan-{ver}-Setup.exe", ver)


if __name__ == "__main__":
    main()
