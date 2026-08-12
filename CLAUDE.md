# DicomAnon

A PyQt6 desktop app that anonymises DICOM studies and writes an ID mapping file.
Released as a Windows EXE and a macOS app bundle, both built by GitHub Actions on
a `v*` tag (`.github/workflows/build-windows.yml`, `build-macos.yml`).

## Current status / next steps

**2026-08-13: DicomAnon now verifies every file it writes and stops the run on failure**,
including the check that an anon folder only ever receives one source patient, which is
the direct test for defect 6. It lives in the app because the hospital runs a frozen
binary with no Python, and because mid-run is the only moment the source PatientID still
exists. `check-anon-output.py` is the weaker second look at the university end.

Defect 7 is fixed: `PhysiciansReadingStudy` was not a DICOM keyword, so that tag was
never blanked in any release despite the README saying it was. `--self-test` now
validates the list so CI catches a repeat.

Untested against real data. Everything so far is synthetic fixtures.

**2026-08-13: defect 6, studies from another patient can be written to a patient's
folder.** The destination folder is chosen entirely from the source folder's *name*,
and `ds.PatientID` is never read before it is overwritten. Any study sitting under a
patient folder, for whatever reason, is relabelled with that folder's pseudonym and
written there, and the same operation destroys the evidence that it was ever foreign.

This outranks defects 1 to 5 below and is numbered 6 only to keep their numbering
stable. Note that **the defect 5 assertion list does not catch it**: every assertion
there checks that identifiers were removed, none checks that a file belongs to the
patient whose folder it landed in.

Next, in this order:

1. **Run `check-anon-output.py` against the export copy on the university server.**
   Needs nobody else, and it is the first real measurement of how bad the existing
   export is. `check_identity` in `gbm-mrlinac`'s `check-patient-integrity.py` already
   does the birth year and sex part there and should keep being run.
2. **Duplicate `anon_patient_dir_name` in `dicom-anon-mapping.xlsx`**, which settles
   path B on its own and needs no DICOM reads. The file is in the researcher's home
   folder at the hospital, so this one needs them to send it.
3. **Release a build with the in-app checks and get the researcher onto it**, so no
   further contaminated output can be produced. Until then every run is unguarded.
4. **Ask the hospital programmer what their export script groups files by.** Now that
   the in-app check exists, this decides what the failure dialogs will actually mean
   when they fire, and whether a source folder can legitimately hold two patient IDs.

Still open, and not addressed by any of the above: defects 1 to 4. Defect 1 in
particular is what `verify_file(check_dates=True)` is waiting on, and the switch is
already in place for when it is fixed.

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

Adding studies to a patient already in the destination is the normal workflow for this
data, so incremental support should be made correct rather than removed. See "how to
support incremental updates safely" below; rule 1 there, an immutable
patient-to-folder assignment, would on its own have prevented the incident that
surfaced all of this.

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

### 2026-08-13: defect 7, two entries in IDENTIFYING_KEYWORDS blank nothing

Found by writing `check-anon-output.py`, on its first run, which is the point.

`anonymise_dicom` blanks a tag with `if kw in ds` (`DicomAnon.py:283-289`). That test is
False for a keyword the DICOM dictionary does not know, so the entry is dead and the tag
it was meant to cover survives untouched. Two of the 46 entries are dead:

- **`PhysiciansReadingStudy`** should be **`NameOfPhysiciansReadingStudy`**, which is
  the keyword for (0008,1060). The reading physician's name has therefore never been
  blanked, in any release, while the README lists it among the tags that are cleared.
  This is a documented guarantee the tool does not deliver, and it is PHI.
- **`PatientAccountNumber`** matches nothing in the dictionary at all. There is no such
  DICOM keyword, so it is not clear which tag was intended. Decide what it was for and
  either name that tag or drop the entry.

Both are now resolved: the first was renamed, and the second was dropped rather than
guessed, with a comment in `anon_checks.py` recording that the intent is unknown. If it
was meant to cover something real, say what and it goes back in. `--self-test` now
validates the whole list, so CI fails the build if this class of typo returns.

The general lesson is the one from defect 5. A keyword list is checked by nobody at
runtime, so a typo in it is silent and permanent. `check-anon-output.py` now validates
the list against the DICOM dictionary on every run, which is why this surfaced
immediately once something finally looked.

### 2026-08-13: the checks belong in the app, not in a script

