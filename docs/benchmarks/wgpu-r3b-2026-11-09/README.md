# R3b sheet captures — 2026-11-09

All comparison images have **GL on the left, Metal on the right**. These are
composer raster views, `tecnico`, white paper, a saved orthographic scene,
300 dpi. Pusher car and marquee use 100 × 70 mm frames (1181 × 827 pixels).
The model files were read only. The JSON files record scale and elapsed time.

Observed differences:

- Pusher car: same framing and outline positions, but Metal has heavier outer
  profiles, especially the large circle and long planar boundaries.
- Marquee: same framing and column positions; Metal produces darker fine edge
  clusters at the lettering and more visible thin subdivisions around rings.
- These are technical-look captures, not validation of textured/shadowed styles,
  perspective, or section clipping. No pixel-parity claim is made.

The timing interval covers `ComposerWindow.render_frame`, including annotation
projection, Metal device creation, packing, upload, capture and image conversion.
GL's visible widget was initialized before this interval. Thus these measure
current end-to-end sheet operations, not equivalent warm resident GPU passes.
The Metal path intentionally uses a separate transient renderer and does not
reuse resident GPU buffers. It cannot disturb the interactive renderer, but
repeated views pay setup/upload costs and peak memory increases.

Reproduce with `.venv-work/bin/python scripts/wgpu_sheets_compare.py MODEL.igz`
in a subprocess with a 240-second timeout. Texture extraction and QSettings
are redirected into `.spike-results` within this worktree. Use a worktree-local
`TMPDIR` as well. Individual GL/Metal PNGs and paired PNGs are retained.

Current limitation: GL applies saved section planes to sheets. Metal has no
section clipping API; the new capture path raises `NotImplementedError` for an
active visible cut instead of returning a misleading uncut drawing. This is an
**unmet R3b acceptance requirement**, not deferred silently to R3c.

Ride measurement: A3 landscape (420 × 297 mm), 300 dpi, 4961 × 3508 pixels,
1:750 technical view. The paired run measured **GL 40.1683 s** and
**Metal 32.5727 s**. A separate Metal-only run measured 31.2192 s; both GUI
children exited normally before their 240-second limits. The single Metal PNG
is from that second run; the comparison PNG retains the first paired capture.
The independent run overlapped the end of the paired run, so these numbers
are diagnostic single samples under a shared workload, not a speedup gate.
Ride framing matches; Metal shows more fine edge detail through dense track
and support clusters. Shader/profile parity remains a renderer issue.

Pass `metal` or `gl` as the optional second argument to isolate a renderer.
