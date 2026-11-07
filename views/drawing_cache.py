"""Disposable, content-addressed drawing data. Never stores executable objects.

The .igz geometry remains authoritative. Keys cover its complete deferred
source, paint, lighting, Python/Qt/NumPy and the code/native kernels that bake
it. Corrupt, obsolete or unwritable caches are ordinary misses. One bounded
worker writes immutable bake results, off the UI thread.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import marshal
import math
import os
from pathlib import Path
import queue
import sqlite3
import struct
import sys
import threading
import types
import zlib

import numpy as np

_VERSION = 1
_MAX_ENTRY = 512 * 1024 * 1024
_MAX_BYTES = 4 * 1024 ** 3
_MAX_PENDING_BYTES = 1024 ** 3
_SIGNATURE = None
_STORE = None
_TEXTURES = {}
_EXCLUDE = {'fp', 'vkey', 'uid', 'msig', 'mesh', 'faces'}


def _code(code):
    constants = tuple(_code(c) if isinstance(c, types.CodeType) else c
                      for c in code.co_consts)
    return code.replace(co_filename='', co_firstlineno=1, co_linetable=b'',
                        co_consts=constants)


def signature():
    global _SIGNATURE
    if _SIGNATURE is None:
        from PySide6.QtCore import qVersion
        from core import lazy_mesh, mesh, materials, texture, _native
        from formats import igz
        from views import array_bake, viewport
        h = hashlib.sha256(str((_VERSION, sys.version_info[:3],
                               np.__version__, qVersion())).encode())
        for module in (lazy_mesh, mesh, materials, texture, igz, array_bake, viewport):
            # Both normal Python and PyInstaller expose their compiled
            # module. Hash all code/constants, including class properties,
            # without runtime counters or machine-specific source paths.
            code = module.__loader__.get_code(module.__name__)
            if code is None:
                raise ValueError('renderer module has no code')
            h.update(marshal.dumps(_code(code)))
        native = _native.available()
        if native is not None:
            # The public module is a Python re-export package. Its .py
            # is inside the frozen archive; fingerprint the actual kernel.
            kernel = sys.modules[native.face_geometry.__module__]
            with open(kernel.__file__, 'rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(block)
        _SIGNATURE = h.hexdigest()
    return _SIGNATURE


def source_key(mesh):
    d = mesh.__dict__
    # Deferred sources are immutable; editing materialises the mesh.
    key = d.get('_drawing_source_key')
    if key is None:
        h = hashlib.sha256(signature().encode())
        for name, value in sorted(d['_deferred_source'].items()):
            h.update(name.encode())
            if isinstance(value, np.ndarray):
                h.update(str((value.dtype.str, value.shape)).encode())
                h.update(np.ascontiguousarray(value).tobytes())
            else:
                h.update(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
        key = d['_drawing_source_key'] = h.hexdigest()
    return key


def key_for(vp, mesh, paint):
    from core.materials import material_sig
    from formats.igz import _texture_entries
    # Source metadata is immutable until materialisation. Walk its face
    # attribute table once, rather than again for each painted variant and
    # again when the staged chunk is consumed. Still stat the files below:
    # replacing a texture at the same path must invalidate the cache.
    d = mesh.__dict__
    paths = d.get('_drawing_texture_paths')
    if paths is None:
        paths = d['_drawing_texture_paths'] = tuple(dict.fromkeys(
            tex.get('path') for tex in _texture_entries(d['_deferred_source']['meta'])
            if tex.get('path')))
    paths = dict.fromkeys((*paths, *(tex.get('path') for tex in _texture_entries(paint))))
    textures = []
    for path in paths:
        if not path:
            continue
        try:
            stat = os.stat(path)
            stamp = (path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            digest = _TEXTURES.get(stamp)
            if digest is None:
                digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                _TEXTURES[stamp] = digest
            textures.append((path, digest))
        except OSError:
            textures.append((path, None))
    values = (source_key(mesh), material_sig(paint), vp._LIGHT.toTuple(),
              vp.DEFAULT_FACE_COLOR, textures)
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def pack(value):
    """JSON structure plus typed binary spans; no pickle/object arrays."""
    chunks, offset = [], 0
    def span(raw):
        nonlocal offset
        size = len(raw); start = offset
        chunks.append(raw); offset += size
        if offset > _MAX_ENTRY:
            raise ValueError('drawing cache entry too large')
        return start, size
    def encode(v):
        if isinstance(v, np.ndarray):
            if v.dtype.hasobject:
                raise ValueError('object array')
            a = np.ascontiguousarray(v)
            return ['a', a.dtype.str, a.shape, *span(a.tobytes())]
        if isinstance(v, bytes):
            return ['b', *span(v)]
        if isinstance(v, tuple):
            return ['t', [encode(x) for x in v]]
        if isinstance(v, list):
            if len(v) >= 32 and (v[0] is None or type(v[0]) in (str, int, float, bool))                     and all(x == v[0] for x in v):
                return ['r', v[0], len(v)]
            return ['l', [encode(x) for x in v]]
        if isinstance(v, dict):
            return ['d', [[encode(k), encode(x)] for k, x in v.items()]]
        if v is None or type(v) in (str, int, float, bool):
            return v
        raise ValueError('unsupported drawing cache value')
    header = json.dumps(encode(value), separators=(',', ':')).encode()
    raw = struct.pack('<I', len(header)) + header + b''.join(chunks)
    if len(raw) > _MAX_ENTRY:
        raise ValueError('drawing cache entry too large')
    return zlib.compress(raw, 1)


def unpack(blob):
    decoder = zlib.decompressobj()
    raw = decoder.decompress(blob, _MAX_ENTRY + 1)
    if len(raw) > _MAX_ENTRY or not decoder.eof or len(raw) < 4:
        raise ValueError('invalid drawing cache entry')
    size, = struct.unpack_from('<I', raw)
    if size > len(raw) - 4:
        raise ValueError('invalid drawing cache header')
    data = memoryview(raw)[4 + size:]
    def span(start, count):
        if type(start) is not int or type(count) is not int or start < 0 \
                or count < 0 or start + count > len(data):
            raise ValueError('invalid drawing cache span')
        return data[start:start + count]
    def decode(v):
        if not isinstance(v, list):
            return v
        kind = v[0]
        if kind == 'a':
            dtype, shape = np.dtype(v[1]), tuple(v[2])
            if dtype.hasobject or len(shape) > 8 or any(
                    type(n) is not int or n < 0 for n in shape):
                raise ValueError('invalid cached array')
            if math.prod(shape) * dtype.itemsize != v[4]:
                raise ValueError('invalid cached array length')
            return np.frombuffer(span(v[3], v[4]), dtype=dtype).copy().reshape(shape)
        if kind == 'b': return bytes(span(v[1], v[2]))
        if kind == 't': return tuple(decode(x) for x in v[1])
        if kind == 'l': return [decode(x) for x in v[1]]
        if kind == 'r':
            if type(v[2]) is not int or not 0 <= v[2] <= _MAX_ENTRY // 8 \
                    or not (v[1] is None or type(v[1]) in (str, int, float, bool)):
                raise ValueError('invalid cached repeated list')
            return [v[1]] * v[2]
        if kind == 'd': return {decode(k): decode(x) for k, x in v[1]}
        raise ValueError('invalid drawing cache tag')
    return decode(json.loads(raw[4:4 + size]))


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.reader = self._connect()
        self.reader.execute('PRAGMA journal_mode=WAL')
        self.reader.execute('CREATE TABLE IF NOT EXISTS entries '
                            '(key TEXT PRIMARY KEY, value BLOB NOT NULL)')
        self.reader.commit()
        self.pending = queue.Queue(maxsize=8192)
        self._pending_values = {}
        self._pending_bytes = 0
        self._pending_lock = threading.Lock()
        self.hits = self.misses = 0
        self._hot = OrderedDict()
        self._hot_bytes = 0
        self.worker = threading.Thread(target=self._write, daemon=True,
                                       name='drawing-cache')
        self.worker.start()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=0.05)
        db.execute('PRAGMA synchronous=NORMAL')
        return db

    def get(self, key):
        with self._pending_lock:
            pending = self._pending_values.get(key)
        if pending is not None:
            self.hits += 1
            return pending
        hot = self._hot.get(key)
        if hot is not None:
            self._hot.move_to_end(key)
            self.hits += 1
            return hot[0]
        try:
            row = self.reader.execute('SELECT value FROM entries WHERE key=?',
                                      (key,)).fetchone()
            value = unpack(row[0]) if row else None
            if value is None: self.misses += 1
            else:
                self.hits += 1
                weight = self._weight(value)
                if weight <= 16 * 1024 ** 2:
                    self._hot[key] = (value, weight)
                    self._hot_bytes += weight
                    while self._hot_bytes > 64 * 1024 ** 2 or len(self._hot) > 1024:
                        _, (_, size) = self._hot.popitem(last=False)
                        self._hot_bytes -= size
            return value
        except (sqlite3.Error, ValueError, TypeError, KeyError, IndexError,
                struct.error, zlib.error, OverflowError):
            return None

    @staticmethod
    def _weight(value):
        if isinstance(value, np.ndarray): return value.nbytes
        if isinstance(value, bytes): return len(value)
        if isinstance(value, dict): return sum(Store._weight(v) for v in value.values())
        if isinstance(value, tuple): return sum(Store._weight(v) for v in value)
        if isinstance(value, list): return 8 * len(value)
        return 32

    def put(self, key, payload):
        if not self.worker.is_alive():
            return
        weight = self._weight(payload)
        with self._pending_lock:
            if key in self._pending_values or self._pending_bytes + weight > _MAX_PENDING_BYTES:
                return
            try:
                self.pending.put_nowait((key, payload))
                self._pending_values[key] = payload
                self._pending_bytes += weight
            except queue.Full:
                pass                   # cache misses never block interaction

    def close(self):
        self.pending.join()
        self.pending.put(None)
        self.worker.join()
        self.reader.close()

    def _write(self):
        db = None
        try:
            db = self._connect()
            size = db.execute('SELECT coalesce(sum(length(value)),0) FROM entries').fetchone()[0]
            while True:
                job = self.pending.get()
                if job is None:
                    self.pending.task_done()
                    break
                key, payload = job
                try:
                    blob = pack(payload)
                    old = db.execute('SELECT length(value) FROM entries WHERE key=?', (key,)).fetchone()
                    db.execute('INSERT OR REPLACE INTO entries VALUES (?,?)', (key, blob))
                    size += len(blob) - (old[0] if old else 0)
                    while size > _MAX_BYTES:
                        rows = db.execute('SELECT key,length(value) FROM entries ORDER BY rowid LIMIT 64').fetchall()
                        if not rows: break
                        db.executemany('DELETE FROM entries WHERE key=?', [(r[0],) for r in rows])
                        size -= sum(r[1] for r in rows)
                    db.commit()
                except (OSError, sqlite3.Error, ValueError, TypeError, MemoryError):
                    if db is not None: db.rollback()
                finally:
                    with self._pending_lock:
                        self._pending_values.pop(key, None)
                        self._pending_bytes -= self._weight(payload)
                    self.pending.task_done()
        finally:
            if db is not None: db.close()


def store():
    global _STORE
    if _STORE is None:
        try:
            from PySide6.QtCore import QStandardPaths
            root = os.environ.get('INGETRAZO_DRAWING_CACHE_DIR') or str(
                Path(QStandardPaths.writableLocation(QStandardPaths.GenericCacheLocation))
                / 'IngeTrazo' / 'drawing')
            _STORE = Store(Path(root) / ('v%d.sqlite' % _VERSION))
        except (OSError, sqlite3.Error):
            _STORE = False
    return _STORE


def restore(vp, mesh, paint):
    """Stage a matching bake before geometry prefetch does the work again."""
    try:
        cache = store()
        if not cache: return None
        key = key_for(vp, mesh, paint)
    except (OSError, ValueError, TypeError, AttributeError, ImportError):
        return None
    staged = mesh.__dict__.setdefault('_drawing_staged', {})
    if key in staged: return staged[key]
    payload = cache.get(key)
    if payload is not None:
        from core.lazy_mesh import Plan
        try:
            plan = Plan(**payload['plan'])
            chunk = payload['chunk']
            if not isinstance(chunk, dict) or 'edges' not in chunk:
                return None
            mesh.__dict__['_deferred_plan'] = plan
            mesh.__dict__['_deferred_geom'] = payload['geometry']
            staged[key] = payload
        except (KeyError, TypeError, ValueError):
            return None
    return payload


def restored_chunk(vp, mesh, paint, msig, vkey, uid):
    payload = restore(vp, mesh, paint)
    if payload is None: return None
    from views.array_bake import DeferredFaces, LazyFingerprint, _attrs_table
    plan = mesh.__dict__['_deferred_plan']
    src = mesh.__dict__['_deferred_source']
    chunk = dict(payload['chunk'])
    chunk.update(mesh=mesh, uid=uid, vkey=vkey, msig=msig,
                 faces=DeferredFaces(mesh, payload['face_indices']),
                 fp=LazyFingerprint(lambda: (mesh, plan, _attrs_table(src),
                                     np.asarray(src['face_attr'], dtype=np.int64))))
    return chunk


def remember(vp, mesh, paint, chunk):
    try:
        cache = store()
        if not cache: return
        key = key_for(vp, mesh, paint)
    except (OSError, ValueError, TypeError, AttributeError, ImportError):
        return
    plan = mesh.__dict__['_deferred_plan']
    payload = {'chunk': {k: v for k, v in chunk.items() if k not in _EXCLUDE},
               'face_indices': chunk['faces'].index,
               'plan': {k: v for k, v in vars(plan).items() if k != 'extra'},
               'geometry': mesh.__dict__['_deferred_geom']}
    cache.put(key, payload)


def prepare_file(path):
    """Prewarm without opening/closing the user's window; CLI diagnostics."""
    global _STORE
    import time
    from core.scene import Scene
    from formats.igz import load_into
    from views.viewport import Viewport
    start = time.perf_counter()
    signature()                     # surface cache setup errors in this CLI
    scene = Scene()
    load_into(scene, Path(path))
    read = time.perf_counter()
    vp = Viewport()
    vp.scene = scene
    vp.prepare_drawing()
    prepared = time.perf_counter()
    cache = store()
    if cache:
        cache.pending.join()
    result = {'read_seconds': round(read - start, 3),
              'prepare_seconds': round(prepared - read, 3),
              'cache_hits': cache.hits if cache else 0,
              'cache_misses': cache.misses if cache else 0}
    if cache:
        cache.close()
        _STORE = None
    return result