**Correcting the entry below, which was written on a wrong assumption.** It said
`check-anon-output.py` should run at the hospital as the gate before delivery. It
cannot. The hospital runs the **frozen PyInstaller binary**: no Python interpreter, no
pydicom, no console. A console script is not something the researcher there can run at
all, whatever its dependencies. The tool ships as an EXE and an app bundle precisely so
that none of that has to exist on their machine.

So the verification goes **inside DicomAnon**, which is also where it is strongest. This
is the point made under defect 6 and not followed through: at the hospital, mid-run, the
**source PatientID is still in memory**. Checking that one source patient's files reach
exactly one anon folder, and that one anon folder receives exactly one source patient, is
a direct test for contamination. It cannot be fooled and it needs no proxy. Everything
downstream is inference from what survived anonymisation.

What went in:

- `anon_checks.py`, importing nothing but pydicom and the standard library, so the
  frozen GUI app and the plain-Python console script can share one copy of the logic.
  `IDENTIFYING_KEYWORDS` moved here from `DicomAnon.py`, so the list that gets blanked
  and the list that gets checked are the same object. It also has to live outside
  `DicomAnon.py` because the frozen app has no source file to parse, which is how the
  first version read it.
- Per-file verification in `process_folder`, between `anonymise_dicom` and `save_as`.
  A failure raises `VerificationError` and the run **stops before writing that file**.
- `RunVerifier`, fed the source PatientID for every file. It reports contamination on
  the file that first reveals it, rather than at the end of a run that has already
  scattered files across folders.
- A dialog naming the source file and the problem in words, saved to
  `dicom-anon-verification.txt` beside the mapping file. Beside it, not in the
  destination: it names source patient IDs, so it is re-identifying.
- `--self-test` now validates the keyword list, so CI fails the build on a defect 7
  typo rather than the next export discovering it.

Only the source-PatientID checks stop a run. A folder whose birth years disagree while
its source PatientID stayed constant is a source data quality problem, not
contamination, and stopping a 760k-file run for it would be wrong. Those warn at the end.

`check-anon-output.py` keeps its place, in the role the correction leaves it: the
independent check at **the university**, on what actually arrived. It is weaker by
construction, and it covers the one thing the in-app check never will, which is output
written by builds that predate the in-app check. That is most of the existing export.

#### What check-anon-output.py does

Checks: `keywords` (defect 7), `identity` (birth year and sex per folder), `labels`
(PatientID and PatientName must equal the folder name), `stale` (defect 4 leftovers,
real birth dates, raw StudyIDs, populated identifying tags), `crossfolder` (a real
PatientID or a pseudonymised UID under two folders).

**The birth year and sex check already existed** as `check_identity` in
`2-mrlinac/convert/check-patient-integrity.py` in the `gbm-mrlinac` repo, with the same
compare-the-year-not-the-date reasoning. That is the right place for it at the
university, and it should keep being run there. The two are not redundant, they sit at
different ends of the pipeline:

| | in-app checks (`anon_checks.py`) | `check-anon-output.py` | `check-patient-integrity.py` (gbm-mrlinac) |
|---|---|---|---|
| runs | hospital, during the run | university, on arrival | university, on the built dataset |
| needs | nothing, it is in the binary | pydicom and stdlib | repo config, dicom-index.json, conda env |
| sees | source PatientID, so it is definitive | only what survived anonymisation | only what survived anonymisation |
| unique | stops the run before bad output exists | the keyword list, stale files, assignment drift | pixel hashing, the only thing that catches defect 2's cross-run duplicates |

Deliberately **not** duplicated: pixel hashing. It is slow, it needs the export laid out
the way the university has it, and it already exists. If this check passes and that one
still finds duplicates, the difference is defect 2, since identifiers reset between runs
and only image content gives those copies away.

### 2026-08-13: the pipeline this tool sits in, and what it means for defect 6

Recorded because none of the analysis above accounted for it, and it moves where the
fix has to live.

The full chain has four parties and four stages:

1. A Python script written by **a programmer at the hospital** takes data off the
   scanner and arranges it into `<patientID>_<patientName>` folders. Not in this repo,
   not under our control, and not read by anyone here.
2. **A researcher at the hospital** runs that script, then runs DicomAnon over its
   output. They wrote neither tool.
3. The anon output folders are copied to the **university server**.
4. Model building happens at the university, on the anonymised data only.

