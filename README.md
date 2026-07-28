# DicomAnon
This is a repository for a DICOM anonymiser, deftly named DicomAnon. Although there are many applications that will anonymise DICOM files, this one was written to do so in bulk. With DicomAnon, you can point to a parent folder containing many patient folders, which may contain many imaging sessions, which may contain images acquired with different modalities. Note that patient folders are assumed to adhere to a naming convention of `<patientID>_<patientName>`, where patientID is a number.

After telling DicomAnon where you want the anonymised files to be placed, it will preserve the folder structure and place anonymised DICOM files there. DicomAnon does not change the original files; it merely reads them, changes the value of DICOM tags that contain personal information about the patient, and writes the anonymised version to the designated destination folder.

<img width="712" alt="DicomAnon screen shot" src="https://github.com/RMIT-University-Medical-Radiations/DicomAnon/assets/1016303/742f9e86-d083-413f-9635-909e5964eb2e">

<!-- TODO: this screenshot predates the `ID lookup file` row and needs retaking. -->
> **Note:** the screenshot above is out of date - it does not show the `ID lookup file` row that now sits below the source and destination folders.

The DICOM files are anonymised by blanking the values of the following DICOM tags:

### Patient
* PatientName - replaced with `Brain-<anon_patient_ID>`
* PatientID - replaced with `Brain-<anon_patient_ID>`

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
* PhysiciansReadingStudy

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
* PatientAccountNumber
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


The tag `PatientBirthDate` is modified but the year is preserved. The `StudyDate` tag is shifted by a fixed number of days so that the time period between studies is preserved.

Further, it recursively remaps all UIDs in the dataset (and sequences), except SOPClassUIDs. The reason for doing this is so that even if the anonymised DICOMs are loaded back into the system at their originating institution, the patient could still not be identified.

On completion, DicomAnon will save a mapping of the true patient IDs to anonymised patient IDs as an Excel spreadsheet named `dicom-anon-mapping.xlsx` in your home folder. DicomAnon shows the full path in a dialog when it finishes - see [Where to find the ID mapping spreadsheet](#where-to-find-the-id-mapping-spreadsheet) below.

Note that adding new patient folders (and updates to existing patient folders) will not erase previous DICOM files for the same patient; the new anonymised DICOM files will be saved in the same structure alongside those previously processed. The new patient IDs will also be added to the Excel mapping spreadsheet.

## Installation
Unzip the downloaded file and move it to a convenient place, alongside your other utility applications.

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
| 1234       | 001           |
| 5678       | 002           |

* **The first column** holds the real patient ID - the number at the start of each patient folder name. For a folder named `1234_SmithJohn`, the ID is `1234`.
* **The second column** holds the anonymised ID you want to use for that patient. This value becomes the patient's folder name in the destination folder, and the patient's `PatientName` and `PatientID` tags are set to `Brain-<anonymised ID>`.

The column *names* do not matter - DicomAnon reads the first and second columns by position, so anything in a third or later column is ignored.

Any patient folder whose ID is not listed in the lookup file is skipped, and DicomAnon lists those patients in a warning dialog when it finishes. If a run processes fewer patients than you expected, that dialog is the first place to look.

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

## Keep the mapping spreadsheet safe
The mapping spreadsheet is the only record linking the real patient IDs to the anonymised ones. Anyone with both the anonymised DICOM files and this spreadsheet can re-identify the patients, so store it according to your institution's requirements for identifiable data - not alongside the anonymised files you intend to share.
