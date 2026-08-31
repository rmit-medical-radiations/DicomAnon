# DicomAnon: decision log

Dated decisions, defect analyses and trial results, newest first. This is the
**evidence**: what was found, how it was diagnosed, and why the code and the release
history look the way they do.

The **invariants and the traps** that follow from all of this are in `CLAUDE.md`,
which is the file to read first. Everything here is background, needed when you are
changing the thing it describes or re-checking a decision.

Split out of `CLAUDE.md` on 2026-09-01 (it had reached 1270 lines, ~16k tokens, ~88%
of it log). Sections are verbatim as written on their dates. Add new entries here,
and add the one-line consequence to `CLAUDE.md`.

## Contents

- 2026-09-01: a bare date and a paired date parted company at midnight
- 2026-08-14: v0.11 shipped without the retry on purpose, and what v0.12 had to prove
- 2026-08-13: the v0.10 crash, diagnosed from the file it left behind
- 2026-08-13: v0.10 crashed at the hospital, before the cause was known
- 2026-08-13: several source folders per patient is normal, not a collision
- 2026-08-13: pydicom moved to 3.0.2, and TOOL_VERSION deliberately not bumped
- 2026-08-13: full-size trial, and the numbers to plan the rebuild with
- 2026-08-13: RT trial, the case the persisted UID map exists for
- 2026-08-13: v0.8 trialled on real DICOM, and the rewrite problem it exposed
- 2026-08-13: the export measured, and what it actually shows
- 2026-08-13: defects 8 and 9, found by simulating messy data
- 2026-08-13: defects 2, 3 and 4, and the state store they all needed
- 2026-08-13: defect 1 fixed, and the offset became the thing that matters
- 2026-08-13: QC on the ID lookup file, and rule 1 enforced at last
- 2026-08-13: defect 7, two entries in IDENTIFYING_KEYWORDS blank nothing
- 2026-08-13: the checks belong in the app, not in a script
- 2026-08-13: the pipeline this tool sits in, and what it means for defect 6
- 2026-08-13: defect 6, cross-patient contamination
- 2026-08-12: anonymisation gaps found by analysing a real export
- 2026-08-12: how to support incremental updates safely
- 2026-08-05: releases v0.4 and v0.5 shipped a broken Windows EXE

---

## Status history (2026-08-05 to 2026-08-14)

The `Current status / next steps` section as it read before the split: a running
summary written newest-first as each defect was found and fixed. Superseded by the
status section in `CLAUDE.md`, kept as the dated record.

**2026-08-14: v0.12 released, with the mapping swap retry and the recovery path tested.**
v0.11 went to the oncologist deliberately without the retry, because a retry that
succeeds destroys the evidence and the cause was still unproven. v0.12 ships it now that
the recovery around it is covered. See the decision log.

**2026-08-13: defect 1 fixed and the date check turned on.** Every `DA`/`TM`/`DT`
element is shifted, by a random per-patient offset stored in the ID mapping file rather
than the hard-coded 30 days that anyone could read off GitHub. Intervals between a
patient's studies are preserved exactly, including across runs, which is what the
oncologist's workflow needs. `PatientAge` is kept and the birth year is now the shifted
one, since keeping both the real year and the age would have given the offset away.

**2026-08-13: the ID lookup file is checked before anything is written**, and rule 1 is
enforced: a patient's folder assignment is permanent, and a lookup file that moves a
patient or reassigns their folder stops the run. The mapping file now opens on a
DO NOT EDIT sheet, keeps a `.bak`, and holds the date offsets.

**2026-08-13: defects 2, 3 and 4 fixed.** Per-patient state under
`~/.dicom-anon-state/<destination key>/` persists `uid_map` and `study_label_map`, so
pseudonyms are stable between runs and scoped to one patient. `TOOL_VERSION` is recorded
per patient, and a run stops rather than mixing versions in one folder or writing into a
destination it has no record of.

**2026-08-13: the export has been measured, and 18 of its 33 folders hold data from two
different people.** Confirmed assignment drift, exactly as defect 4 predicted. See the
decision log. **The export cannot be repaired in place and must be rebuilt from source.**

**2026-08-13: defects 8 and 9 fixed**, both found by simulating messy real DICOM. A file
with no `StudyInstanceUID` would have halted an entire run, and identifying tags nested
in sequences were never blanked, with the verification blind to it because it used the
same top-level test as the blanking.

**All nine defects are now addressed.** The remaining work is deployment and the rebuild,
not analysis. Two things to keep in view:

- **The existing export has to be rebuilt**, both because of the contamination above and
  because the tool now refuses to add to a destination it has no state for.
- **v0.8 has now been trialled on real DICOM** (one patient, 1293 files, real Philips MR)
  and the output verified against the source. It found one blocker, since fixed: every
  run rewrote the entire destination, about nine hours for the real export. Re-runs with
  nothing changed are now instant. See the decision log.

**2026-08-13: trialled on a real RT patient too** (CT, MR, RTSTRUCT, RTPLAN, RTDOSE, REG),
with the structure sets deliberately written by a later run than the images they contour.
No reference was broken that was not already broken in the source. Noted along the way:
2928 of 3603 references in the source's registration objects already dangle, which is a
question for the hospital about what the export omits.

**2026-08-13: trialled at full scale** on the export's largest patient (45359 files,
25 GB): 17 minutes, zero verification failures, and the contamination warning fired on a
genuinely contaminated folder. **Budget about 4.6 hours for a full rebuild.** Peak memory
was 4.4 GB for one patient and should be watched across a 33-patient run; if it grows,
process patients in separate runs, since an interrupted rebuild now resumes cheaply.

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