Alongside this, **an oncologist at the hospital** wants to add new studies to a patient
folder that has already been anonymised, as treatment progresses. **That requirement is
why `dicom-anon-mapping.xlsx` exists**: it is the record of which anon folder a patient
was already given, so a later run can put their new studies in the same place. It was
never intended merely as a re-identification key, and the README's paragraph about new
files being saved "alongside those previously processed" is describing this workflow.

This confirms, from the requirement rather than from the data, that incremental updates
must be made correct rather than removed. It also explains the shape of the incident: the
mapping file was built to carry the folder assignment forward, but nothing ever enforced
that the assignment it recorded was honoured, which is exactly rule 1 below.

Four consequences.

**DicomAnon is the trust boundary, and it is the last place the truth exists.** Stage 1
decides which files constitute a patient, and this tool accepts that decision without
testing it. After stage 2 the source `PatientID` is gone. So contamination introduced at
stage 1 is diagnosable only at stage 1 or 2, both of which run at the hospital. The
university end is structurally incapable of diagnosing it and can only observe symptoms.
That is an argument for putting the check inside DicomAnon rather than writing a
separate audit tool at the university: DicomAnon is the only program we control that
ever sees both the source identifiers and the folder assignment.

**Path A is now the prime suspect, and it has a specific owner.** "The source folder was
already contaminated" is no longer a vague possibility, it is a question about one
identifiable script. Before building anything, ask the hospital programmer what that
script groups by, because the answer decides whether the proposed source-side check has
any power at all:

- If it groups files **by the DICOM `PatientID`**, then asserting `PatientID` is constant
  within a folder is tautological and catches nothing. Contamination would instead have
  to come from the `PatientID` being wrong at acquisition, typically the wrong patient
  selected at the scanner console, which is a real and common failure in radiotherapy.
- If it groups by **anything else**, a worklist, an accession number, a date range, a
  manual copy, then the check has real power and should be built.

Either way, also assert the **name** half of `<patientID>_<patientName>` matches
`PatientName` in the files. If the script derives the folder name from a separate list
while gathering files by another key, the name is where the disagreement shows up.

**Failures have to be actionable by the researcher.** They did not write either tool and
cannot debug Python. "Fail the run loudly" from defect 5 must therefore mean a dialog
naming the patient folder and what was wrong with it, in terms that can be forwarded to
the hospital programmer or to us without interpretation. A traceback is not a report.
The same applies to the state file from the incremental design: it lives at the
hospital, the researcher is responsible for not losing it between runs, and it must
never be copied to the university with the delivery, since it is the re-identification
key. `dicom-anon-mapping.xlsx` in the researcher's home folder already has this property
and should keep it.

**A folder legitimately spans runs and tool versions, so any check must expect that.**
Because the oncologist's updates arrive over weeks, one anon folder holds files written
by several runs and, per defect 4, by several tool versions. A check that treats every
within-folder difference as contamination will drown in defect 4's stale files: those
retain a **full** `PatientBirthDate` rather than `YYYY0101`, so comparing whole birth
date strings reports every partially-updated folder as contaminated. Compare the birth
**year**, which survives both states, and report the stale files separately as what they
are.

#### Detecting contamination from the university, today

Defect 1 is a privacy failure and, by accident, a contamination detector. Fields that
survive anonymisation are constant per patient, so a single anon folder must contain
exactly one value of each:

- `PatientBirthDate`, deliberately preserved to `YYYY0101`, so **one birth year**
- `PatientSex`, which is not in `IDENTIFYING_KEYWORDS` and is untouched
- `PatientAge`, retained in 84% of series

Two different birth years, or both `M` and `F`, under one anon folder is contamination.
This needs no hospital involvement, no source access and no cooperation from anyone, it
runs on the copy already sitting on the university server, and unlike the
`SOPInstanceUID` detector it works **across runs**, because these values come from the
source data rather than from a per-run map.

It has false negatives and no false positives: two patients of the same sex born in the
same year are invisible to it, and `PatientAge` varies legitimately within a patient
across sessions so it only helps as a coarse outlier check. Run it first anyway. It is
the cheapest thing on the list and the only one that needs nobody else.

Note the tension to resolve later: fixing defect 1 by zeroing these fields removes this
detector. Zero them at the source of truth and keep the check, do not keep the leak for
the sake of the check.

#### Constraint on the defect 3 fix

Scoping `uid_map` per patient is correct, but done naively it **destroys** the
cross-folder detector described under defect 6, which exists only because the map is
currently global. Fixing a real defect would make contamination harder to see.

