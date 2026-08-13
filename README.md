# DicomAnon
This is a repository for a DICOM anonymiser, deftly named DicomAnon. Although there are many applications that will anonymise DICOM files, this one was written to do so in bulk. With DicomAnon, you can point to a parent folder containing many patient folders, which may contain many imaging sessions, which may contain images acquired with different modalities. Note that patient folders are assumed to adhere to a naming convention of `<patientID>_<patientName>`, where patientID is a number.

After telling DicomAnon where you want the anonymised files to be placed, it will preserve the folder structure and place anonymised DICOM files there. DicomAnon does not change the original files; it merely reads them, changes the value of DICOM tags that contain personal information about the patient, and writes the anonymised version to the designated destination folder.

<img width="752" height="384" alt="image" src="https://github.com/user-attachments/assets/38d1d9bb-19c0-4239-818d-cec97df44bfd" />


The DICOM files are anonymised by blanking the values of the following DICOM tags:

### Patient
* PatientName - replaced with the anonymised ID you assigned this patient in the [ID lookup file](#the-id-lookup-file)
* PatientID - replaced with the same anonymised ID

DicomAnon does not invent these values or add any prefix to them. Whatever you put in the
second column of the lookup file is written into both tags exactly as it appears there, and is
also used as the patient's folder name in the output. So a lookup row giving `Brain-0001`
produces a `Brain-0001` folder containing files whose `PatientName` and `PatientID` are both
`Brain-0001`. If you use a different naming convention, that is what you will get.

### Patient (except PatientName, PatientID)
* OtherPatientIDs
* OtherPatientNames
* PatientBirthName
* PatientMotherBirthName
* PatientAddress
* PatientTelephoneNumbers
* PatientInsurancePlanCodeSequence
* PatientComments
* EthnicGroup
* Occupation
* AdditionalPatientHistory
* PatientReligiousPreference

### General person/organisation
* ResponsiblePerson
* ResponsiblePersonRole
* PersonName
* PerformingPhysicianName
* ReferringPhysicianName
* ReferringPhysicianAddress
* ReferringPhysicianTelephoneNumbers
* RequestingPhysician
* OperatorsName
* PhysiciansOfRecord
* NameOfPhysiciansReadingStudy

### Institution / contact info
* InstitutionName
* InstitutionAddress
* InstitutionalDepartmentName
* StationName
* DeviceSerialNumber
* SoftwareVersions

### Study / scheduling / admin IDs
* AccessionNumber
* IssuerOfPatientID
* IssuerOfAccessionNumberSequence
* RequestingService
* AdmissionID
* InsurancePlanIdentification
* VisitComments
* ScheduledProcedureStepDescription
* RequestedProcedureDescription
* RequestedProcedureID
* RequestedProcedureLocation

### Free-text descriptions
* ProtocolName
* PerformedProcedureStepDescription
* StudyComments

### Addresses / geographic
* CountryOfResidence
* RegionOfResidence
* PatientMotherBirthName


### Dates and times
Every date and time in the file is shifted by the same offset: not just `StudyDate`, but `SeriesDate`, `AcquisitionDate`, every `...Time`, every combined date-time, the same tags inside nested sequences, and any date written into a free-text field such as `SeriesDescription`.

The offset is a random number of days and seconds, generated per patient and recorded in the ID mapping spreadsheet. Because it is stored, the same patient gets the same offset every time, so studies added months later keep their true spacing from the earlier ones. Because it is random and per patient, it cannot be guessed from the software and one patient's offset tells you nothing about another's.

The gap between any two studies for a patient is therefore exactly preserved, while the real dates are not recoverable from the files.

`PatientBirthDate` is reduced to 1 January of its year, and that year is the shifted one, not the real one. `PatientAge` is kept: age is the gap between the birth date and the study date, and shifting both by the same offset leaves it correct.

> **Why this changed in v0.8.** Earlier versions shifted `StudyDate` alone, by a fixed 30 days written into the source code. `SeriesDate` sat next to it unshifted, so subtracting one from the other recovered the offset; and the 30 days was public anyway. Every time field, and every date field except `StudyDate`, was written out untouched. Data anonymised by an earlier version does not have this protection.

Further, it recursively remaps all UIDs in the dataset (and sequences), except SOPClassUIDs. The reason for doing this is so that even if the anonymised DICOMs are loaded back into the system at their originating institution, the patient could still not be identified.

On completion, DicomAnon will save a mapping of the true patient IDs to anonymised patient IDs as an Excel spreadsheet named `dicom-anon-mapping.xlsx` in your home folder. DicomAnon shows the full path in a dialog when it finishes - see [Where to find the ID mapping spreadsheet](#where-to-find-the-id-mapping-spreadsheet) below.

Note that adding new patient folders (and updates to existing patient folders) will not erase previous DICOM files for the same patient; the new anonymised DICOM files will be saved in the same structure alongside those previously processed. The new patient IDs will also be added to the Excel mapping spreadsheet.

## Adding new studies to a patient later
This is the normal way the tool is used: a patient accrues sessions over weeks, and each batch is anonymised into the folder they already have. For that to be safe, DicomAnon has to remember what it did last time, so it keeps a record for each output folder.

That record holds the map from real UIDs to anonymised ones, the study numbering, and which version of DicomAnon wrote each file. Keeping it is what makes the following true:

* the same real UID always becomes the same anonymised UID, so a new study that refers to an earlier one still resolves. Structure sets reference series, and registrations match frames of reference, by UID: without this those links break silently;
* `STUDY_0001`, `STUDY_0002` and so on keep counting rather than restarting at 1 each run;
* two different patients never receive the same anonymised UID, even where their original files shared one, which vendor-generated UIDs often do.

The record is stored **outside** the output folder, under `.dicom-anon-state` in your home folder, because it contains real UIDs and patient IDs. Like the mapping spreadsheet, it must never be copied to whoever receives the anonymised files. It is tied to the specific output folder it describes, so using a different output folder starts a fresh record rather than silently reusing another delivery's.

**Keep it.** If it is lost, DicomAnon cannot add to those folders safely and will say so.

### When DicomAnon refuses to add to a folder
Two situations stop a run rather than producing output that cannot be trusted:

* **The output folder contains data DicomAnon has no record of.** This is what you get when pointing a new version at a folder filled by an older one. The UID maps and date offsets used back then cannot be reconstructed, so nothing new can safely be added beside that data. Process the source into a new, empty output folder instead.
* **A patient was last processed by an older version of DicomAnon.** Everything already written for them has to be produced again with the current version, so that one folder never holds two different versions of the anonymisation. If the source no longer has all of that patient's data, DicomAnon lists exactly which files it cannot reproduce.

## Checks that can stop a run
DicomAnon checks every file it anonymises before writing it, and stops the whole run if a check fails rather than carrying on and producing output nobody can trust. A dialog names the source file and what was wrong, and the same text is saved to a report file so you can send it on.

### Where the report file is, and how to handle it
The report is always called `dicom-anon-verification.txt` and is saved in your **home folder**, the same place as the ID mapping spreadsheet:

* Windows: `C:\Users\<your-username>\dicom-anon-verification.txt`. Press <kbd>Windows</kbd> + <kbd>R</kbd>, type `%USERPROFILE%` and press <kbd>Enter</kbd> to open that folder.
* macOS: `/Users/<your-username>/dicom-anon-verification.txt`. In Finder choose **Go > Home**, or press <kbd>Shift</kbd> + <kbd>Command</kbd> + <kbd>H</kbd>.

The dialog also shows the full path, and you can select it with the mouse and copy it.

> **The report can contain patient identifiers.** It names the source files involved, and source folder and file names contain real patient IDs and names. It is deliberately kept out of the output folder for that reason. When sending it to whoever supports the tool, send it the way your institution requires identifiable data to be sent, not by ordinary email.

It is rewritten each run, so if a run fails, copy it somewhere safe before running again.

A run stops if:

* a file still carries an identifying tag, a real birth date, a raw `StudyID`, a source UID, or a private tag after anonymisation;
* a file's `PatientName` or `PatientID` does not match the anonymised folder it is going into;
* **an output folder would receive files from two different source patients**, or one source patient would be written to two different output folders. This is the check that catches a source patient folder containing somebody else's study, which anonymisation would otherwise relabel and make undetectable.

If a run stops, the files written before that point are still in the output folder, but the output is incomplete and should not be copied anywhere until the cause is fixed.

Some findings only warn, because they do not justify discarding a finished run: for example an output folder holding more than one birth year or sex while the source patient ID stayed the same, which points at a data entry problem in the source rather than mixed-up patients.

The `check-anon-output.py` script in this repository re-checks a finished output folder from the outside. It is a weaker check than the one built into the app, because by then the source patient IDs are gone, but it is useful for verifying an export that was produced by an older version of DicomAnon.

## Installation
Downloads for both Windows and macOS are attached to each release on the [Releases](https://github.com/rmit-medical-radiations/DicomAnon/releases) page. Open the most recent release and download the file for your platform.

### Windows
Download `DicomAnon.exe` and move it to a convenient place, alongside your other utility applications. There is no installer - the `.exe` runs as-is.

Windows may show a "Windows protected your PC" warning the first time you run it, because the application is not code-signed. Click `More info`, then `Run anyway`.

### macOS
Download `DicomAnon-macOS.zip`, unzip it, and drag `DicomAnon.app` to your `Applications` folder.

The application is not signed or notarised, so macOS will refuse to open it the first time with a message saying it is damaged or cannot be checked for malicious software. To get past this, right-click (or Control-click) `DicomAnon.app` and choose `Open` from the menu, then click `Open` in the dialog that appears. You only need to do this once.

Note that the macOS build is for Apple Silicon Macs (M1 and later). It will not run on older Intel Macs.

## Usage
1. Start the application and select the parent folder of the patient folders containing the DICOM files to be anonymised (i.e. the `source` folder)
2. Select the destination folder that will contain the anonymised DICOM files (i.e. the `destination` folder). Create a new destination folder if you wish.
3. Select the `ID lookup file` - the Excel file that tells DicomAnon which anonymised ID to give each patient. See [The ID lookup file](#the-id-lookup-file) below for how to prepare it.
4. Press the `Anonymise!` button.
5. Wait for the processing to complete. The progress bar provides a visual clue about how far along it is.
6. On completion, an Excel spreadsheet with the mapping from the real patient ID to the anonymised patient ID will be saved in your home folder. DicomAnon displays the full path in a dialog when it finishes.

A source folder, a destination folder and an ID lookup file must all be selected before the `Anonymise!` button will do anything.

## The ID lookup file
DicomAnon does not invent the anonymised IDs; you supply them in an Excel file (`.xlsx` or `.xls`) that you select before anonymising.

The file needs two columns, with a header row:

| Patient ID | Anonymised ID |
| ---------- | ------------- |
| 1234       | Brain-0001    |
| 5678       | Brain-0002    |

* **The first column** holds the real patient ID - the number at the start of each patient folder name. For a folder named `1234_SmithJohn`, the ID is `1234`.
* **The second column** holds the anonymised ID you want to use for that patient. You choose it; DicomAnon uses it verbatim and adds nothing to it. The same value becomes the patient's folder name in the destination folder **and** the value of their `PatientName` and `PatientID` tags.

`Brain-0001` above is only the convention this project happens to use, not something DicomAnon requires or supplies. Whatever you write is what appears in the files, so pick the convention you want before the first run: an anonymised ID cannot be changed afterwards, as described below.

The column *names* do not matter - DicomAnon reads the first and second columns by position, so anything in a third or later column is ignored.

Any patient folder whose ID is not listed in the lookup file is skipped, and DicomAnon lists those patients in a warning dialog when it finishes. If a run processes fewer patients than you expected, that dialog is the first place to look.

### The lookup file is checked before anything is written
This file decides which patient goes into which folder, so a mistake in it is the most damaging kind. DicomAnon checks the whole file first and refuses to start if anything is wrong, listing every problem at once so you can fix them in one pass. It rejects:

* the same anonymised ID given to two different patients, which would put two people in one folder under one identity;
* the same patient ID listed twice, which previously kept whichever row came last, silently;
* a row missing either ID;
* a patient ID that is not a number, since it could never match a `<patientID>_<name>` folder;
* an anonymised ID that will not work as a folder name, including `/` or `\`, a name reserved by Windows such as `CON`, or a trailing space or dot.

It also refuses to start if two source folders have the same patient ID, for example `0123_SmithJohn` and `123_JonesMary`, because both would be written into the same output folder. Note that Excel drops leading zeros from a number, so a padded ID cannot be represented in the lookup file at all.

**A patient's folder assignment is permanent.** Once a patient has been anonymised into a folder, DicomAnon will not accept a lookup file that moves them somewhere else, or that gives their folder to somebody else. The already-written folder cannot be unwritten, so honouring the change would split one patient across two identities with nothing connecting them. If you need to change an assignment, ask before editing anything.

## Where to find the ID mapping spreadsheet
The spreadsheet is always called `dicom-anon-mapping.xlsx` and is always saved in your **home folder** - not in the destination folder you chose for the anonymised DICOM files, and not inside Documents. When processing finishes, DicomAnon shows the full path in a dialog; you can select the path with the mouse and copy it.

### Windows
The file is saved to `C:\Users\<your-username>\dicom-anon-mapping.xlsx`, for example `C:\Users\jsmith\dicom-anon-mapping.xlsx`.

To open it:
1. Press <kbd>Windows</kbd> + <kbd>R</kbd> to open the Run box.
2. Type `%USERPROFILE%` and press <kbd>Enter</kbd>.
3. File Explorer opens your user folder. Double-click `dicom-anon-mapping.xlsx` to open it in Excel.

Alternatively, click in the File Explorer address bar, type `%USERPROFILE%\dicom-anon-mapping.xlsx` and press <kbd>Enter</kbd> to open the file directly.

If you cannot see the file, check that you are looking at `C:\Users\<your-username>\` itself rather than `C:\Users\<your-username>\Documents\`. Note that some OneDrive configurations redirect your Documents and Desktop folders, but the mapping spreadsheet is saved to the local user folder regardless.

### macOS
The file is saved to `/Users/<your-username>/dicom-anon-mapping.xlsx`, for example `/Users/jsmith/dicom-anon-mapping.xlsx`.

To open it:
1. In Finder, choose **Go > Home** from the menu bar, or press <kbd>Shift</kbd> + <kbd>Command</kbd> + <kbd>H</kbd>.
2. Double-click `dicom-anon-mapping.xlsx` to open it in Excel.

Alternatively, choose **Go > Go to Folder** (<kbd>Shift</kbd> + <kbd>Command</kbd> + <kbd>G</kbd>), type `~/dicom-anon-mapping.xlsx` and press <kbd>Enter</kbd>.

## Never edit the mapping spreadsheet by hand
The spreadsheet is not a report. DicomAnon reads it as well as writes it, and it opens on a sheet saying so.

As well as the patient IDs, it records the **date offset** used for each patient. That offset is how the same patient's studies keep their true spacing when you add more of them later. Change a row by hand and you can:

* send a patient's new studies into a different folder from their earlier ones, splitting one person into two;
* shift a patient's new studies by a different amount from their old ones, so the intervals between their sessions become wrong;
* make it impossible to reproduce or check what was done, because the offsets exist nowhere else.

None of that is detectable afterwards from the anonymised files alone.

DicomAnon keeps the previous version as `dicom-anon-mapping.xlsx.bak` each time it saves. If you think something is wrong with the file, do not correct it: ask first. An assignment that has already been used to write files cannot be changed after the fact.

## Keep the mapping spreadsheet safe
The mapping spreadsheet is the only record linking the real patient IDs to the anonymised ones, and the date offsets it holds are part of that key: with them, every shifted date can be turned back into the real one. Anyone with both the anonymised DICOM files and this spreadsheet can re-identify the patients, so store it according to your institution's requirements for identifiable data - not alongside the anonymised files you intend to share, and never copied to whoever receives those files.
