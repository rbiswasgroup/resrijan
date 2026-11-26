"""Check that the Windows runtime contains every module ReSrijan imports.

Runs the real workloads here (Linux): digitise a figure, plot, analyse, fit, compose, build every GUI
page and the data editor. Then every imported module is looked up in the Windows runtime folder.
A module that was pruned away by mistake (e.g. numpy.testing, needed by SciPy) is reported.

    python tools/windows/check_imports.py build/windows/ReSrijan/runtime
"""
from __future__ import annotations

import os
import sys
import sysconfig
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POSIX_ONLY = {"posix", "pwd", "grp", "fcntl", "termios", "tty", "pty", "resource", "readline", "_posixsubprocess",
              "_posixshmem", "syslog", "crypt", "nis", "spwd", "ossaudiodev", "_curses", "curses", "_crypt",
              "multiprocessing.popen_fork", "multiprocessing.popen_forkserver", "multiprocessing.popen_spawn_posix",
              "multiprocessing.forkserver", "multiprocessing.resource_tracker", "asyncio.unix_events",
              "_scproxy", "_gdbm", "_dbm", "dbm.gnu", "dbm.ndbm", "_uuid", "_multiprocessing", "_ctypes_test"}


def workloads(tmp: Path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("MPLBACKEND", "Agg")
    from resrijan.cli import main
    ex = ROOT / "examples"
    main(["digitize", str(ex / "04_scatter_errorbars" / "scatter_err.png"), "-o", str(tmp / "d1"), "-f", "png,pdf,svg,tiff"])
    main(["digitize", str(ex / "05_bar_chart" / "bar_err.svg"), "-o", str(tmp / "d2"), "-f", "png"])
    main(["digitize", str(ex / "08_micrograph" / "micrograph_tem.png"), "-o", str(tmp / "d3"), "-f", "png"])
    main(["plot", str(ex / "10_plot_your_data" / "diffusion.csv"), "--kind", "errorbar", "-x", "T_K",
          "-y", "D_urea", "--yerr", "err_urea", "--text", "300,1,a", "-o", str(tmp / "p"), "-f", "png,eps"])
    main(["analyze", str(ex / "15_analysis" / "amide_band.csv"), "--baseline", "als", "--components", "3",
          "--smooth", "savgol:9:3", "-o", str(tmp / "a"), "-f", "png"])
    main(["fit", str(ex / "16_curve_fit" / "correlation.csv"), "-m", "kww", "-o", str(tmp / "f"), "-f", "png"])
    main(["compose", str(ex / "11_compose_figure" / "figure_natchem.yaml"), "-o", str(tmp / "c"), "-f", "png"])
    main(["doctor"])
    from PySide6.QtWidgets import QApplication
    from resrijan.gui import theme
    from resrijan.gui.mainwindow import MainWindow
    from resrijan.gui.editor import DataEditor
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    w = MainWindow(synchronous=True)
    for k in w.pages:
        w.show_page(k)
    w.pages["plot"].open_path(str(ex / "10_plot_your_data" / "diffusion.csv"))
    w.pages["plot"].preview()
    w.pages["fit"].preview()
    w.pages["analyze"].preview()
    ed = DataEditor(str(next((tmp / "d1").glob("*_data.csv"))))
    ed.save()
    import resrijan._winlaunch  # noqa: F401


def present(runtime: Path, name: str, origin: str) -> bool:
    site = runtime / "Lib" / "site-packages"
    rel = name.replace(".", "/")
    roots = [site, runtime / "Lib", runtime / "DLLs"]
    for r in roots:
        if (r / rel / "__init__.py").exists() or (r / (rel + ".py")).exists():
            return True
        parent, leaf = (r / rel).parent, rel.split("/")[-1]
        if parent.is_dir() and any(parent.glob(leaf + ".*.pyd")) or (parent / (leaf + ".pyd")).exists():
            return True
        if (r / rel).is_dir() and origin == "namespace":
            return True
    return False


def _runtime_versions(site: Path) -> dict:
    out = {}
    for d in site.glob("*.dist-info"):
        name, _, ver = d.name[:-len(".dist-info")].partition("-")
        out[name.lower().replace("_", "-")] = ver
    return out


def main():
    runtime = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "build" / "windows" / "ReSrijan" / "runtime")
    with tempfile.TemporaryDirectory() as t:
        workloads(Path(t))
    from importlib import metadata
    stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve()
    site = runtime / "Lib" / "site-packages"
    rver = _runtime_versions(site)
    pkg_of = metadata.packages_distributions()
    errors, notes = [], []
    for name, mod in sorted(sys.modules.items()):
        if mod is None or name in sys.builtin_module_names or name in POSIX_ONLY or name.split(".")[0] in POSIX_ONLY:
            continue
        if getattr(mod, "__name__", name) != name or name.startswith(("_frozen", "_sysconfigdata", "__editable__",
                                                                     "_distutils_hack")):
            continue                                    # aliases and interpreter/build internals
        f = getattr(mod, "__file__", None)
        parent = sys.modules.get(name.rpartition(".")[0]) if "." in name else None
        if parent is not None and str(getattr(parent, "__file__", "") or "").endswith((".so", ".pyd")):
            continue                                    # sub-module defined inside a compiled module
        if f is None and not hasattr(mod, "__path__"):
            continue
        p = Path(f).resolve() if f else None
        in_site = p is not None and ("site-packages" in p.parts or "dist-packages" in p.parts)
        in_std = p is not None and str(p).startswith(str(stdlib)) and not in_site
        if in_std and p.suffix == ".py" and (runtime / "Lib" / p.relative_to(stdlib)).exists():
            continue                                    # e.g. collections.abc lives in _collections_abc.py
        ours = p is not None and str(p).startswith(str(ROOT / "resrijan"))
        if not (in_std or in_site or ours) or present(runtime, name, "namespace" if f is None else f):
            continue
        top = name.split(".")[0]
        if in_std or ours:
            errors.append(name)
            continue
        dists = pkg_of.get(top, [])
        local = {d.lower().replace("_", "-"): metadata.version(d) for d in dists}
        same = [d for d, v in local.items() if rver.get(d) == v]
        in_rt = (site / top).exists() or any(site.glob(top + ".*"))
        if in_rt and same:
            errors.append(name)                         # same package version, module pruned away
        else:
            notes.append(name if in_rt else f"{top} (not installed: optional)")
    errors = [m for m in errors if not any(m.startswith(o + ".") for o in errors)]
    notes = sorted({n.split(".")[0] if "optional" in n else n for n in notes if not any(n.startswith(o + ".") for o in errors)})
    print(f"{len(sys.modules)} modules imported.")
    print("Missing from the Windows runtime (must be fixed): " + (", ".join(errors) or "none"))
    if notes:
        print("Notes (different package version or optional extras): " + ", ".join(sorted(set(notes))))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
