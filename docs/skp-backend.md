# SKP import backend seam

> **2026-09-28.** IngeTrazo no longer runs, downloads or links to any
> proprietary .skp tooling: the former external converter and its automatic
> download are gone, the validation tests built on it are gone, and the `.skp`
> export is off because OpenSKP's writer builds on a blank template document
> that IngeTrazo no longer distributes. `.skp` files are read with OpenSKP
> only. Where the sections below say "the oracle", they mean the reference
> output the reader was validated against at the time.

IngeTrazo aims to open **any** `.skp` (old → recent). This document describes
the single seam that decouples the app from *how* a `.skp` is read.

## Backends

- **OpenSKP** (pure Python, MIT — https://github.com/iamahsanmehmood/openskp).
  Offline, Linux-native, no Wine, no proprietary DLL. **Wired and working** (see
  "What works / what's missing"). An **optional dependency**: `pip install
  openskp` (pulls `trimesh`). Not in `requirements.txt` yet — the seam falls
  back gracefully when it's absent.

## The seam — `formats/skp.py`

**Parse then apply.** A backend *parses* a file into a plain **payload** (world-
space face loops), touching no `Scene`. The heavy parse runs *outside* the undo
history; `apply_payload` then adds the geometry cheaply inside a command — so a
failed or empty parse never leaves a half-applied edit.

Public API:

- `detect_format(path) -> "skp" | "unknown"` — from the first bytes. Real `.skp`
  files (legacy MFC **and** 2021+) begin with the same UTF-16 format
  marker (or a `PK` ZIP wrapper), so the *era* is **not** observable from the
  magic bytes — and doesn't need to be, since OpenSKP handles the range.

## Legacy (pre-2021) MFC container — SUPPORTED (2026-07-22)

Classic `.skp` files (versions ≤2020; validated on real 2016/2017/2018
models) are ONE uncompressed MFC `CArchive` stream with a global 1-based
store map — no ZIP, no `model.dat`. Our fork adds
`openskp/legacy.py`: a full walker (materials + textures, layers,
half-edge kernel, definitions/instances/groups, face-camera flags, UV
matrices, dims/texts/guides/section planes) that emits the same
`full_parse()` dict, so `SkpFile.parse()` and the whole IngeTrazo seam
work unchanged. Validated: exact face/edge/area/bbox parity on five
user models against their VFF (2021+) re-saves; `skp_diff`
fingerprints identical through `apply_payload` (incl. materials and
textures). Key decoding notes (where real files differ from the public
2017 spec) are in the module docstring. Known gaps: files with fewer
than 2 materials can't bootstrap the slot base yet, legacy colorized materials untinted, CImage entities and doc
thumbnail skipped, positioned-texture UV parity unverified visually.
- `can_handle(path) -> bool` — a pure backend is available and recognises it
  (does not guarantee a non-empty parse).
- `parse_skp(path, progress=None) -> payload` — first backend that yields
  geometry; raises `NeedsConverter` on an unrecognised file, a parser error, or
  an empty parse.
- `apply_payload(scene, payload) -> backend_name` — add the payload as reference
  groups.
- `load_skp(scene, path)` — `apply_payload(parse_skp(...))`, for the diff harness.
- `NeedsConverter`, `backends_status()`.

Backends implement `available()`, `supports(fmt)`, `parse(path, progress)`.

### Cascade in the UI

`views/main_window.py::import_skp_path`:

1. If `can_handle(skp)` → `parse_skp` (outside history). Non-empty → apply
   through `SnapshotImport`.
2. Empty or `NeedsConverter` → the file is reported as unreadable, with the
   way around it (export COLLADA or OBJ from the program that made it). There is no
   converter behind it any more.

## The OpenSKP adapter — `formats/skp_openskp.py`

Isolated so `import openskp` is lazy. OpenSKP 0.2.0 model (by introspection):

- `SkpFile.open(path).parse()` → `SkpModel(definitions, materials, layers,
  version)`.
- `Definition(id, name, vertices{id→Vertex(x,y,z)}, edges{id→Edge(v1_id,v2_id)},
  faces{id→Face}, instances[Instance])`.
- `Face(loops, normal, material_id)`; each loop is `[(edge_id, sense), …]`,
  first = outer, rest = holes; `sense` 1 walks `v1→v2`.
- `Instance(matrix[13], ref_idx→def id, children)` — 3×3 row-major + translation.

The .skp format is **inches, Z-up** (same up axis as IngeTrazo) → scale ×0.0254, no
axis swap. The instance tree is flattened to world-space polygons (reference
geometry, one group). Enable/disable via `_OpenSkpBackend` in `formats/skp.py`.

## What works / what's missing (measured with `scripts/skp_diff.py`)

Validated against a reference oracle on real files (e.g. `demuna.skp`, a .skp
of the 2022 version):

- ✅ **Bounding box exact** — units, Z-up and instance transforms correct.
- ✅ **Geometry ~90–95% complete** — faces/vertices/triangles within ~5–9% of
  the oracle.
- ✅ **Materials / colours** — resolved. `Face.material_id` joins through
  `SkpModel.materials_by_id`, added by **our upstream PR**
  ([openskp#3](https://github.com/iamahsanmehmood/openskp/pull/3)).
- ✅ **Textures** — resolved. `Material.texture` (image bytes + tile size in
  inches), added by **our upstream PR**
  ([openskp#4](https://github.com/iamahsanmehmood/openskp/pull/4)). The adapter
  writes the images to the app's own cache —
  `<user data>/IngeTrazo/textures/skp/<stem>-<hash of path+size+mtime>/`,
  overridable with `$INGETRAZO_TEXTURE_CACHE`, emptied from
  *File ▸ Import ▸ Clear imported texture cache…* — so importing never creates
  a folder next to the user's `.skp` (it used to write `<stem>/` there, the
  usual COLLADA-export convention). Saving the document copies those
  images **into** the `.igz` container (`formats/igz.py`), which is what makes
  it portable; the cache is disposable and re-fills on open. It maps them with
  IngeTrazo's planar
  projection at the material's real tile size. Measured: **18/18 materials and
  2/2 textures — exact parity with the oracle**; those rows no longer appear
  in the diff.
  Until the PRs ship on PyPI, install from the integration branch:
  `pip install git+https://github.com/tuxiasumari/openskp@ingetrazo#subdirectory=packages/python`
  (branch `ingetrazo` = upstream `main` + both PR branches merged). With PyPI
  0.2.0 (no joins) faces import uncoloured.
- ✅ **"~5–9% skipped faces" — resolved: it was a measurement artefact, not
  lost geometry.** The raw DAE carries 4516 triangles = exactly what OpenSKP
  parses, and **total surface area matches to 0.00%** (327.268 vs 327.269 m²).
  The count deltas came from comparing a fused path (the DAE import runs
  coplanar fusion + weld + double-face dedupe) against raw .skp polygons.
  Two fixes landed: the harness fingerprint now carries **`area_m2`** (the
  fusion-invariant completeness metric — when areas agree, count deltas are
  labelled as post-processing); and `apply_payload` now runs the **same
  fusion pipeline as the DAE import** (`fuse_coplanar_loops` +
  `soften_smooth_edges`, hole-carrying faces added directly), so a `.skp`
  through the pure backend looks identical to one through the converter.
  After both: triangles Δ1.3%, vertices Δ0.7%, faces 262 vs 389 — the pure
  path fuses *better* (it starts from the file's original polygons, not
  reconstructed triangles). Perf: plaza Yanque (34 MB) parses in ~12 s pure
  Python — 97k faces, 42 273 m², 19 materials + 10 textures.
- ✅ **Grouping — resolved (with shared components).** The
  adapter now mirrors the DAE reference import: the root's loose faces become
  one group named after the file, each top-level instance becomes its own
  group carrying its .skp definition name, and a definition placed ≥2
  times above the DAE sharing thresholds becomes **one prototype** (extracted
  at any depth) with each copy an O(1) `Group.xform` instance. Measured:
  demuna → 3 groups, exact parity with the oracle and with *better* names
  ('Niraj', 'Derrick' vs the reference's 'node'); plaza Yanque → 39 groups of which
  31 are instances sharing 5 prototypes, and import time dropped 12.1 → 7.5 s
  (each prototype fuses once, not per copy). Library definitions never placed
  in the model are not emitted.
- ⚠️ **Instance-tree misplacement (upstream, latent)** — in `demuna.skp` the
  parser hangs Rodeo#2's instance under the *Derrick* definition instead of
  the root, and `CASCO.dwg` (137 verts / 156 edges, a pure-wireframe DWG
  import) is never instanced. Positions still come out right in this file,
  but the hierarchy is wrong — worth an upstream issue with the repro.

These gaps are the concrete contribution targets for OpenSKP (see
`docs/openskp-collaboration.md`). Geometry — the hard part — already works.

## OpenSKP 1.5 import update (2026-11-08)

The runtime dependency is pinned to `902ca8027efbe9faf1d31fcec4fea485a2f5fd1c`,
upstream tag `python-v1.5.0`. `git ls-remote --tags` verified that tag;
`git merge-base --is-ancestor` verified that the previous pin
`291700bc213655a00461838de71e5f206311e619` is its ancestor. The intervening
Python history includes analytic arcs (#463), group kinds (#461), legacy
annotation fixes (#384, #473, #484), and placement scalar handling (#451).
The adapter now treats matrix element 12 as OpenSKP's scale factor (1/w),
multiplying both the linear part and translation.

Compatibility audit:

- Removed the legacy dimension/path and anchored-text replacements: 1.5
  already handles them. Replacing its text reader would lose inline anchors.
- Retained the definition-list tail fix, preserving 1.5's new `inline_stack`
  completion check and removal of consumed inline records.
- Retained the 2019 layer tail fix. An unrelated upstream version check for
  SketchUp 3 is not evidence that the two extra 2019 bytes are handled;
  the previous capability check incorrectly skipped the fix on 1.5.
- Retained the layer table bridge and numeric face-layer resolution: the
  public model still omits the table. The `full_parse` wrapper also keeps
  instance persistent IDs now.
- Retained the `iter_top_level_lazy` tag-folder bridge: `F801/9B3A` remains
  opaque. Its signature and lazy-node payload access still work in 1.5.
- Retained group-kind observation for the classic `CGroup` distinction and
  raw definition records; also consume public `Definition.is_group`.

### Curves

`Edge.curve_id` associates segments with both analytic arcs and ordinary
polyline curves. Each placed curve contributes transformed endpoint pairs to
its mesh payload. After faces and loose edges are built, the importer resolves
those endpoints through the mesh weld and assigns one `Mesh.next_curve_id()`
to the surviving segments. Different flattened placements get different IDs;
shared component meshes keep their shared curve topology. Existing soft,
smooth and hidden display flags remain authoritative.

No analytic parameters are stored in the IngeTrazo document. For a later
phase, `Definition.arcs[curve_id]` exposes:

- `center`: three coordinates in inches, definition-local space.
- `normal`: dimensionless unit plane normal.
- `x_axis`, `y_axis`: parameter vectors in inches, definition-local space.
- `start_angle`, `end_angle`: radians.
- `radius`: computed length of `x_axis`, in inches.
- `is_full_circle`: computed Boolean, covering equal endpoints in classic
  files and a full 2π sweep in modern files.

The parameterization is `center + cos(t)*x_axis + sin(t)*y_axis`. Nonuniformly
scaled arcs can have unequal, nonperpendicular parameter vectors; radius alone
cannot represent those arcs.

### Persistent identities

The 1.5 Python `Instance` dataclass has no persistent-ID field. Its `guid`
comes from `6819` (`ref_guid`), and is not used as a placement identity.
Modern definitions expose their entity ID as `Definition.id` and definition
GUID as `Definition.guid`; no model GUID is exposed.

Modern instance records (`6419`) retain the entity-info subtree:
`D007 → DC05 → DE05`. Records have a two-byte tag and a little-endian u32
length; `DE05` contains OpenSKP's variable integer. The compatibility bridge
reads that ID from each retained subtree before the public model drops it,
then attaches `persistent_id` to the matching instance by definition/order.
It never substitutes the referenced definition's ID for an instance ID.

Classic 2017+ entity preambles already decode a PID: a byte mask followed by
one byte for each set bit, contributing that byte at `8*bit` in the integer.
The bridge retains the instance reader's own preamble ID through
`_fill_builder`. Older classic files have no such ID; those placements retain
random UIDs. Legacy Image records currently also fall back to random UIDs.
Classic definition IDs are archive slots, not persistent IDs.

The file namespace is SHA-256 of the sorted definition name/GUID pairs
(including multiplicity), because no model GUID is exposed. UUID5 over that
namespace and the placement's PID path is truncated to 16 hexadecimal digits.
The ancestor PID path distinguishes a nested entity placed through multiple
copies of its enclosing component. Root loose geometry uses a reserved root
identity. Missing IDs or collisions with existing groups use a random UID;
importing twice into one scene therefore does not create duplicate UIDs.
Renaming definitions changes this fallback namespace, and files with identical
definition lists share it (including empty lists). A future model-GUID decoder
would improve identity across edits and between such files.

Regression fixtures `tests/data/skp_arcs_2017.skp`, `skp_arcs_2021.skp` and
`skp_instances_2021.skp` come unchanged from OpenSKP tag `python-v1.5.0`,
`packages/python/tests/fixtures/{arcs_2017,arcs_2021,instance_scale_term_2021}.skp`.
They were authored with SketchUp's library upstream. License attribution is
in `tests/data/openskp-LICENSE.txt`. Tests exercise face-bounded and loose arcs,
polyline copies, real modern and classic IDs, and collision fallback.
