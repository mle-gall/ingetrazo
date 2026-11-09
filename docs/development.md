# Development guide

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Requires Python 3.12+.

## Running tests

```bash
python -m pytest -m "not slow"     # the fast suite (~3,100 tests, ~5 min; what CI runs)
python -m pytest                   # everything (~3,900), including the slow fuzz sweeps
```

Every pull request runs the fast suite. A fix or a feature comes with its
test — ideally one that fails without the change. A test that paints
needs a real OpenGL context: guard it with a skip when there is none, or the
CI runner (no GPU) fails it.

## Style

- PEP 8, 100-character soft limit.
- All code, comments and commit messages in English.
- UI strings localized via `i18n/`. Never hardcode user-facing text.

## Submitting changes

See [../CONTRIBUTING.md](../CONTRIBUTING.md).

### Viewport renderer preference

Preferences → General → Viewport renderer applies to newly opened documents.
Existing Metal choices are preserved; profiles without a choice use
`DEFAULT_RENDERER = 'opengl'` in `core/renderer_settings.py`.
`INGETRAZO_WGPU=0/1` overrides the choice for one process without changing
saved preferences, but cannot bypass capability checks. Before window creation,
a bounded subprocess imports the render crate and creates a tiny hidden Qt
native widget to request the actual Metal device and required features. Its
result is cached for the session; Preferences shows the reason and Python/Qt
versions, and the status bar identifies the effective renderer. Missing crates,
unsupported devices and failed probes use OpenGL. A normal Metal start that
never presents a frame recovers to OpenGL on the next launch with a notice;
environment-selected runs leave the persistent start guard untouched.

macOS builds use `scripts/build_native.sh` (or the release workflow) to build
both crates before PyInstaller. The render wheel requires
`--features extension-module` and `CARGO_PROFILE_RELEASE_STRIP=none`
(rust-lang/rust#157750); the spec requires and bundles it on macOS.
wgpu supports Vulkan on Linux and DX12 on Windows, but this application's
native view is validated only on Metal. The probe reports “not validated” on
those platforms and keeps OpenGL, including when Metal is explicitly requested.