1. **Stop using the current export for anything patient-level.** 18 of 33 folders mix two
   people, so per-patient metrics and anything longitudinal are invalid for them, and
   which 18 is known but which patient is in which folder is not.
2. **Get the ID mapping spreadsheet from the hospital.** It records the folder each
   patient was assigned and is the cheapest way to confirm the drift and recover the
   correct attribution. Duplicate `anon_patient_dir_name` values settle it outright.
3. **Run the pixel hashing** in `gbm-mrlinac`'s `check-patient-integrity.py --check
   duplicates`. It is the only thing that can attribute series to patients now that the
   identifiers are gone, and it also measures defect 2's cross-run duplicates.
4. **Release v0.8, then trial it on one patient** into an empty destination before
   committing to a full rebuild. Defects 8 and 9 are what a first contact with real data
   looks like, and there will be more.
5. **Rebuild the delivery from source.** Confirm first that the hospital still holds
   source for all 33 patients; any patient whose source is gone cannot be brought up to
   the current version at all.
6. **Ask the hospital programmer what their export script groups files by**, which
   decides what the new failure dialogs will mean when they fire.

Smaller things noted and not done: per-file orphan detection (a file deleted from the
source stays in the destination unnoticed), and the two loop bugs from the defect 6
entry, the `break` at a parse failure and the unguarded `os.listdir` on an empty
patient folder.

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

### 2026-09-01: a bare date and a paired date parted company at midnight

Found by checking the claim the invariants make, rather than by a failure: are the gaps
between a patient's studies actually preserved? Measured end to end through
`process_folder`, comparing source against output for **every** `DA`/`TM`/`DT` element at
one second resolution, sequences and the timestamp embedded in `SeriesDescription`
included, over two patients, four irregularly spaced sessions and two runs. Every element
shifted by one constant per patient, every interval survived, the two patients got
different offsets, and the session added in run 2 kept its true spacing. The claim holds.

**But the measurement was too easy, and the reason is worth recording.** Every existing
date test gives every session the SAME time of day (`test_dates.py` defaults
`study_time='134732'` for both studies in its interval check). Two sessions sharing a time
of day carry past midnight together, so their dates stay in step no matter what the code
does. The tests were structurally blind to a whole class of fault, the same way
`verify_file` was blind to defect 9 by reusing the blanking code's own top-level test.
Vary the thing the property depends on, or the test only proves the fixture is consistent
with itself.

**The defect, once the times were varied.** `shift_dates` pairs a `DA` with its `TM` and
shifts them as one instant, which is right and is what keeps a file agreeing with itself
across the wrap. A `DA` with **no** `TM` beside it has no instant to carry it, and was
shifted by whole days alone. So the two kinds parted company whenever the time offset
wrapped:

```
source  StudyDate = SeriesDate = AcquisitionDate = ContentDate = 20210815
        StudyTime = SeriesTime = 233000, no AcquisitionTime, no ContentTime
output  StudyDate       20210508 003000
        SeriesDate      20210508 003000
        AcquisitionDate 20210507      <- one day out
        ContentDate     20210507      <- one day out
