"""ReSrijan (पुनःसृजन, "re-creation") – digitise, analyse, fit and redraw scientific figures in journal style."""
__version__ = "0.6.0"

from ._platform import setup_bundled_tools as _setup_tools  # noqa: E402

_setup_tools()                     # Windows installer: bundled Tesseract / Ghostscript

__all__ = ["digitize", "write_outputs", "__version__"]


def __getattr__(name):
    """``resrijan.digitize`` / ``resrijan.write_outputs`` are imported on first use, so that
    ``import resrijan`` (the GUI launcher, ``--version``) stays light and cannot fail on a library."""
    if name in ("digitize", "write_outputs"):
        from . import pipeline
        return getattr(pipeline, name)
    raise AttributeError(f"module 'resrijan' has no attribute {name!r}")
