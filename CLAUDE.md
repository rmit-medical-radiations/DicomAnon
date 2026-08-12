# DicomAnon

A PyQt6 desktop app that anonymises DICOM studies and writes an ID mapping file.
Released as a Windows EXE and a macOS app bundle, both built by GitHub Actions on
a `v*` tag (`.github/workflows/build-windows.yml`, `build-macos.yml`).

## Current status / next steps

**2026-08-12: five defects found by analysing a real export.** See the decision log
below. In severity order:

1. Anonymisation does not meet the README's own re-identification bar: every time
   field and every date field except `StudyDate` survives untouched, and the
   `StudyDate` shift can be undone from the data itself.
2. `uid_map` is not persisted between runs, so re-processing the same source data
   produces different pseudonyms and an undetectable duplicate.
3. `uid_map` is shared across patients within a run, so a UID common to several
   source patients becomes one pseudonym linking their output folders.
4. Accumulating into an existing destination is unsafe once an assignment or the
   tool version changes, and nothing detects either.
5. Nothing verifies the output, which is why 1 went unnoticed for months.

Fix 5 first: it is cheap, and it would have caught 1 on the first file.

**2026-08-05: v0.7 released.** Fixes the CI blind spot that let broken Windows
builds ship.

The broken `DicomAnon.exe` assets were deleted from the v0.4 and v0.5 releases,
so neither release has any assets now. The tags are untouched and both are still
rebuildable from source. v0.4 had been downloaded twice, so tell anyone still on
it to move to v0.7. Both release pages now carry a withdrawal warning pointing at
`/releases/latest`, so they stay correct as new versions ship.

v0.3 and earlier still carry hand-uploaded assets. They predate the GitHub
Actions builds and have not been checked against this bug.

## Decision log

### 2026-08-12: anonymisation gaps found by analysing a real export

Found while investigating a research dataset (33 patient folders, 16535 series,
761631 files) produced by this tool at a clinical institute. Evidence was gathered
with `2-mrlinac/convert/check-patient-integrity.py` in the `gbm-mrlinac` repo, which
is the outside-in version of the verification this tool lacks. Numbers below are
measured on that export, not hypothetical.

#### 1. The stated re-identification bar is not met

The README's rationale for remapping UIDs is that the data should not be
re-identifiable "even if the anonymised DICOMs are loaded back into the system at
their originating institution". `anonymise_dicom` modifies exactly two things that
bear on this: `PatientBirthDate` and `StudyDate`. Everything else date-like or
time-like survives. Over 4484 series that this tool anonymised correctly
(pseudonymised `StudyID`, zeroed birth date, identifier tags blanked):

| retained in the output | share |
|---|---|
| `StudyTime` | 100% |
| `SeriesTime` | 90% |
| `PatientAge` | 84% |
| `ContentTime` | 66% |
| `AcquisitionDate`, real and unshifted | 40% |
| `AcquisitionTime` | 37% |
| `SeriesDescription` containing a full timestamp, e.g. `20210819134732-1ABrain` | 2% |

Two consequences against that threat model:

- **The shift is self-defeating.** `StudyDate` is shifted and `SeriesDate` is not, so
  anyone holding the data can difference the two, recover the offset, and undo the
  shift everywhere. The output carries its own key.
- **`AcquisitionDate` with `AcquisitionTime` is a direct lookup** into the
  institution's own records and needs nothing else.

The UID handling itself is sound: `_anonymise_uids_recursive` walks by VR through
nested sequences and correctly skips `SOPClassUID`. The date handling should follow
the same pattern. **Prefer a `_shift_dates` that walks every `DA`/`TM`/`DT` element
over a keyword list**, for the same reason the UID function walks by VR: a list
silently misses whatever nobody thought of.

Also decide explicitly about `PatientAge`, which is not in `IDENTIFYING_KEYWORDS`,
and about `StudyDescription`, which `anonymise_dicom` preserves on purpose.

#### 2. UID pseudonyms are not stable between runs

`uid_map` and `study_label_map` are created inside `process_folder`, so every
invocation starts empty. The same source UID therefore receives a different pseudonym
in a later run and `STUDY_nnnn` numbering restarts.

In the export this produced series with **byte-identical pixel data and completely
disjoint UIDs**, which no integrity check based on identifiers can detect. It was only
found by hashing pixel data.

Either persist `uid_map` alongside the ID mapping file and reload it, or make single
full runs the only supported mode and enforce it.

#### 3. `uid_map` is shared across patients within a run

`uid_map` is created once per `process_folder` call and passed to every patient, so a
UID that several source patients share, typically a vendor constant, maps to a single
pseudonym that then links their output folders. In the export,
`1.2.826.0.1.3680043.8.498.1229313067498998618823` is a generated
`FrameOfReferenceUID` shared by **16 patient folders**.

That is a false linkage between patients, and it breaks downstream tools that match
frames by UID, which is how DICOM registration objects are resolved.

**Scope `uid_map` per patient.** Two patients must never share a pseudonymised UID.

#### 4. Accumulating into an existing destination is unsafe

The README documents this deliberately:

> "adding new patient folders (and updates to existing patient folders) will not erase
> previous DICOM files for the same patient; the new anonymised DICOM files will be
> saved in the same structure alongside those previously processed."

That is reasonable for appending genuinely new patients. It becomes unsafe as soon as
either the ID lookup or the tool version changes, and nothing detects either:

- If the lookup assigns a patient a different anon folder than last time, the patient
  is written to the new folder and the old copy simply stays. Two folders, two
  identities, no collision, no warning. Combined with defect 2 the two copies share no
  identifiers, so nothing links them.
- Output written by an older build is never reprocessed. In the export, **5507 of
  16535 series (33%)** retained a 2025-era state: raw hospital `StudyID`, unshifted
  `StudyDate`, full birth dates, original UIDs and populated identifier tags,
  including a patient given name with a hospital MRN in 331 series.

At minimum, detect that a patient already exists under a different anon folder and
refuse or replace. Better, support writing a delivery to a fresh empty destination in
one run, and document that as the supported path.

#### 5. Nothing verifies the output

Defect 1 shipped for months and defect 4's consequences were invisible, for the same
reason the v0.4/v0.5 Qt breakage shipped: **nothing checks the result.** `--self-test`
asserts only that the GUI starts.

After writing each file, assert:

- no `PatientBirthDate` retains a month or day;
- no keyword in `IDENTIFYING_KEYWORDS` is populated;
- `StudyID` matches `STUDY_\d+`;
- no output UID equals any input UID;
- no `DA`, `TM` or `DT` element equals its input value.

Fail the run loudly. That last assertion alone would have caught defect 1 on the first
file processed.

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
