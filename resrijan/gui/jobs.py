"""Background jobs: run a function in a worker thread, stream its console output to the log,
and deliver the result (or the error) back to the GUI thread."""
from __future__ import annotations

import contextlib
import io
import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot


class _Stream(io.TextIOBase):
    def __init__(self, emit):
        self._emit, self._buf = emit, ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)
        return len(s)

    def flush(self):
        if self._buf:
            self._emit(self._buf)
            self._buf = ""


class _Worker(QObject):
    line = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn

    def run(self):
        out = _Stream(self.line.emit)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                res = self.fn()
            out.flush()
            self.done.emit(res)
        except Exception as exc:  # noqa: BLE001 – every error goes to the GUI
            out.flush()
            self.failed.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")


class JobRunner(QObject):
    """One job at a time. ``started(title)``, ``line(text)``, ``finished(ok)`` drive the status bar
    and the log; the per-job callbacks receive the result or the error text.

    Results arrive through slots of this object, which lives in the GUI thread, so the callbacks
    always run in the GUI thread (queued connections across threads)."""
    started = Signal(str)
    line = Signal(str)
    finished = Signal(bool)

    def __init__(self, parent=None, synchronous: bool = False):
        super().__init__(parent)
        self.synchronous = synchronous          # tests: run in the calling thread
        self._thread: Optional[QThread] = None
        self._worker: Optional[_Worker] = None
        self._busy = False
        self._on_done: Optional[Callable[[Any], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None

    @property
    def busy(self) -> bool:
        return self._busy

    def run(self, title: str, fn: Callable[[], Any], on_done: Callable[[Any], None],
            on_error: Optional[Callable[[str], None]] = None) -> bool:
        if self._busy:
            return False
        self._busy = True
        self._on_done, self._on_error = on_done, on_error
        self.started.emit(title)
        w = _Worker(fn)
        w.line.connect(self._relay)
        w.done.connect(self._done)
        w.failed.connect(self._failed)
        self._worker = w
        if self.synchronous:
            w.run()
            return True
        t = QThread()
        w.moveToThread(t)
        t.started.connect(w.run)
        self._thread = t
        t.start()
        return True

    @Slot(str)
    def _relay(self, text: str):
        self.line.emit(text)

    @Slot(object)
    def _done(self, res):
        cb = self._on_done
        self._cleanup()
        self.finished.emit(True)
        if cb:
            cb(res)

    @Slot(str)
    def _failed(self, msg: str):
        cb = self._on_error
        self._cleanup()
        self.line.emit(msg)
        self.finished.emit(False)
        if cb:
            cb(msg)

    def _cleanup(self):
        t = self._thread
        if t is not None:            # let the worker's run() return before the objects are dropped
            t.quit()
            t.wait()
        self._thread, self._worker, self._busy = None, None, False
        self._on_done = self._on_error = None

    def shutdown(self):
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
