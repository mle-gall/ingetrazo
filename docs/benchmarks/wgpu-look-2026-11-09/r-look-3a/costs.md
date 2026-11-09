# Ride frame-cost samples — 2026-11-09

Complete ride, 76,029 instances; 2000×1400 (2× HiDPI), edges on. Three rounds, 105 measured frames per configuration. Values are medians in milliseconds.

| AO | MSAA | CPU ms | GPU ms | Wall ms |
|---|---|---:|---:|---:|
| off | False | 20.66 | 21.17 | 20.88 |
| half | False | 16.80 | 18.46 | 17.02 |
| full | False | 18.04 | 22.03 | 19.80 |
| off | True | 33.11 | 33.30 | 33.29 |
| half | True | 37.26 | 38.26 | 37.37 |
| full | True | 41.58 | 42.20 | 41.69 |

These timestamps span whole geometry/AO frames, not the AO pass alone. Concurrent machine activity remained significant: the no-MSAA half-resolution median is lower than AO-off, so subtracting those medians would be misleading. Full resolution was 3.57 ms slower than half without MSAA and 3.94 ms slower with MSAA in this run. Half resolution remains the default. The isolated ~3 ms AO budget is **not established** by these contended measurements.

The separate `*-off.json` and `*-half.json` files retain preliminary single-round timings. The six-configuration table above uses only `space_asbuilt_ride-metal-ao-full.json`.
