# DicomAnon

A PyQt6 desktop app that anonymises DICOM studies and writes an ID mapping file.
Released as a Windows EXE and a macOS app bundle, both built by GitHub Actions on
a `v*` tag (`.github/workflows/build-windows.yml`, `build-macos.yml`).

## Current status / next steps (as of 2026-09-01)

**All nine defects found in the 2026-08 analysis are addressed.** The notes record
v0.12 as the current build, shipping the mapping-file swap retry with its recovery
path tested. The remaining work is deployment and the rebuild, not analysis.

- **The old export could not be repaired in place and had to be rebuilt from source**
  (18 of 33 folders held data from two different people). Related repos record a clean
  export landing on krypton on 2026-08-27 that passes audit, with 0 of 33 folders
  mixing patients, which is consistent with the rebuild having been completed
  successfully. Confirm that before assuming it; nothing in this repo records it.
- **OPEN — the release tags do not match the notes.** `origin` carries no tag beyond
  **v0.9**, while the decision log describes v0.10, v0.11 (cut from `0ba762f`) and
  v0.12. Since the build workflows fire on a `v*` tag, work out how those releases were
  published before cutting another one.
- **OPEN, cross-repo — the SRO delivery cannot be re-linked, only re-anonymised.** A
  separate DicomAnon run was made for an SRO export with its own destination, so it got
  its own `uid_map` and none of its UIDs match the image delivery (0 of 280 frame-of-
  reference UIDs). The fix is to re-run with the destination set to the image
  delivery's output folder, so `state_dir_for()` resolves the same `uid_map`. That
  needs the machine holding **both** `~/.dicom-anon-state/<sha1(destination)>/` for
  that delivery **and** `~/dicom-anon-mapping.xlsx`; per the low-ADC notes, neither is
  on the Mac or the Spark. Do not attempt a geometric re-link.
- **OPEN, and it costs a rebuild — `TOOL_VERSION` moved 0.8 to 0.9 on 2026-09-01.** A
  bare date (one with no time beside it) was shifted a day out of step with the rest of
  its own file whenever the offset wrapped past midnight, so the bytes changed and the
  version had to move with them. **Every patient's folder must be produced again**
  (~4.6 h for 33), and a run finding 0.8 in a destination will stop and list rather than
  mix. Weigh that against the artefact: one day on secondary date elements such as
  `AcquisitionDate` and `ContentDate`, never on the `StudyDate`/`StudyTime` timeline,
  which is 100% paired. See the decision log before scheduling it.
- **Still to ask the hospital**: what their export script groups files by. It decides
  what the new failure dialogs mean when they fire.
- **Noted and not done**: per-file orphan detection (a file deleted from the source
  stays in the destination unnoticed), and the two loop bugs from the defect 6 entry
  (the `break` at a parse failure, and the unguarded `os.listdir` on an empty patient
  folder).
- **Rebuild budget**: about **4.6 hours** for 33 patients, measured on the largest
  (45,359 files, 25 GB, 17 minutes, zero verification failures). Peak memory was
  **4.4 GB for one patient**; watch it across a full run and split into separate runs
  if it grows, since an interrupted rebuild now resumes cheaply.

## The invariants

These are what the defects cost. Do not weaken one without reading its decision-log
entry first.

- **Rule 1: a patient's folder assignment is permanent.** A lookup file that moves a
  patient or reassigns their folder stops the run. This alone would have prevented the
  incident that surfaced everything else.
- **Per-patient state lives under `~/.dicom-anon-state/<destination key>/`** and
  persists `uid_map` and `study_label_map`, so pseudonyms are stable between runs and
  **scoped to one patient**. Both halves matter: unpersisted gives a different
  pseudonym each run and an undetectable duplicate; shared across patients lets one
  common UID link their output folders.
- **`TOOL_VERSION` is recorded per patient**, and a run stops rather than mixing
  versions in one folder or writing into a destination it has no record of.
