"""Load figures from PDF, EPS, PS and bitmap files.

Every input is turned into one or more :class:`Page` objects that carry

* ``rgb``      – a raster rendering (H x W x 3, uint8) used by the computer-vision path,
* ``scale``    – pixels per PDF point of that rendering,
* ``pdf_page`` – a live PyMuPDF page when the source is vector-capable (PDF/EPS/PS),
                 which lets the extractors read exact path coordinates and text.

EPS and PS are converted to PDF with Ghostscript (``-dEPSCrop``), and SVG/SVGZ with
MuPDF (falling back to rsvg-convert or Inkscape). Both keep the drawing as vectors,
so these figures get the same exact-coordinate treatment as PDF.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
from PIL import Image

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

RASTER_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
VECTOR_EXT = {".pdf", ".eps", ".ps", ".epsi", ".epsf", ".svg", ".svgz"}


@dataclass
class Page:
    source: str
    index: int
    rgb: np.ndarray
    scale: float                       # raster pixels per PDF point (1.0 for bitmaps)
    kind: str                          # "vector" or "raster"
    pdf_page: Optional[object] = None  # fitz.Page when vector-capable
    native_dpi: Optional[float] = None
    meta: dict = field(default_factory=dict)

    @property
    def height(self) -> int:
        return self.rgb.shape[0]

    @property
    def width(self) -> int:
        return self.rgb.shape[1]

    def has_vectors(self, rect=None) -> bool:
        """True when the page (or a rect in PDF points) holds stroked/filled paths."""
        if self.pdf_page is None:
            return False
        draws = self.pdf_page.get_drawings()
        if rect is None:
            return len(draws) > 3
        r = fitz.Rect(rect)
        return sum(1 for d in draws if fitz.Rect(d["rect"]).intersects(r)) > 3

    def px_to_pt(self, x, y):
        return x / self.scale, y / self.scale

    def pt_to_px(self, x, y):
        return x * self.scale, y * self.scale


def _ghostscript() -> str:
    for name in ("gs", "gswin64c", "gswin32c"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError(
        "Ghostscript is required for EPS/PS input. Install it with:  sudo apt install ghostscript")


def ps_to_pdf(path: str, out_dir: Optional[str] = None) -> str:
    """Convert EPS/PS to a vector PDF (bounding box respected for EPS)."""
    gs = _ghostscript()
    out_dir = out_dir or tempfile.mkdtemp(prefix="resrijan_")
    out = os.path.join(out_dir, Path(path).stem + ".pdf")
    cmd = [gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite",
           "-dEPSCrop", "-dAutoRotatePages=/None", "-dCompatibilityLevel=1.5",
           "-dEmbedAllFonts=true", "-dSubsetFonts=true", f"-sOutputFile={out}", str(path)]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out


def _svg_uses_clipping(path: str) -> bool:
    """True when the SVG clips, masks or patterns content (MuPDF's SVG reader ignores these)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return False
    return any(k in data for k in (b"clip-path", b"<clipPath", b"mask=", b"<mask", b"<pattern"))


def _svg_mupdf(src: str, out: str) -> str:
    with fitz.open(src) as d:
        pdf = fitz.open("pdf", d.convert_to_pdf())
        if len(pdf[0].get_drawings()) == 0 and not pdf[0].get_images():
            raise RuntimeError("no drawing paths produced")
        pdf.save(out)
    return out


def _svg_rsvg(src: str, out: str) -> str:
    rsvg = shutil.which("rsvg-convert")
    if not rsvg:
        raise RuntimeError("not installed")
    try:        # -u: allow huge files (Inkscape SVGs embed photos as one long base64 line)
        subprocess.run([rsvg, "-u", "-f", "pdf", "-o", out, src], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        subprocess.run([rsvg, "-f", "pdf", "-o", out, src], check=True, capture_output=True)
    return out


def _svg_inkscape(src: str, out: str) -> str:
    ink = shutil.which("inkscape")
    if not ink:
        raise RuntimeError("not installed")
    subprocess.run([ink, src, "--export-type=pdf", f"--export-filename={out}"], check=True, capture_output=True)
    return out


def svg_to_pdf(path: str, out_dir: Optional[str] = None) -> str:
    """Convert SVG/SVGZ to a vector PDF.

    MuPDF is fast but ignores clip paths and masks, so SVGs that use them (Inkscape
    exports of PDFs, cropped photos, matplotlib axes clips) go through rsvg-convert
    first; Inkscape is the last resort.
    """
    import gzip
    out_dir = out_dir or tempfile.mkdtemp(prefix="resrijan_")
    src = path
    if path.lower().endswith(".svgz"):
        src = os.path.join(out_dir, Path(path).stem + ".svg")
        with gzip.open(path, "rb") as fi, open(src, "wb") as fo:
            fo.write(fi.read())
    out = os.path.join(out_dir, Path(path).stem + ".pdf")
    order = [("rsvg-convert", _svg_rsvg), ("MuPDF", _svg_mupdf), ("inkscape", _svg_inkscape)]
    if not _svg_uses_clipping(src):
        order = [order[1], order[0], order[2]]
    errors = []
    for name, fn in order:
        try:
            return fn(src, out)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("Could not convert SVG to PDF (" + "; ".join(errors) +
                       "). Install librsvg2-bin:  sudo apt install librsvg2-bin")


def _load_bitmap(path: str) -> Page:
    im = Image.open(path)
    dpi = None
    if "dpi" in im.info:
        try:
            dpi = float(im.info["dpi"][0])
        except Exception:
            dpi = None
    if im.mode in ("I;16", "I;16B", "I", "F"):
        arr = np.asarray(im).astype(np.float64)
        lo, hi = np.percentile(arr, [0.01, 99.99])
        arr = np.clip((arr - lo) / max(hi - lo, 1e-9) * 255, 0, 255).astype(np.uint8)
        rgb = np.stack([arr] * 3, -1)
    else:
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        rgb = np.asarray(im.convert("RGB")).copy()
    return Page(source=str(path), index=0, rgb=rgb, scale=1.0, kind="raster",
                native_dpi=dpi, meta={"format": Path(path).suffix.lower().lstrip(".")})


def render_pdf_page(page, dpi: float = 600, clip=None) -> np.ndarray:
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, clip=clip)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 1:
        arr = np.repeat(arr, 3, axis=2)
    return arr[:, :, :3].copy()


def load(path: str, pages: Optional[List[int]] = None, dpi: float = 600) -> List[Page]:
    """Load ``path`` and return a list of pages (0-based ``pages`` selects a subset)."""
    path = str(path)
    ext = Path(path).suffix.lower()
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if ext in RASTER_EXT:
        return [_load_bitmap(path)]
    if ext in VECTOR_EXT:
        if ext == ".pdf":
            pdf_path = path
        elif ext in (".svg", ".svgz"):
            pdf_path = svg_to_pdf(path)
        else:
            pdf_path = ps_to_pdf(path)
        doc = fitz.open(pdf_path)
        idx = pages if pages is not None else list(range(doc.page_count))
        out = []
        for i in idx:
            pg = doc[i]
            rgb = render_pdf_page(pg, dpi)
            out.append(Page(source=path, index=i, rgb=rgb, scale=dpi / 72.0, kind="vector",
                            pdf_page=pg, native_dpi=dpi,
                            meta={"format": ext.lstrip("."), "pdf": pdf_path,
                                  "page_size_pt": (pg.rect.width, pg.rect.height),
                                  "_doc": doc}))
        return out
    # last resort: let PIL try
    try:
        return [_load_bitmap(path)]
    except Exception as exc:  # pragma: no cover
        raise ValueError(f"Unsupported file type: {ext}") from exc


def embedded_images(page: Page, min_px: int = 200):
    """Return raster images embedded in a PDF page with their placement (points).

    Journal PDFs often embed micrographs or even whole plots as bitmaps; extracting
    them at native resolution beats re-rendering the page.
    """
    if page.pdf_page is None:
        return []
    pg = page.pdf_page
    doc = pg.parent
    res = []
    for info in pg.get_images(full=True):
        xref = info[0]
        try:
            rects = pg.get_image_rects(xref, transform=True)
            pix = fitz.Pixmap(doc, xref)
            if pix.n - pix.alpha >= 4:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            if pix.width < min_px and pix.height < min_px:
                continue
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            arr = arr[:, :, :3] if pix.n >= 3 else np.repeat(arr[:, :, :1], 3, axis=2)
            for r, m in rects:
                if abs(m.b) > 1e-6 or abs(m.c) > 1e-6:
                    continue          # rotated/sheared placement: not usable as a data grid
                img = arr
                if m.a < 0:
                    img = img[:, ::-1]
                if m.d < 0:
                    img = img[::-1]   # stored bottom-up (common in SVG-derived PDFs)
                res.append({"xref": xref, "rect": tuple(r), "rgb": img.copy(),
                            "native_dpi": pix.width / max(r.width, 1e-6) * 72.0})
        except Exception:
            continue
    return res


def crop(page: Page, box_px) -> Page:
    """Return a sub-page for a pixel box (x0, y0, x1, y1). Vector access is kept."""
    x0, y0, x1, y1 = [int(round(v)) for v in box_px]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(page.width, x1), min(page.height, y1)
    sub = Page(source=page.source, index=page.index, rgb=page.rgb[y0:y1, x0:x1].copy(),
               scale=page.scale, kind=page.kind, pdf_page=page.pdf_page,
               native_dpi=page.native_dpi, meta=dict(page.meta))
    sub.meta["offset_px"] = (x0 + page.meta.get("offset_px", (0, 0))[0],
                             y0 + page.meta.get("offset_px", (0, 0))[1])
    return sub
