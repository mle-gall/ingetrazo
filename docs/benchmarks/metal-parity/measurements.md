# Measurements and error audit

These are one-shot, unshown **1000×700 physical-pixel** captures on the shared Mac, not presented first-frame times. Load is shared and Metal scene packing happens before GL. “GL first” is a first FBO render after context initialization; “GL warm” is the subsequent evidence capture. “Metal first export” includes fresh native renderer initialization, upload, temporary targets and readback, with Python packing measured separately. Do not compare GL warm against Metal cold as renderer throughput. Peak RSS is the **combined process** high-water mark, not one renderer's memory. Driver and swapchain allocations are excluded from Metal resident accounting.

| Model | Load s | Metal pack s | GL first s | GL warm s | Metal first export s | Peak process MiB | Metal accounted MiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| [marquee](raw/marquee.json) | 0.067 | 0.228 | 0.405 | 0.016 | 0.224 | 337.672 | 23.995 |
| [pusher_car_rust](raw/pusher_car_rust.json) | 0.494 | 2.611 | 2.156 | 0.052 | 0.368 | 1119.125 | 105.371 |
| [space_asbuilt_stairs](raw/space_asbuilt_stairs.json) | 1.469 | 1.473 | 5.205 | 0.038 | 0.807 | 1343.125 | 159.318 |
| [space_asbuilt_ride](raw/space_asbuilt_ride.json) | 11.318 | 21.971 | 50.819 | 0.397 | 12.874 | 3318.781 | 1123.405 |

## Navigation / synchronous pick probes

Eight camera-yaw increments, each followed by an offscreen frame, point pick, then hover. No capture/readback in the timed frame submission; pick itself synchronizes, and hover repeats picking. GPU timestamps may belong to earlier frames. These are distributions from eight samples, not a latency SLA. No GL input-latency comparison was made, and no ride interaction run was added beyond its two capture budget.

| Model | Frame wall median ms | Pick median / max ms | Hover median / max ms |
|---|---:|---:|---:|
| [marquee](raw/marquee-latency.json) | 1.32 | 8.10 / 21.81 | 4.78 / 18.78 |
| [pusher_car_rust](raw/pusher_car_rust-latency.json) | 1.36 | 13.99 / 23.08 | 4.66 / 9.38 |

The samples include synchronous stalls, so steady navigation responsiveness remains an acceptance item. Selection mutation cost, GPU→display latency, long-run memory growth and flicker were not measured.

## Exceptions / stderr

- Both billboard export calls reproduce G09; their GL images are retained, no Metal image exists. [Default](raw/new-document.log), [mesh-marked](raw/mesh-figure.log).
- Successful GPU runs have a first-draw GL sampler warning. Warmup eliminated the missing reference-image/section artifact; no new Metal validation errors occurred in final successful captures.
- 76 + 63 + 23 = **162 focused tests passed**, 34 aggregate deprecation warnings. [Tool/cap tests](raw/focused-tests.log), [interaction/style/scene/billboard/sheet tests](raw/interaction-tests.log), [Tape/Move updates](raw/tape-move-tests.log).
- No GUI/menu test that maps a window was run. No installed-app logs were consulted because the app was not used.
- Native build completed in release; render emitted an existing dead-code warning. Builds are retained as text logs.