So scope the map per patient for *generation*, and separately keep a global
source-UID to anon-folder index for *detection*. If a source UID is ever seen under a
second anon folder in the same run, that is contamination, and the run should fail
naming both folders. The index is cheap, it is the same data already being collected,
and it belongs in the persisted state from rule 2 so the check spans runs rather than
resetting with each one.

### 2026-08-13: defect 6, cross-patient contamination

Found by tracing how the destination folder for a file is chosen, prompted by the
concern that studies from one patient had ended up in another patient's folder. This is
a code reading, not a measurement on the export; the checks needed to measure it are
listed at the end.

#### The root cause is one missing comparison

The destination folder comes entirely from the source folder's **name**:

- `DicomAnon.py:361` parses the ID out of the folder name (`0123_SmithJohn` gives `123`)
- `DicomAnon.py:370` looks that up to get `anon_patient_folder_name`
- `DicomAnon.py:374` globs **every** `.dcm` under that folder, recursively, unfiltered
- `DicomAnon.py:274-275` overwrites `PatientName` and `PatientID` with the pseudonym

Nothing in the file reads `ds.PatientID` before that overwrite. The tool takes whatever
it finds under a folder and asserts, by writing it, that it belongs to that patient.

This is worse than a missing check, because the operation that mislabels the study is
the same one that destroys the evidence. The original `PatientID`, `PatientName`,
`AccessionNumber` and every UID are gone by the time the file is written, so nothing in
the output distinguishes a contaminating study from a legitimate one. Contaminated
input produces output whose contamination is undetectable from the output alone.

#### Four ways a foreign study lands in a patient's folder

**A. The source folder was already contaminated.** A prior-comparison study pulled
alongside the index study, a manual file copy, a PACS export keyed on accession rather
than patient. The tool launders it silently. Given the source is a hospital system this
is the most likely path, and the only one where the tool behaves as written.

**B. Two hospital IDs assigned the same anonymised ID in the lookup file.**
`_load_lookup` (`DicomAnon.py:309`) is `dict(zip(...))` with no uniqueness check on
either column, so `5678` and `9012` both mapping to `002` sends both patients into
`destination/002/` under the same pseudonymised `PatientID`. The same call means a
hospital ID listed twice silently keeps the **last** row, so `1234->001` followed by
`1234->007` collapses to `007`. That is defect 4's assignment drift, reachable by an
Excel copy-paste.

**C. Leading zeros collapse distinct source folders.** `_parse_patient_id` returns
`int(patient_str)` (`DicomAnon.py:325`), so `0123_SmithJohn`, `123_JonesMary` and
`00123_BrownAnn` all produce lookup key `'123'`. Three people, one destination folder.
Whether this fired depends on whether the export ever zero-pads, but the code cannot
tell those folders apart.

**D. Silent overwrite once B or C has collided two patients.** `ds.save_as`
(`DicomAnon.py:397`) does not check for an existing file. Relative paths are taken from
each patient's own folder root, so two patients using the same date-based session layout
overwrite each other. Contamination plus data loss. This is why rule 3 under
"how to support incremental updates safely" says a collision must either overwrite the
identical file or fail, never be disambiguated with a counter.

#### Detecting contamination in the existing export

Defect 3 leaves a useful accident behind. `uid_map` and `study_label_map` are shared
across all patients in a run, and `_get_study_label` (`DicomAnon.py:278`) runs *before*
`_anonymise_uids_recursive` (`DicomAnon.py:292`), so it keys on the original
`StudyInstanceUID`. Therefore **within a single run**, one source study written into two
patient folders receives byte-identical pseudonymised `SOPInstanceUID`s in both.

In increasing order of cost:

1. **The mapping spreadsheet detects path B by itself.** `dicom-anon-mapping.xlsx` has
   one row per `patient_id` carrying its `anon_patient_dir_name`. Any anon folder name
   appearing against two different `patient_id` values is a confirmed collision. No
   DICOM reads required.
2. **Scan for any `SOPInstanceUID` present under more than one anon patient folder.**
   UIDs are generated, so a duplicate is proof rather than coincidence. Two limits: it
   goes blind across runs because `uid_map` resets (defect 2), and it only fires when
   the contaminating study also exists in its true owner's folder from the same run.
3. **Go back to the source.** For each `<id>_<name>` folder, check `PatientID` is
   constant across every file and matches the folder name. This is the only check that
   separates path A from B and C definitively, and it is what the tool should have been
   doing all along.

