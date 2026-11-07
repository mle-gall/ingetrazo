"""UI-sliced snapshot capture followed by a detached, single writer thread."""
from __future__ import annotations

import logging
from queue import SimpleQueue
import threading
import time
import uuid

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication

from core import autosave
from formats.igz_snapshot import snapshot_steps


class BackgroundAutosave(QObject):
    SLICE_SECONDS = .006

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pending = []
        self.job = None
        self.steps = None
        self.writing = False
        self.results = SimpleQueue()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.advance)
        self.last_error = None
        self.max_slice_seconds = 0.0

    @property
    def busy(self):
        return bool(self.job or self.pending or self.writing)

    def request(self, documents):
        for doc in documents:
            if doc not in self.pending and (self.job is None or self.job['doc'] is not doc):
                self.pending.append(doc)
        if self.busy:
            self.timer.start()

    def cancel(self):
        """Disable future publication without waiting for an in-flight worker."""
        self.pending.clear()
        if self.job is not None:
            self.job['cancelled'] = True
        if not self.writing:
            self.steps = None
            self.job = None
            self.timer.stop()

    def _available(self, doc):
        win = self.window
        return (doc in win._documents and doc.viewport is not None
                and not getattr(win, '_opening_document', False)
                and not (doc is win._doc and win._workspace is not None))

    def _valid(self, job, capturing=False):
        doc = job['doc']
        if job.get('cancelled') or not self._available(doc):
            return False
        if (doc.viewport.scene is not job['scene'] or doc.path != job['path']
                or doc.untitled_no != job['untitled']
                or autosave.slot_epoch(job['slot']) != job['epoch']):
            return False
        return not capturing or (
            doc.viewport.scene.content_version == job['version']
            and id(doc.viewport.scene.mesh) == job['mesh']
            and id(doc.viewport.scene.edit_group) == job['context'])

    def _start_next(self):
        while self.pending:
            doc = self.pending.pop(0)
            if not self._available(doc) or not self.window._doc_is_dirty(doc):
                continue
            scene = doc.viewport.scene
            version = scene.content_version
            if version == doc.autosaved_version:
                continue
            scene.camera_home = self.window._camera_dict(doc.viewport)
            slot = autosave.slot_for(doc.path, doc.untitled_no)
            self.job = dict(doc=doc, scene=scene, version=version,
                            path=doc.path, untitled=doc.untitled_no,
                            mesh=id(scene.mesh), context=id(scene.edit_group),
                            slot=slot, epoch=autosave.slot_epoch(slot),
                            camera=self.window._camera_dict(doc.viewport),
                            navigation_until=0.0)
            self.steps = snapshot_steps(scene)
            return
        self.timer.stop()

    def advance(self):
        if self.writing:
            if self.results.empty():
                return
            stage, error = self.results.get()
            self.writing = False
            job = self.job
            try:
                if error is not None:
                    raise error
                if self._valid(job) and self.window._doc_is_dirty(job['doc']):
                    # Both clear() and publication run on the UI thread.
                    # A clean save/close cannot race this final rename.
                    stage.replace(job['slot'])
                    job['doc'].autosaved_version = job['version']
                    from core.i18n import tr
                    self.window.statusBar().showMessage(tr('Auto-saved.'), 2000)
            except Exception as exc:
                self.last_error = str(exc)
                logging.getLogger(__name__).warning('Background autosave: %s', exc)
            finally:
                stage.unlink(missing_ok=True)
                self.job = None
            return
        if getattr(self.window, '_opening_document', False):
            return
        if QApplication.mouseButtons() != Qt.NoButton:
            return
        if self.job is None:
            self._start_next()
            if self.job is None:
                return
        if not self._valid(self.job, capturing=True):
            doc = self.job['doc']
            # A changed model restarts capture at the back of the queue;
            # closed/saved documents simply disappear from it.
            if self._available(doc) and self.window._doc_is_dirty(doc):
                self.pending.append(doc)
            self.steps = None
            self.job = None
            return
        vp = self.job['doc'].viewport
        camera = self.window._camera_dict(vp)
        now = time.monotonic()
        if camera != self.job['camera']:
            self.job['camera'] = camera
            self.job['navigation_until'] = now + .25
        if now < self.job['navigation_until']:
            return  # Trackpad orbit/zoom need not hold a mouse button.
        if vp.active_tool is not None and vp._tool_busy(vp.active_tool):
            return
        started = time.perf_counter()
        try:
            while time.perf_counter() - started < self.SLICE_SECONDS:
                next(self.steps)
        except StopIteration as done:
            prepared = done.value
            self.steps = None
            slot = self.job['slot']
            stage = slot.with_name('.' + slot.name + '.' + uuid.uuid4().hex + '.pending')
            results = self.results
            self.writing = True
            # The worker captures only detached data and its staging path.
            def write():
                error = None
                try:
                    from formats.igz import write_prepared
                    write_prepared(prepared, stage, background=True)
                except Exception as exc:
                    error = exc
                results.put((stage, error))
            threading.Thread(target=write, name='IGZ autosave', daemon=True).start()
        except Exception as exc:
            self.last_error = str(exc)
            logging.getLogger(__name__).warning('Autosave snapshot: %s', exc)
            self.steps = None
            self.job = None
        finally:
            self.max_slice_seconds = max(self.max_slice_seconds,
                                         time.perf_counter() - started)