```

Four dates identical in the source, written out as two pairs a day apart. Worse across
sessions, where there is no time to reconstruct the truth from: a date paired with its
time in one session and bare in the next lost a day from the interval between them, an
`AcquisitionDate` gap of 13 days where the source said 14.

**Not hypothetical for this data.** The export analysis measured `AcquisitionDate` on 40%
of series but `AcquisitionTime` on only 37%, and `ContentTime` on 66%, so a patient having
one session with the time and one without is ordinary. `StudyDate`/`StudyTime` are 100%
paired, which is why the primary study timeline was never affected and why this went
unnoticed.

**The fix: the carry is decided once per file.** `_reference_carry` reads one reference
time and returns how many days the file's bare dates move on top of `offset_days`.
`StudyTime` first, because it anchors the study timeline and was on every series in the
export; failing that the first other `TM` in tag order, then the time inside a `DT`; and 0
for a file with no time at all, which is the old behaviour and the only defensible answer
when there is nothing to reason from. Computed at the top level and passed down through
the recursion, because a sequence item holding a bare date and no time of its own has
nothing to compute it from. Paired elements are untouched: they still shift as exact
instants, so this only adds information where there was none.

**What is deliberately NOT fixed, and must not be mistaken for this bug returning.** Two
studies whose times of day fall either side of the wrap still get different carries, so a
gap measured from **dates alone** can differ by a day from the source. The instant is
exact in both, and differencing date with time recovers the true interval. Simulated over
20000 patients of ~20 sessions with times sampled from clinic hours, 13.9% of consecutive
gaps differ by a day at date granularity and 37.4% of patients have at least one. This is
inherent to shifting by a non-integer number of days: the alternatives are giving up the
time shift, or giving up a file agreeing with itself, and both are worse. **Tell anyone
doing longitudinal analysis to difference the instant, not the date.**
`tests/test_intervals.py` asserts the artefact explicitly so it is pinned rather than
rediscovered.

**`TOOL_VERSION` bumped 0.8 to 0.9, and this one is expensive.** The rule is to bump when
the bytes change, and they do: any file with a bare date, written when the offset wrapped,
differs by a day from what this build would now write. Unlike the pydicom move, which was
measured byte-identical and deliberately left at 0.8, there is no case for leaving it. The
consequence is that **every patient's folder has to be produced again**, about 4.6 hours
for 33 patients, and a run that finds an older version in a destination will stop and list
rather than mix the two. Weigh that against the size of the artefact before rebuilding: it
is one day on secondary date elements, not on the study timeline.

**Mutation-checked, not trusted for going green.** Eight mutations, each reverting one
part of the fix: bare dates ignoring the carry (the exact pre-fix behaviour), the free
text path dropping it, `shift_text_dates` dropping it internally, sequences recomputing
their own, `StudyTime` no longer preferred, the carry forced to zero, the `DT` fallback
removed, and `shift_dates` never asking for one. The first version of the test survived
two of those: the embedded timestamp in the fixture was the 14 digit form, which is a
whole instant and never reaches the bare-date branch, and every `TM` in the fixture held
the same value, so preferring `StudyTime` over another `TM` changed nothing. Fixed by
adding an 8 digit date in `StudyDescription` and an `InstanceCreationTime` (0008,0013)
that disagrees with `StudyTime` (0008,0030) and sorts before it. All eight now fail the
test.

### 2026-08-14: v0.11 shipped without the retry on purpose, and what v0.12 had to prove

Worth recording because the reasoning is easy to mistake for an oversight. v0.11 was cut
from `0ba762f` and sent to the oncologist **without** the `os.replace` retry, which
landed 33 minutes later in `13f2f73`. That was deliberate: the retry addresses a theory
about transient Windows file holders that no run has ever confirmed, and a retry that
succeeds on the third attempt destroys the only chance of learning what was holding the
file. After three wrong guesses, the signal was worth more than the convenience.

**But v0.11 turned out to be a poor diagnostic build, which was not the intent.** Reading
it back: the failure path is `except OSError as e`, and `e` is bound and never used. The
message has a single `{}`, filled with the mapping file path, so **the WinError number
never reaches the operator**, and error 32 (sharing violation, something genuinely has it
open) and error 5 (access denied, permissions or a scanner) point at different causes.
`VerificationError` routes to `_report_verification_failure`, not to the traceback
handler, so nothing else captures it either. Beside that, `os.remove(tmp)` deletes the
temporary spreadsheet, which was the artefact that produced the last diagnosis. So the
build sent out to gather evidence discards the evidence for every theory, including the
Excel one. Do not treat "it stops loudly" as "it reports usefully"; they are different
properties and only the second one was needed here.

Note also that "the spreadsheet was not open in Excel" is a recollection, not a
measurement, and should not be leaned on. The message names Excel alongside OneDrive,
backup tools and antivirus, ruling nothing in or out.

**What v0.12 had to prove before the retry could ship.** The dialog tells the operator to
rename the kept copy over the real file and run again. That sequence had never been
executed by anything. `tests/test_recovery.py` now runs it end to end: the mapping swap
fails mid-run, the patient's files are already written, the rename restores a readable
mapping with the folder assignment and the offsets, and a later run adds a session with
the run 1 files byte-identical and the real 31 day gap still 31 days in the output. That
is exactly the timeline inconsistency the hospital incident would have caused.

Three smaller claims the dialog makes, now asserted rather than assumed: the underlying
OS error appears in the report; a failed save leaves an existing mapping undamaged, which
is the whole point of writing to a temporary file and swapping; and the retry gives up,
measured at 3.0 s for six attempts, since an unbounded loop in a windowed app looks to
the operator exactly like the hang that started this.

**The test was mutation-checked rather than trusted for going green.** Dropping the OS
error from the message fails it, and restoring `os.remove(tmp)` on failure fails it too.
That second mutation is precisely v0.11's shipped behaviour, so the test would have
caught it. A green suite proves nothing until you have watched it go red.

Useful detail confirmed while writing it: `_patient_offsets` reads the mapping file
first and only falls back to the per-patient state, so renaming the kept copy into place
restores the authoritative record rather than a second-best one. The two agree.

### 2026-08-13: the v0.10 crash, diagnosed from the file it left behind

The leftover `dicom-anon-mapping.xlsx.tmp.xlsx` on the oncologist's machine is the
evidence, and it says this: `_save_mapping` wrote the temporary file and then
`os.replace(tmp, mapping_file)` did not complete. The temp file holds 33 rows, 32 stamped
2026-01-27 from the original export and exactly one stamped the day of the run, with
8591 files and its date offsets recorded. So one patient was anonymised in full, the
mapping was built, the swap failed, and the exception escaped a windowed app.

**She has since confirmed the spreadsheet was NOT open in Excel**, so that theory is
dead, and it was the third wrong guess in this incident after the file extension and a
network share. What she did say is decisive in another way: "I repeated about 4 times and
each time it only does brain 002." The failure is deterministic, not a transient lock.

**She has since said each attempt took about ten minutes**, which settles it. Ten minutes
is the run re-anonymising all 8591 files; skipping them takes seconds. So nothing was
recorded between attempts, and the failure is in `_save_mapping`, which ran before
`save_patient_state`. It also means she must be clearing or changing the output folder
between attempts, or the second run would have been refused for holding data with no
state rather than crashing again.

What actually raises there is still unknown, and after three wrong guesses it is not
worth a fourth. `os.replace` is now retried six times over three seconds, because the
usual Windows causes (OneDrive, an indexer, a virus scanner) release the handle in that
window, and only then does it give up.

The original reasoning that got here: `_save_mapping`
ran BEFORE `save_patient_state`, so if the spreadsheet write fails the state is never
recorded and the next run redoes the whole patient. If instead the crash came after the
state was saved, the retry would skip those files in seconds. **So: is each retry slow,
reprocessing all 8591 files, or nearly instant?** Slow means the failure is in the
spreadsheet write; fast means it is later, most likely the empty-folder `os.listdir`
already fixed.

The fix does not depend on which lock it was: any failure of that call
now stops the run with "the spreadsheet is open in Excel or another program, close it and
run again", and KEEPS the temporary file, naming it in the message. An earlier version of
this fix deleted it for tidiness, which would have destroyed both the only up-to-date
copy of the mapping and the only evidence of the failure. That was the wrong instinct and
the incident is exactly why.

**The temp file was the only copy of that patient's date offsets**, which is the part
worth remembering. Offsets live in the mapping file and nowhere else, not in the
per-patient state. Because the swap failed, the real mapping was still January's, with no
offset for the patient just written. Re-running after discarding the temp file would
generate a fresh offset every time while the 8591 files already on disk stayed shifted by
the old one and were skipped as already written, leaving that patient's timeline
inconsistent with the offset recorded for them. Recovery is to rename the temp file over
the real one before re-running.

Fixed properly as well: offsets are now written into the per-patient state too, and the
state is saved BEFORE the spreadsheet. The state is what makes a run resumable, so losing
it to a failure saving a spreadsheet was the wrong way round. `tests/test_offsets_survive.py`
fails the build if a failed mapping write loses them again.

Two dead ends worth recording so they are not rediscovered. The mapping file carries an
`anon_patient_id` column the current code never writes; it is legacy from the 2024 build
and harmless. And the copy sent for diagnosis had its hospital ID column deleted, which
briefly looked like a mapping file with no patient IDs at all.

### 2026-08-13: v0.10 crashed at the hospital, before the cause was known

The oncologist ran v0.10, it anonymised one patient and then crashed. **No diagnosis
yet.** What follows is what was fixed, not what happened, and the two must not be
confused: two crash paths were found and closed, but there is no evidence that either
is the one she hit.

One speculative cause was floated and should be written off: that her source files might
not be named `.dcm`. There is no evidence for it, and every local export uses `.dcm`. It
is recorded only so nobody later mistakes it for a finding.

**What is real.** Two paths in `process_folder` raised out of a windowed app, and
`anon_button_clicked` caught only `VerificationError`, so the window simply died:

- A patient whose folders yield no `.dcm` files. The destination is created inside the
  file loop, so if nothing is written it does not exist, and `os.listdir` on it raised
  `FileNotFoundError`. This is the bug recorded under defect 6 as a smaller thing noted
  and not done. It was left undone and it reached a user.
- Any write failing. `os.makedirs` and `ds.save_as` sat outside every `try`.

Both are reproduced in `tests/test_crash.py`. The first now skips the patient and
reports them, counting any non-`.dcm` files in the folder so that "empty" and "named
something else" are distinguishable. The second is caught by a new handler that saves a
report with the traceback, the source, output and lookup paths, and shows a dialog
saying what it means for the data.

**The point of the general handler is diagnosis, not repair.** The next failure, whatever
it is, leaves a file the researcher can forward instead of a dead window. That is the
only reason to believe the next report will be actionable, because this one was not.

**To identify the actual cause, ask for:** `dicom-anon-mapping.xlsx` from her home
folder, which is saved after every patient and so names exactly the last one that
completed; the source folder that comes after it; and whatever the error dialog said, if
one appeared. A frozen windowed build shows PyInstaller's traceback dialog on an
unhandled exception, which is why `disable_windowed_traceback` must stay off.

### 2026-08-13: several source folders per patient is normal, not a collision

The duplicate-patient-ID check was wrong, and a real export shows why.
A local pre-anonymisation test export contains `900001_SURNAME^GIVEN^R` and `900001_SURNAME^GIVEN^R^MR`. That
is **one patient**, measured: both folders carry DICOM `PatientID` 900001, and only
`PatientName` differs by a trailing `^MR` component. The export names folders
`<PatientID>_<PatientName>`, so a patient whose name is recorded two ways in the source
system gets one folder per spelling.

Refusing that run was a false stop on something the data does routinely. Worse, the check
was reasoning from the **folder name**, which cannot tell "one patient, two spellings"
from "two patients, one parsed ID". The source `PatientID` can, and `RunVerifier` already
tests exactly that as each file is read, so the accurate check was there all along and the
folder-name check was both redundant and harmful.

Now: source folders are grouped by parsed patient ID and all of a patient's folders are
processed into their single anon folder, sharing one state, one UID map and one study
numbering. A genuine collision, two different source `PatientID`s reaching one anon
folder, still stops the run.

**Merging needs one guard the old code did not have.** Two folders could hold the same
relative path, and the second write would silently overwrite the first. `_check_merge_collisions`
compares the paths that repeat and reads only those files: the same instance exported
twice is not a collision and should simply overwrite, per rule 3, while two different
instances at one path is data loss and stops the run. The real folders share no path,
SOP UID or study UID, but that is luck rather than a guarantee.

Verified on the real thing: the two folders merged into one anon folder, 6048 files
(926 + 5122), 19 study labels, 6261 UIDs, one source `PatientID` recorded, one identity
in the output, no warnings, and every modality preserved (MR, CT, RTSTRUCT, REG, RTDOSE,
RTPLAN, PR). The previous code refused this run outright.

Fixed in passing, since the loop was being rewritten: a folder whose name does not parse
used to `break`, abandoning every remaining patient while still saving the mapping for
those already done. It now collects those folders, reports them in one dialog and carries
on, the way an unknown patient ID already did.

#### The folder name still decides; the PatientID now checks it

Worth stating plainly, because the merge change makes it easy to assume otherwise:
**the anonymised folder is still chosen from the source folder's NAME.** The name is
parsed for the numeric ID, the lookup file is keyed on it, and that decides where the
files go. The DICOM `PatientID` is never used to choose a destination.

What it is used for is checking that decision. That left a gap: a folder named for one
patient but filled entirely with another's files was accepted in silence, because every
file in it agreed with every other and nothing conflicted. Demonstrated, not theorised: a
folder named `1234_...` containing only patient 9999's files was written into 1234's
anonymised identity with no warning at all.

`compare_patient_id` now compares the two per file and stops the run when they differ.
Measured first on the local exports: across all six source folders the folder-name ID and
the `PatientID` inside agree exactly, so the export script derives the folder name from
the DICOM and the check is safe to enforce.

It only compares when the `PatientID` is numeric, and reports rather than blocks when it
is not. A site that prefixes or pads its IDs would otherwise be stopped on every file,
which is the mistake the duplicate-folder check made and worth not repeating. The
compromise leaves a hole, a non-numeric `PatientID` that disagrees, and that hole is
visible in the end-of-run warnings rather than silent.

#### A UI element that is not a UID

The run warned about `(2005,1395)` holding
`'7,IMAGE_TYPE,SLICE_NUMBER,ECHO_NUMBER,...'`, 113 characters in a `UI` element. Worth
chasing, because `_anonymise_uids_recursive` walks by VR and would have replaced that
descriptive string with a generated UID, corrupting data that is not identifying.

It does not, and the reason is ordering: the tag is **private**, and
`remove_private_tags()` runs before the UID remapping, so it is gone before anything can
rewrite it. Confirmed on the output: no private tags and no `(2005,1395)` in any file.

A scan of all 6234 files found this to be the **only** `UI` element in the whole dataset
not holding a UID-shaped value, and it is private. So walking by VR is safe here, but the
margin is the ordering of two lines in `anonymise_dicom`. If private tag removal ever
moves after UID remapping, this breaks silently.

### 2026-08-13: pydicom moved to 3.0.2, and TOOL_VERSION deliberately not bumped

`requirements.txt` pinned `pydicom==2.4.3` while every real-data trial had been run
against 3.0.2 on a developer machine. The shipped build therefore had only synthetic
coverage, and the version that had processed 45359 real files was not the one users got.
That is the wrong way round, so the pin moved to 3.0.2, the current release.

**The output is byte-identical between the two.** Measured, not assumed: 40 real Philips
files anonymised under 2.4.2 and 3.0.2 with `generate_uid` monkeypatched to a
deterministic counter, so the pydicom version was the only variable. Same aggregate
SHA1, all 40 files identical byte for byte.

The first attempt at this comparison was wrong and worth recording: it gave each version
a fresh `uid_map`, so every UID was newly generated and every file differed by
construction. The hashes disagreed and it looked like a real encoding difference. It was
not. Control the randomness before concluding anything from a byte comparison.

**So `TOOL_VERSION` stays at `0.8`.** Bumping it would be the reflex, since the rule is
that a version change forces every patient's folder to be produced again. But that rule
exists to stop two *different* anonymisations sharing a folder, and here the output is
identical. Bumping would force a full reprocess of everything for no benefit, which is
expensive and would train people to ignore the mechanism. Bump `TOOL_VERSION` when the
bytes change, not when a dependency does.

Also removed from both spec files: `hiddenimports=['pydicom.encoders.gdcm',
'pydicom.encoders.pylibjpeg']`. Those modules do not exist in pydicom 3, which renamed
the package to `pydicom.pixels`, and they were never needed in the first place: the app
touches no pixel data, it passes it through as raw bytes.

The two-version support in `tests/_fixtures.py` stays. It costs nothing and the pin will
drift from developer machines again.

### 2026-08-13: full-size trial, and the numbers to plan the rebuild with

Third trial, on the largest patient in the export (45359 files, 25 GB) staged as a source
folder via an APFS clone, so it cost no extra disk and the export was never written to.
Note this is already-anonymised data being anonymised again: it exercises scale,
throughput and robustness, not the source-side identity logic, because every file carries
the same `PatientID`.

| | |
|---|---|
| files | 45359, all written, **zero verification failures** |
| elapsed | 994 s (17 min) |
| throughput | 46 files/s, 27 MB/s |
| output size | unchanged from the source, within measurement noise |
| peak memory | **4.4 GB** |
| state file | 9.3 MB: 28031 UIDs, 53 study labels, 45359 files tracked |

**Extrapolated to the full export: about 4.6 hours for 761631 files.** That is the number
to plan the rebuild with, measured on a laptop with source and destination on one disk.

Three things worth carrying forward.

**No false stops at scale.** 45359 real files, every one verified, none rejected. After
defects 8 and 9 that was the open question, and this is the strongest evidence so far
that the checks do not misfire on real data.

**Peak memory of 4.4 GB for one patient needs watching.** It is a high-water mark rather
than steady state, but the rebuild processes 33 patients in one run and nothing here
shows whether it grows across them. Watch it, and if it does grow, process patients in
separate runs: state is saved per patient and files already written at the current
version are skipped, so an interrupted rebuild resumes cheaply rather than starting over.

**The contamination warning fired on genuinely contaminated real data.** Brain-0005 is one
of the 18 mixed folders, and the run reported it holding more than one birth year or sex.
It *warned* rather than stopped, which is correct here and worth understanding: the input
was already anonymised so every file carried one `PatientID`, leaving only the weak proxy
to fire. In the real rebuild, from true source data, the same contamination would be
caught by the source `PatientID` check and would **stop** the run. That difference is
exactly why the source-side check is the one that matters.

Also confirmed: `check-anon-output.py` over the result reported **no stale output at all**,
so the 438 files in that folder that still carried real birth dates and populated
identifying tags were properly cleaned this time.

### 2026-08-13: RT trial, the case the persisted UID map exists for

Second trial, on the real RT patient in `Test-GBM-Sorted-1`: CT, MR, RTSTRUCT, RTPLAN,
RTDOSE and REG, 756 files. Split deliberately across two runs, images first and the RT
objects second, so the structure sets were written by a **later run** than the images
they contour. That is defect 2's scenario exactly, and the one that produced the export's
undetectable duplicates.

Method: count references that resolve to nothing, in the source and in the output, and
require the output to introduce none. A pre-existing dangling reference is the source's
problem; a new one would be ours.

| modality | references | dangling in source | dangling in output |
|---|---|---|---|
| RTSTRUCT | 164 | 0 | **0** |
| RTDOSE | 35 | 0 | **0** |
| RTPLAN | 18 | 0 | **0** |
| REG | 3603 | 2928 | **2928** |
| CT | 4 | 4 | 4 |
| MR | 3 | 3 | 3 |

Nothing broken that was not already broken, and no source UID present in the output. The
structure sets written in run 2 resolve correctly to images anonymised in run 1, which
only works because `uid_map` is persisted.

**The REG figure is a finding about the source data, not about the tool.** 2928 of 3603
references in the registration objects already point at instances that are not in the
export, in the source. Anything downstream that resolves registrations by UID should
expect that, and it is worth raising with the hospital: it suggests the export omits
series the registrations were computed against.

Also fixed here: the duplicate-patient-ID check was scanning **every** source folder,
including ones the lookup never names. A source directory holding folders from another
delivery would have halted the run for a patient that would have been skipped anyway.
It now only considers folders the lookup actually names, covered by
`tests/test_collisions.py`. Confirmed against `Test-GBM-Sorted-2`, which really does
contain two folders whose names parse to the same ID: naming a different patient
proceeds, naming the colliding one refuses.

Performance note for the rebuild: run 2 took 76 seconds for 84 RT files. RTSTRUCT and REG
carry thousands of sequence items, and `snapshot_source`, the anonymiser and `verify_file`
each walk the whole dataset, so verification costs roughly three traversals per file.
Acceptable, but RT objects are far slower per file than images.

### 2026-08-13: v0.8 trialled on real DICOM, and the rewrite problem it exposed

First run of v0.8 against real scanner data rather than fixtures, using the local
pre-anonymisation test datasets (`Test-GBM-Sorted-*`), one patient into an empty
destination. Real Philips MR, three sessions, 1293 files.

**It worked, and the output is correct.** Verified against the source file by file:

- 309 private tags in the source, 0 in the output;
- all 20 `DA`/`TM`/`DT` elements in the sample file changed, none retained;
- 0 overlap between source and output UIDs;
- `InstitutionName` and `StationName` populated in the source, blank in the output;
- study spacing preserved exactly, `StudyID` renumbered `STUDY_0001`..`0003`;
- `check-anon-output.py --all-files` over the result: PASSED.

Then the incremental cases, all on real data: a second run adding another patient left
the first patient's 1293 files **byte-identical**; a lookup file trying to move a patient
was refused by rule 1; and `Test-GBM-Sorted-2`, which really does contain two folders
whose names both parse to the same patient ID, was refused. Under v0.7 those two folders
would have been written into one anon folder without a word.

**The problem the trial existed to find: every run rewrote everything.** A re-run with
nothing changed still took 90 seconds and rewrote all 2049 files. Scaled to the real
export that is roughly **nine hours and 301 GB rewritten every time the oncologist adds
one session**, which makes the incremental workflow unusable in practice even though it
is correct.

The state already recorded each written path against the version that wrote it, so the
fix was to skip a file already present at the current `TOOL_VERSION`. The same re-run now
takes **0 seconds**. Adding new data still processes normally, which `test_longitudinal`
covers, and a version change still forces the whole folder to be produced again because
`stale_files` compares against the recorded version rather than mere presence.

Found alongside it: `valid_file_count` in the mapping file was accumulated with `+=` on
every run, so re-processing a patient inflated it without limit. It is now set from
`len(state['files'])`, the true total, and the counts match the files on disk exactly.

Not a defect but worth knowing: because the birth date is reduced to 1 January of its
shifted year, an age derived from the output dates can differ from the stored
`PatientAge` by up to a year. That artefact predates v0.8, which reduced to 1 January of
the real year, so it is unchanged behaviour rather than a regression.

### 2026-08-13: the export measured, and what it actually shows

First run of `check-anon-output.py` against the real export (local copy of `GBM-SP`,
33 folders, 761631 files, 22857 series directories sampled). **Nothing below contains
patient data; this file is in a public repository. The report JSON does contain real
birth dates and was deliberately not committed.**

**The headline: 18 of 33 folders hold data from two different people.** Not a
suspicion, a measurement.

The mechanism is defect 4's assignment drift, and the evidence took two passes to read
correctly. The first pass compared birth year and sex per folder and found 15 identities
apparently spanning several folders, which looked like patients smeared across the
export. That reading was wrong: with 33 patients and only 24 distinct (year, sex) pairs,
collisions are guaranteed by pigeonhole, and some of those matches were coincidence.

The second pass used the **full** birth dates that stale files still carry, which is a
far stronger identifier, and it inverted the picture:

- folders containing more than one real birth date: **0**
- folders containing more than one anonymised birth year: **0**

Every folder holds exactly one identity of each kind. They are simply **different
identities**. In 18 folders the stale files belong to one patient and the current files
belong to another. Four folders are internally consistent, and eleven have no stale
files at all, having been written entirely by the newer build.

The affected folders form a chain: the current files in one folder match the real
patient whose stale files sit in the previous affected folder, skipping exactly the
folders that are internally consistent. A permutation that orderly is not a coincidence.
It is the lookup file's assignment changing between runs, precisely as defect 4
predicted: the patient was written to their new folder, the old copy stayed where it
was, and nothing warned.

Two things follow.

**Rule 1 is confirmed as the fix, empirically rather than by argument.** An immutable
patient-to-folder assignment would have stopped the run that caused this.
`check_assignments` now does exactly that.

**The exact per-folder attribution is still unknown.** Birth year and sex cannot resolve
which specific patient is in which folder, because the years collide. Resolving it needs
either the ID mapping spreadsheet from the hospital, or the pixel hashing in
`check-patient-integrity.py`. Do not attempt to repair the export folder by folder from
year matching; rebuild from source instead.

Also measured: 9710 sampled files still carry a real birth date, a raw `StudyID` and
populated identifying tags, across 22 of 33 folders. The tags most often left populated
were `EthnicGroup`, `PatientAddress`, `PatientMotherBirthName`,
`ReferringPhysicianAddress` and `ReferringPhysicianName`, each in 9710 files. Every
entry in `IDENTIFYING_KEYWORDS` is now a valid DICOM keyword, and no folder contained a
file labelled for another folder.

### 2026-08-13: defects 8 and 9, found by simulating messy data

Prompted by asking what would happen when v0.8 first meets real hospital DICOM rather
than clean fixtures. Both were found in minutes by building the awkward cases by hand,
and both would have mattered on the first real run.

**Defect 8: one non-conformant file would halt an entire run.** `_get_study_label`
returns the bare string `STUDY` when a file has no `StudyInstanceUID`, which fails
`verify_file`'s `STUDY_\d+$` assertion. Since v0.8 stops the run on any verification
failure, a single odd file would have blocked the researcher with no way forward. Now
returns `STUDY_0000`, a reserved label that groups such files without implying they are
one study.

**Defect 9: identifying tags nested in sequences were never blanked, and the check was
blind to it.** The blanking used `if kw in ds`, which only inspects the top level, so an
`InstitutionName` or `ReferringPhysicianName` inside `RequestAttributesSequence` or
`OriginalAttributesSequence` survived. Real hospital data puts them in both places.

The worse half is that `verify_file` used **the same top-level test**, so it agreed with
the bug instead of catching it. A check written from the implementation can only confirm
what the implementation already does; it has to be written from the property. Both now
walk: `blank_identifying_tags` and `populated_identifying_tags`.

This is the same shape as defect 7 and the same lesson as defect 1: the UID handling
walked recursively from the start, and everything modelled on it was correct, while
everything that used a flat keyword test was quietly wrong.

`tests/test_messy.py` covers both, plus truncated dates, whitespace-only times, empty
sequences and private tags nested in sequences.

### 2026-08-13: defects 2, 3 and 4, and the state store they all needed

All three were the same missing thing: nothing survived a run. `uid_map` and
`study_label_map` were created inside `process_folder`, empty, once per run, and shared
by every patient. That single line is defect 2 (nothing persists) and defect 3 (nothing
is scoped) at once, and defect 4 is what happens when the destination remembers more
than the tool does.

**The state store.** One JSON file per anon folder, under `~/.dicom-anon-state/<key>/`
where the key is a hash of the destination path. Per patient it holds `uid_map`,
`study_label_map`, `source_patient_ids`, `tool_version`, and `files` mapping each
written relative path to the version that wrote it. Written through a temporary file and
renamed, like the mapping file, because losing it reintroduces defect 2 exactly.

Placement follows rule 2. Outside the destination, because it holds source UIDs and
hospital IDs and would otherwise be delivered along with the data it de-identifies.
Keyed to the destination rather than loose in the home folder, so pointing the tool at a
different output folder cannot silently reuse another delivery's UID map. The rule also
says to exit non-zero if the state is missing; the GUI equivalent is refusing to write
into a destination it has no record of, below.

**Defect 3, without losing the detector.** `uid_map` is now per patient, so two patients
can never share a pseudonym. The earlier entry warned that this would destroy the
cross-folder detector that existed only because the map was global. It turned out the
detector was not worth rebuilding as a UID index: an 800k-entry file to catch something
the source PatientID already catches directly. What was needed instead is
`recorded_owners`, which seeds `RunVerifier` from the state with every source PatientID
seen in an earlier run. Cheap, and it closes the one gap the within-run check has: a
folder filled *entirely* from the wrong source patient has no within-run conflict to
notice.

**Defect 4 has two halves and they need different answers.**

- *Unrecorded output.* A destination holding data with no state was written by a build
  with none of the current checks, and its UID maps and offsets cannot be reconstructed.
  Rule 4 says never to write current-version files beside older ones, so the run stops
  and asks for a fresh destination. This is the documented supported path from the
  original analysis, now enforced rather than suggested. Note the consequence: **the
  existing export cannot be added to and has to be rebuilt.**
- *A version change.* `TOOL_VERSION` is recorded per patient. If it is older, every file
  already written for that patient must be produced again. `stale_files` compares what
  is recorded against what this run would write, and the run stops listing exactly what
  the source can no longer produce. That is the "refuse and list" branch; reprocessing
  happens naturally when the source still holds everything, because paths mirror the
  source and writing is idempotent (rule 3).

`TOOL_VERSION` is `0.8` and must be bumped whenever a change alters what the anonymiser
writes, or a patient's folder will silently mix two versions of the output.

Rule 5's orphan check is what `unrecorded_folders` implements, at folder granularity
rather than per file. Per-file orphan detection is still not done: a file deleted from
the source stays in the destination and nothing notices, as long as its folder is
recorded.

### 2026-08-13: defect 1 fixed, and the offset became the thing that matters

`shift_dates` walks every `DA`, `TM` and `DT` element by VR, through nested sequences,
exactly as `_anonymise_uids_recursive` walks UIDs. `verify_file(check_dates=True)` is
now the default, so the assertion that would have caught defect 1 on the first file is
on permanently.

Three things came out of doing it that were not in the original analysis.

**The offset was public.** The old code shifted `StudyDate` by a hard-coded
`offset_days=30`, in a repository anyone can read. Even without the SeriesDate
differencing trick, the shift could be undone by anybody who opened the source. Walking
every date element fixes nothing if the offset is a constant in the code. Offsets are
now random per patient, generated by `new_offsets()`, and **stored in the ID mapping
file**, which was already the re-identification key and already lives outside the
delivered data. Per patient rather than per run, so two patients' timelines cannot be
lined up against each other. Stored rather than derived, so the oncologist's later
studies keep their true spacing from the earlier ones. That is rule 2 arriving by a
different route: the mapping file is now the state file for offsets.

**`PatientAge` had to be decided, and the answer changes the birth date.** Keeping the
real birth year and keeping `PatientAge`, which is what the tool did, hands over the
offset: age minus (study year - birth year) is the shift in years. So
`_anonymise_birthdate` now runs **after** `shift_dates` and reduces the already-shifted
date to 1 January of its year. Age stays correct, because it is the gap between two
dates that both moved by the same amount, and the year is no longer real. This is
strictly better than blanking `PatientAge`, which would have lost a prognostic variable
for nothing.

**DA and TM are two halves of one instant, and shifting them separately breaks the
file.** With a seconds component in the offset, a time that carries past midnight left
`StudyDate` on the 3rd while `AcquisitionDateTime`, a DT holding the same instant,
landed on the 4th. `shift_dates` now pairs a `DA` with its `TM` and shifts them as one
moment. The partner is found by name, `keyword.replace('Date', 'Time')`, which picks up
`StructureSetDate`/`StructureSetTime` and `DateOfLastCalibration`/`TimeOfLastCalibration`
without anyone listing them, for the same reason the walk is by VR. Unpaired elements
still shift individually.

Free text is handled too: `SeriesDescription` values like `20210819134732-1ABrain` have
the timestamp shifted in place, matching both the 8 and 14 digit forms. Matching only 8
digits finds nothing there, because the date is followed by more digits.

`StudyDescription` is still preserved deliberately, apart from any date inside it.

### 2026-08-13: QC on the ID lookup file, and rule 1 enforced at last

The lookup file is where the oncologist assigns anonymised IDs, which makes it the most
dangerous input the tool takes, and until now it was read with `dict(zip(...))` and no
checks at all. `check_lookup` rejects, listing every problem at once: one anon ID given
to two patients, a patient listed twice, a missing ID on either side, a non-numeric
patient ID, and anon IDs that are not usable folder names on Windows.

`check_assignments` implements **rule 1**, the one the incremental analysis said would on
its own have prevented the whole incident: a patient's folder assignment is permanent,
the lookup may only add patients, and a lookup that moves a patient or reassigns their
folder stops the run. It runs against the mapping file before any DICOM is read.

Two things found while testing it:

- **`astype(str)` on a numeric column produced `'1234.0'`.** One blank cell anywhere in
  the patient ID column makes pandas type it as float, and every ID then matches no
  patient folder. The failure mode is a run that silently processes nobody and reports
  every patient as "not found". `_cell_to_str` handles it.
- **Excel destroys leading zeros itself.** `'01234'` becomes the number 1234 on a
  round-trip, so a padded ID cannot be expressed in the lookup file at all. The real risk
  is therefore not in the lookup but in the source: `0123_X` and `123_Y` both parse to
  123 and would land in one folder. `process_folder` now refuses to start when two source
  folders share a parsed patient ID.

The mapping file gained a `DO NOT EDIT` sheet, written first so it is what opens, and it
is saved after every patient rather than once per run, through a temporary file with the
previous version kept as `.bak`. It now holds the date offsets, so a hand edit can
silently shift a patient's new studies by a different amount from their old ones, and
losing the file means the shifts can never be undone or checked.

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

