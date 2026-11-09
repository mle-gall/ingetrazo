# Phase B2 handover

Branch: `phaseB/home-worksession`, based on `895b9576`.
No push, PR, issue or remote comment was made. All implementation files and the
private `.venv-work` interpreter are in this worktree. No renderer implementation
files were changed. The history and bridge changes enforce worksession read-only
state at the command and agent boundaries.

Commits:

- `6a3aa668`: portable worksession JSON and bounded pinned recent entries.
- `a722ec81`: Home, startup routing, session tabs, active file, thumbnails and tools.
- Final test/documentation commit: focused regression coverage and schema notes.

Validation (Python 3.13, private requirements installation, offscreen Qt):

```sh
QT_QPA_PLATFORM=offscreen INGETRAZO_WGPU=0 TMPDIR="$PWD/.venv-work" \
  .venv-work/bin/python -m pytest -q \
  tests/test_home_worksession.py tests/test_project_tabs.py \
  tests/test_recent_files.py tests/test_igz_project.py tests/test_links_window.py
```

Result: **49 passed**, 22.92 seconds. `git diff --check` also passed. Test settings
use the suite's temporary INI scope, with temporary directories under the private
venv. No full-suite/batch runner or interactive review instance was started.

Persisted additions are documented in [project-file.md](project-file.md):
`worksession.files` (ordered relative paths and cameras), `worksession.active_file`,
QSettings `home/recent_files` / `home/recent_projects` (20 entries each with pins),
and optional IGZ ZIP member `thumbnail.png`.

Review limitations:

- Non-active tabs are static read-only views; activate one to navigate/edit it.
- Existing open tabs join the worksession. Unsaved document contents are not
  embedded in the project file; normal save/recovery remains responsible for them.
- Missing host documents cause project opening to fail before changing the
  current session; Home relocation handles a moved recent file/project itself.
- Thumbnail capture is conditional on a visible frame. Offscreen tests cover
  archive persistence, not the rendered appearance of the Metal capture.
- Dock recent-document integration was skipped. A live Metal/macOS visual smoke
  test remains for owner review; neither renderer implementation was modified.
