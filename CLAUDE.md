# DicomAnon

A PyQt6 desktop app that anonymises DICOM studies and writes an ID mapping file.
Released as a Windows EXE and a macOS app bundle, both built by GitHub Actions on
a `v*` tag (`.github/workflows/build-windows.yml`, `build-macos.yml`).

## Current status / next steps

**2026-08-05: v0.7 released.** Fixes the CI blind spot that let broken Windows
builds ship. Nothing outstanding.

The broken `DicomAnon.exe` assets were deleted from the v0.4 and v0.5 releases,
so neither release has any assets now. The tags are untouched and both are still
rebuildable from source. v0.4 had been downloaded twice, so tell anyone still on
it to move to v0.7. Both release pages now carry a withdrawal warning pointing at
`/releases/latest`, so they stay correct as new versions ship.

v0.3 and earlier still carry hand-uploaded assets. They predate the GitHub
Actions builds and have not been checked against this bug.

## Decision log

### 2026-08-05: releases v0.4 and v0.5 shipped a broken Windows EXE

A user on v0.4 hit `DLL load failed while importing QtCore: The specified
procedure could not be found` at startup. Root cause was the Qt/bindings
mismatch already fixed for macOS in 74fe599: `PyQt6` 6.6.1 only loosely
constrains `PyQt6-Qt6`, which ships the Qt libraries themselves, so an unpinned
install paired Qt 6.11.1 with 6.6.1 bindings. macOS reports this as
`Symbol not found: __Z13lcPermissionsv`; Windows reports it as a missing DLL
export. Both are the same bug. `PyQt6-Qt6` is pinned in `requirements.txt` as of
v0.6, and it must stay matched to the `PyQt6` version.

The broken EXEs shipped because the Windows smoke test could not detect this
class of failure. The EXE is built windowed (`console=False`), so an import-time
crash raises PyInstaller's modal "Unhandled exception in script" dialog and the
process stays alive waiting for a click. The test only checked that the process
had not exited after 5 seconds, so it passed on a completely broken build. The
macOS job caught the same mismatch correctly, because a crash there just exits.

**Do not "fix" this by setting `disable_windowed_traceback=True` in the spec.**
That dialog is how this bug got reported in the first place, and it is the only
diagnostic an end user can send us.

Instead, `DicomAnon.py` gained a `--self-test` mode that verifies the Qt and
PyQt6 versions match and constructs the main window offscreen, exiting non-zero
on failure. CI runs it against the installed packages before building and
against the packaged binary after, and treats "still running after 60s" as a
failure, since a hang means the exception dialog is up. The GUI is still launched
separately afterwards, because the offscreen self-test never loads the Windows
platform plugin (`qwindows.dll`) and would miss a fault there.

## Gotchas

- CI builds on Python 3.11. `DicomAnon.py` uses `dict | None` annotations
  evaluated at class-definition time, so it needs Python 3.10+. The system
  Python on macOS is 3.9 and will fail with a `TypeError` on import.
- `pandas` is pinned to 2.2.2, which has no wheels for Python 3.13.