Anything the first three miss needs the pixel hashing that
`2-mrlinac/convert/check-patient-integrity.py` in `gbm-mrlinac` already does, which is
what found the defect 2 duplicates.

#### What this changes

The five per-file assertions under defect 5 all verify that identifiers were *removed*.
None verifies that a file belongs to the patient whose folder it went into, so that
plan as written would still miss this entirely. Add:

- Before anonymising a patient folder, assert every file under it carries the same
  `PatientID` and that it matches the folder name. Fail the run and name the offending
  files rather than skipping them, since a mismatch means the source is wrong and no
  output from that folder can be trusted.
- Assert the lookup file is a bijection: no duplicate hospital IDs, no duplicate anon
  IDs. Reject the file before any processing starts.
- Key patients on the folder's ID **string**, not `int()`, so zero-padded IDs stay
  distinct.

Two smaller things noticed in the same reading:

- A parse failure at `DicomAnon.py:364` does `break`, abandoning every remaining patient
  while still saving the mapping for those already processed. A run can end up quietly
  partial. It should skip the folder and report it, the way an unknown patient ID does.
- `anon_patient_dir` is listed at `DicomAnon.py:407` without checking it exists. It is
  only ever created inside the per-file loop (`DicomAnon.py:395-396`), so a patient
  folder holding no `.dcm` files raises `FileNotFoundError` out of `process_folder`,
  which `anon_button_clicked` does not catch, and the mapping file is never written for
  that run. It survives today only because the destination usually already has the
  folder from an earlier run.

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

### 2026-08-12: how to support incremental updates safely

Adding new studies to a patient already in the destination is the **normal** case, not
an edge case: MR-Linac patients accrue around twenty sessions over several weeks, so
"re-run everything from scratch" is fine as a one-off remediation and unsustainable as a
workflow. The defects above are not an argument for removing incremental support, they
are an argument for making it correct. Five rules do that.

#### 1. The patient-to-folder assignment is immutable

Once a hospital ID has been assigned an anon folder, that mapping is **permanent**. The
input lookup may only ADD patients; if it disagrees with a previously recorded
assignment, **fail the run and report it** rather than honouring the new value.

This single rule would have prevented the entire incident. Everything else that went
wrong needed the assignment to drift first.

#### 2. State is persisted, and the run refuses to start without it

Per patient, keep at minimum:

- `uid_map`: source UID to pseudonym, so a later study that references an earlier one
  still resolves. Structure sets reference series UIDs and registrations match frame of
  reference UIDs, so a fresh map silently severs those links.
- `study_label_map`, so `STUDY_nnnn` numbering continues rather than restarting.
- the assignment from rule 1.
- the tool version last used for that patient.

Scope `uid_map` **per patient**, which also fixes the cross-patient pseudonym sharing
noted above. Two patients must never share a pseudonymised UID.

Take the state path as an explicit argument and **exit non-zero if it is missing**. A run
that silently starts with an empty map is the failure mode that produced duplicates
nothing could detect.

**The state file is the re-identification key**: it holds hospital IDs and original
UIDs. Keep it OUTSIDE the destination that gets transferred, and never inside a folder
anyone might copy to a collaborator. Do not put it in the operator's home folder either
if that risks it drifting out of sync with a destination; tie it to the destination
explicitly.

#### 3. Writing a file is idempotent

Output paths already mirror the source relative path, so re-processing the same source
file overwrites rather than duplicating. Keep that property. Never disambiguate a
collision by appending a counter: a collision means either the same file arriving twice,
which should overwrite, or two different patients colliding, which should fail.

#### 4. A version change forces reprocessing, and is never silently mixed

Compare the recorded tool version for a patient against the current one. If it is older,
either reprocess that patient's entire folder from source, or refuse and list the stale
patients. Never write new files at the current version alongside old files at an earlier
one: that is exactly how a third of the export kept its 2025-era state.

If the source is no longer available for a stale patient, that folder cannot be brought
up to date. Mark it permanently stale in the state file so it is visible rather than
assumed current.

#### 5. Verify after every run

The per-file assertions listed above, plus two that only matter for incremental use:

- no two anon folders contain data from the same source patient;
- every file present in the destination is recorded in the state file. An unrecorded
  file is orphaned output from a previous configuration, which is precisely what the
  duplicated copies were.

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