- **Dates are shifted by a random per-patient offset held in the ID mapping file**, not
  the old hard-coded 30 days that anyone could read off GitHub. Every `DA`/`TM`/`DT`
  element is shifted. **Intervals between a patient's studies are preserved exactly,
  including across runs**, which is what the downstream longitudinal work needs.
  `PatientAge` is kept and the birth year is the shifted one, since keeping both the
  real year and the age would give the offset away.
- **"Preserved exactly" means the instant, not the date.** The offset carries a time of
  day, so a gap measured from `StudyDate` ALONE can differ by a day from the source
  (13.9% of consecutive gaps, 37.4% of patients). Differencing date **with** time
  recovers the true interval. Tell anyone doing longitudinal analysis this.
- **A date with no time beside it takes the file's carry, decided once per file** from
  `StudyTime`. Without that, dates identical in the source came out a day apart from
  each other, because a paired `DA`/`TM` carries past midnight and a bare `DA` cannot.
- **The mapping file opens on a DO NOT EDIT sheet, keeps a `.bak`, and holds the date
  offsets.** Losing it loses the ability to add to the delivery consistently.
- **The app verifies every file it writes and stops the run on failure**, including the
  check that an anon folder only ever receives one source patient. It lives in the app,
  not a script, because the hospital runs a frozen binary with no Python, and because
  mid-run is the only moment the source `PatientID` still exists.
  `check-anon-output.py` is the weaker second look at the university end.
- **Re-runs with nothing changed are instant.** Every run used to rewrite the whole
  destination, about nine hours for the real export.

## Traps: things that have already gone wrong

Evidence in `docs/decision-log.md`.

- **A name in `IDENTIFYING_KEYWORDS` that is not a real DICOM keyword blanks nothing,
  silently.** `PhysiciansReadingStudy` was never blanked in any release despite the
  README saying it was. `--self-test` now validates the list so CI catches a repeat.
- **Verification that reuses the blanking code's own assumption is blind by
  construction.** Identifying tags nested in sequences were never blanked, and the
  check missed it because it used the same top-level test.
- **Removal assertions do not catch misattribution.** Every assertion in the defect 5
  list checks that identifiers were removed; none checks that a file belongs to the
  patient whose folder it landed in. That is a separate check and it needs the source
  `PatientID`, before it is overwritten.
- **A destination folder chosen from the source folder's *name*** relabels any foreign
  study sitting under it, and the same operation destroys the evidence that it was ever
  foreign. Read `ds.PatientID` first.
- **A single malformed file must not halt a run.** A file with no `StudyInstanceUID`
  would have stopped the lot.
- **A fixture that holds one value constant cannot test a property that depends on it.**
  Every date test gave every session the same time of day, so sessions carried past
  midnight together and stayed in step whatever the code did. That hid a real defect for
  months. Vary the thing the property depends on.
- **A retry that succeeds destroys the evidence.** v0.11 deliberately shipped without
  the `os.replace` retry because the cause was still unproven. If you ship a retry, keep
  the diagnostic: bind the `OSError` *and use it*, since WinError 32 (sharing violation)
  and 5 (access denied) point at different causes.
- **Trial on real data before committing to a rebuild.** Defects 8 and 9 are what first
  contact with messy real DICOM looks like, and the full-scale trial is what turned the
  nine-hour rewrite into an instant re-run.

## Build and environment gotchas

- CI builds on Python 3.11. `DicomAnon.py` uses `dict | None` annotations
  evaluated at class-definition time, so it needs Python 3.10+. The system
  Python on macOS is 3.9 and will fail with a `TypeError` on import.
- `pandas` is pinned to 2.2.2, which has no wheels for Python 3.13.

## Decision log

The dated decisions, defect analyses and trial results behind everything above live in
**`docs/decision-log.md`**, along with the status history as it was written at the time.
Read it when changing the thing it describes; the invariants and traps are already
summarised here.

Add new entries to the log, and add the one-line consequence here.
