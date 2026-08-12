import sys
import glob
import os
import shutil
from PyQt6.QtWidgets import QWidget, QPushButton, QProgressBar, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QApplication, QFileDialog, QLabel, QLineEdit, QMessageBox, QSizePolicy
from PyQt6.QtCore import Qt, QT_VERSION_STR, PYQT_VERSION_STR
from pydicom import dcmread
import pandas as pd
from os.path import expanduser
from datetime import datetime
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from pydicom.multival import MultiValue
from anon_checks import (IDENTIFYING_KEYWORDS, TOOL_VERSION, RunVerifier,
                         VerificationError, check_assignments, check_lookup,
                         load_patient_state, new_offsets, new_patient_state,
                         recorded_owners, save_patient_state, shift_dates,
                         snapshot_source, stale_files, state_dir_for,
                         unrecorded_folders, validate_keywords, verify_file)


StyleSheet = '''
#BlueProgressBar {
    background-color: #E0E0E0;
    border: 1px solid #BDBDBD;
    border-radius: 4px;
    text-align: center;
    height: 18px;
}
#BlueProgressBar::chunk {
    background-color: #2196F3;
    border-radius: 3px;
}
'''


# IDENTIFYING_KEYWORDS now lives in anon_checks.py, imported above, so that the
# anonymiser and the checks that verify it can never disagree about the list.

class DicomAnonWidget(QWidget):
    def __init__(self):
        super(DicomAnonWidget, self).__init__()
        self.setWindowTitle('DICOM Anonymiser')

        self.source_dir = ""
        self.destination_dir = ""
        self.lookup_file = ""
        self.verifier = RunVerifier()
        self.mapping_file = '{}dicom-anon-mapping.xlsx'.format(expanduser('~') + os.sep)
        # where per-destination state lives; an attribute so tests can redirect it
        self.state_home = expanduser('~')

        BROWSE_WIDTH = 100

        # --- input group ---
        self.source_button = QPushButton('Browse…')
        self.source_button.setFixedWidth(BROWSE_WIDTH)
        self.source_button.clicked.connect(self.source_button_clicked)
        self.source_field = QLineEdit()
        self.source_field.setReadOnly(True)
        self.source_field.setPlaceholderText('No folder selected')

        self.destination_button = QPushButton('Browse…')
        self.destination_button.setFixedWidth(BROWSE_WIDTH)
        self.destination_button.clicked.connect(self.destination_button_clicked)
        self.destination_field = QLineEdit()
        self.destination_field.setReadOnly(True)
        self.destination_field.setPlaceholderText('No folder selected')

        self.lookup_button = QPushButton('Browse…')
        self.lookup_button.setFixedWidth(BROWSE_WIDTH)
        self.lookup_button.clicked.connect(self.lookup_button_clicked)
        self.lookup_field = QLineEdit()
        self.lookup_field.setReadOnly(True)
        self.lookup_field.setPlaceholderText('No file selected')

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel('Source folder'),   0, 0)
        grid.addWidget(self.source_field,         0, 1)
        grid.addWidget(self.source_button,        0, 2)
        grid.addWidget(QLabel('Output folder'),   1, 0)
        grid.addWidget(self.destination_field,    1, 1)
        grid.addWidget(self.destination_button,   1, 2)
        grid.addWidget(QLabel('ID lookup file'),  2, 0)
        grid.addWidget(self.lookup_field,         2, 1)
        grid.addWidget(self.lookup_button,        2, 2)

        group = QGroupBox('Folders && Files')
        group.setLayout(grid)

        # --- anonymise button ---
        self.anon_button = QPushButton('Anonymise!')
        self.anon_button.setFixedWidth(160)
        self.anon_button.clicked.connect(self.anon_button_clicked)

        anon_hbox = QHBoxLayout()
        anon_hbox.addStretch()
        anon_hbox.addWidget(self.anon_button)
        anon_hbox.addStretch()

        # --- progress bar ---
        self.pbar = QProgressBar(self, minimum=0, maximum=100, textVisible=True, objectName="BlueProgressBar")
        self.pbar.setValue(0)
        self.pbar.setVisible(True)

        # --- status label ---
        self.status_label = QLabel('')
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- main layout ---
        self.setMinimumWidth(640)
        self.vbox = QVBoxLayout()
        self.vbox.setSpacing(12)
        self.vbox.setContentsMargins(16, 16, 16, 16)
        self.vbox.addWidget(group)
        self.vbox.addLayout(anon_hbox)
        self.vbox.addWidget(self.pbar)
        self.vbox.addWidget(self.status_label)
        self.vbox.addStretch()
        self.setLayout(self.vbox)
        self.show()
        self.activateWindow()
        self.raise_()

    def _anonymise_birthdate(self, ds: Dataset) -> None:
        """Reduce PatientBirthDate to 1 January of its year.

        Runs AFTER shift_dates, so the year is the shifted one, not the real one. That
        ordering is what lets PatientAge stay in the file: age is the gap between birth
        date and study date, and shifting both by the same offset leaves that gap
        correct while making the year itself meaningless.

        Keeping the real year and keeping PatientAge, which is what the tool used to do,
        would have handed over the offset: age minus (study year - birth year) is the
        shift in years, and knowing that undoes it everywhere.
        """
        b = getattr(ds, "PatientBirthDate", None)
        if not (b and len(b) == 8):
            return
        year = b[:4]
        ds.PatientBirthDate = f"{year}0101"

    def _map_uid(self, old_uid: str, uid_map: dict) -> str:
        """Return a pseudonymised UID, creating a new one if needed."""
        if not old_uid:
            return old_uid
        if old_uid not in uid_map:
            uid_map[old_uid] = generate_uid()
        return uid_map[old_uid]

    def _anonymise_uids_recursive(self, ds: Dataset, uid_map: dict) -> None:
        """
        Recursively remap all UIDs in the dataset (and sequences),
        except SOPClassUIDs (those are class identifiers, not object IDs).
        """
        for elem in ds.iterall():
            if elem.VR != "UI":
                continue

            keyword = elem.keyword or ""
            # Don't touch SOP Class UIDs
            if keyword.endswith("SOPClassUID"):
                continue

            val = elem.value
            if isinstance(val, MultiValue):
                elem.value = [ self._map_uid(str(v), uid_map) for v in val ]
            else:
                elem.value = self._map_uid(str(val), uid_map)

    def _get_study_label(self, ds: Dataset, study_label_map: dict) -> str:
        """
        Give each original StudyInstanceUID a stable pseudonym like STUDY_0001
        for StudyID. StudyDescription is left unchanged.
        """
        study_uid = getattr(ds, "StudyInstanceUID", None)
        if not study_uid:
            return "STUDY"
        if study_uid not in study_label_map:
            idx = len(study_label_map) + 1
            study_label_map[study_uid] = f"STUDY_{idx:04d}"
        return study_label_map[study_uid]

    def anonymise_dicom(
        self,
        ds: Dataset,
        anon_name: str,
        uid_map: dict | None = None,
        study_label_map: dict | None = None,
        offsets: tuple | None = None,
    ) -> Dataset:
        """
        Anonymise a DICOM dataset in place for hospital→research sharing.

        - PatientName, PatientID → anon_name
        - Every DA, TM and DT element shifted by this patient's offset
        - PatientBirthDate reduced to 1 January of its (shifted) year
        - Dates embedded in free text shifted to match
        - Private tags removed
        - Other identifying attributes blanked
        - UIDs pseudonymised consistently using uid_map
        - StudyID pseudonymised using study_label_map
        - StudyDescription is NOT changed, apart from any date inside it
        """
        if uid_map is None:
            uid_map = {}
        if study_label_map is None:
            study_label_map = {}
        if offsets is None:
            offsets = new_offsets()

        # dates: shift the whole timeline, then blur the birth date within it. Shifting
        # StudyDate alone was worse than useless, because the unshifted SeriesDate
        # beside it gave the offset away (defect 1).
        offset_days, offset_seconds = offsets
        shift_dates(ds, offset_days, offset_seconds)
        self._anonymise_birthdate(ds)

        # remove private tags
        ds.remove_private_tags()

        # pseudonymised PatientName / PatientID
        ds.PatientName = anon_name
        ds.PatientID = anon_name

        # pseudonymised StudyID only (for grouping); StudyDescription left as-is
        study_label = self._get_study_label(ds, study_label_map)
        ds.StudyID = study_label
        # ds.StudyDescription is intentionally NOT modified

        # blank other identifying tags
        for kw in IDENTIFYING_KEYWORDS:
            if kw in ds:
                elem = ds.data_element(kw)
                if elem.VR == "SQ":
                    elem.value = []
                else:
                    elem.value = ""

        # pseudonymise UIDs (dataset and nested sequences)
        self._anonymise_uids_recursive(ds, uid_map)

        # file meta UIDs (keep SOP Class, map instance UID)
        if hasattr(ds, "file_meta") and ds.file_meta:
            fm = ds.file_meta
            if "MediaStorageSOPInstanceUID" in fm:
                fm["MediaStorageSOPInstanceUID"].value = self._map_uid(
                    str(fm["MediaStorageSOPInstanceUID"].value), uid_map
                )

        return ds

    @staticmethod
    def _cell_to_str(value):
        """Excel cell to the string the rest of the tool compares against.

        pandas types a column of numbers as float, so a plain .astype(str) turns 1234
        into '1234.0', which then matches no patient folder and silently skips the
        patient. One blank cell anywhere in the column is enough to trigger it.
        """
        if value is None:
            return ''
        if isinstance(value, float):
            if pd.isna(value):
                return ''
            if value.is_integer():
                return str(int(value))
        return str(value).strip()

    def _load_lookup(self, lookup_file):
        """Load and check the ID lookup Excel file.

        Returns {internal_id_str: anon_id_str}. Raises VerificationError listing every
        problem, rather than the first, so a bad file can be fixed in one pass.
        """
        df = pd.read_excel(lookup_file)
        if len(df.columns) < 2:
            raise VerificationError(
                'The lookup file needs at least two columns: the real patient ID, then '
                'the anonymised ID.')
        col_internal = df.columns[0]
        col_anon = df.columns[1]
        pairs = [(self._cell_to_str(a), self._cell_to_str(b))
                 for a, b in zip(df[col_internal], df[col_anon])]
        problems = check_lookup(pairs)
        if problems:
            raise VerificationError(
                'The ID lookup file has problems that would corrupt the output:\n\n{}'
                .format('\n'.join('  - ' + p for p in problems)))
        return {a: b for a, b in pairs if a and b}

    MAPPING_SHEET = 'mapping'
    WARNING_SHEET = 'DO NOT EDIT'
    WARNING_LINES = [
        'DO NOT EDIT THIS FILE BY HAND.',
        '',
        'DicomAnon reads and writes it. It is not a report.',
        '',
        'It records which anonymised folder each real patient was given, and the date '
        'offset used to shift that patient\'s dates. Changing either by hand will split '
        'one patient across two folders, or shift a patient\'s new studies by a '
        'different amount from their earlier ones, and nothing will warn you.',
        '',
        'Editing the file can also silently break anonymisation for that patient.',
        '',
        'This file is the only record linking the real and anonymised IDs, and the date '
        'offsets are part of that key. Keep it safe, keep it away from the anonymised '
        'DICOM files, and never copy it to anyone you send those files to.',
        '',
        'If something looks wrong here, do not correct it. Ask first: an assignment that '
        'has already been used to write files cannot be changed after the fact.',
    ]

    def _read_mapping(self, mapping_file):
        """Load the ID mapping file, tolerating one written before the warning sheet."""
        if not os.path.isfile(mapping_file):
            return None
        try:
            return pd.read_excel(mapping_file, sheet_name=self.MAPPING_SHEET, index_col=0)
        except ValueError:
            # written by a version that had a single unnamed sheet
            return pd.read_excel(mapping_file, index_col=0)

    def _save_mapping(self, mapping_df, mapping_file):
        """Write the mapping with the warning sheet first, so opening it shows that.

        Written to a temporary file and moved into place, keeping the previous version
        as .bak. This file is now saved after every patient rather than once per run, and
        it is the only record linking real and anonymised IDs: a crash partway through
        writing it would destroy something that cannot be reconstructed from anything
        else, since the date offsets exist nowhere but here.
        """
        if mapping_df is None:
            return
        tmp = mapping_file + '.tmp.xlsx'  # pandas picks the engine from the extension
        with pd.ExcelWriter(tmp, engine='openpyxl') as writer:
            pd.DataFrame({'READ THIS FIRST': self.WARNING_LINES}).to_excel(
                writer, sheet_name=self.WARNING_SHEET, index=False)
            mapping_df.to_excel(writer, sheet_name=self.MAPPING_SHEET)
        if os.path.isfile(mapping_file):
            try:
                shutil.copyfile(mapping_file, mapping_file + '.bak')
            except OSError:
                pass  # a missing backup must not stop the run from recording the mapping
        os.replace(tmp, mapping_file)

    def _recorded_assignments(self, mapping_df):
        """{hospital id: anon folder} already committed to by an earlier run."""
        if mapping_df is None or 'anon_patient_dir_name' not in mapping_df:
            return {}
        return {str(row.patient_id): str(row.anon_patient_dir_name)
                for row in mapping_df.itertuples()}

    def _patient_offsets(self, mapping_df, patient_id):
        """This patient's stored date offsets, or a fresh pair if they are new.

        Reused across runs on purpose. The oncologist adds studies to a patient over
        weeks, and a new offset each run would leave that patient's own timeline
        inconsistent with itself, which is the thing the shift is supposed to preserve.
        """
        if mapping_df is not None and 'date_offset_days' in mapping_df:
            rows = mapping_df.loc[mapping_df['patient_id'] == patient_id]
            if len(rows):
                days = rows.iloc[0]['date_offset_days']
                seconds = rows.iloc[0].get('time_offset_seconds', 0)
                if pd.notna(days):
                    return int(days), int(seconds if pd.notna(seconds) else 0)
        return new_offsets()

    def _is_new_patient(self, patient_id, mapping_df):
        if mapping_df is None:
            return True
        return len(mapping_df[mapping_df.patient_id == patient_id]) == 0

    def _parse_patient_id(self, patient_dir):
        parts = patient_dir.split('_')
        if len(parts) < 2:
            raise ValueError(f"Expected '<patientID>_<name>' format: '{patient_dir}'")

        patient_str = parts[0]
        if not patient_str.isdigit():
            raise ValueError(f"Patient ID is not numeric: '{patient_str}'")

        return int(patient_str)

    def _display_error(self, message):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(message)
        msg.setWindowTitle("Error")
        msg.exec()

    def _verification_report_path(self):
        """Beside the mapping file, never inside the destination.

        The report names source patient IDs, so it is re-identifying and must not end
        up in the folder that gets copied to the university.
        """
        return '{}dicom-anon-verification.txt'.format(expanduser('~') + os.sep)

    def _report_verification_warnings(self):
        """Findings that do not justify stopping a finished run, but must be seen.

        A folder whose birth years or sexes disagree while its source PatientID stayed
        constant is a source data problem, not contamination, so the run is allowed to
        finish. It still has to be reported: it is the same signal the university end
        has to rely on, and if it fires while the source ID check stayed quiet, one of
        the two is wrong and that is worth knowing.
        """
        dodgy = list(validate_keywords())
        problems = self.verifier.problems()
        if not problems and not dodgy:
            return
        lines = []
        if problems:
            lines.append('Checks that did not pass:')
            lines.extend('  - ' + p for p in problems)
        if dodgy:
            lines.append('')
            lines.append('These entries are not DICOM keywords, so they blanked nothing:')
            lines.extend('  - ' + kw for kw in dodgy)
        detail = '\n'.join(lines)
        report_path = self._verification_report_path()
        try:
            with open(report_path, 'w') as f:
                f.write('DicomAnon verification warnings at {}\n\n{}\n'.format(
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'), detail))
            saved = os.path.normpath(report_path)
        except Exception:
            saved = None
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle('Check the Output Before Sharing It')
        msg.setText('Processing finished, but some checks did not pass.')
        msg.setInformativeText('{}{}'.format(
            detail,
            '\n\nSaved to:\n{}'.format(saved) if saved else ''))
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg.exec()

    def _report_verification_failure(self, detail):
        """Stop the run and tell the operator something they can forward verbatim.

        The person running this did not write it and cannot read a traceback, so the
        dialog has to name the folder and the problem in words, and the report file
        has to be somewhere they can find and attach.
        """
        report_path = self._verification_report_path()
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        body = 'DicomAnon verification failure at {}\n\n{}\n'.format(stamp, detail)
        try:
            with open(report_path, 'w') as f:
                f.write(body)
            saved = os.path.normpath(report_path)
        except Exception:
            saved = None
        self.status_label.setText('Stopped: verification failed.')
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle('Anonymisation Stopped')
        msg.setText('Anonymisation was stopped because a check failed.')
        msg.setInformativeText(
            '{}\n\nThe files written before this point are still in the output folder, '
            'but the output is incomplete and should not be copied anywhere until this '
            'is resolved.{}'.format(
                detail,
                '\n\nThis message was also saved to:\n{}'.format(saved) if saved else ''))
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg.exec()

    # process all DICOMs under the selected top-level folder containing patient folders
    def process_folder(self, source_base_dir, destination_base_dir, mapping_df, lookup_dict):
        # update the status bar
        self.status_label.setText('Counting files.')
        # process GUI events to reflect the update value
        QApplication.processEvents()
        # count the DICOM files under the selected directory
        dicom_files_count = len(glob.glob('{}/**/*.dcm'.format(source_base_dir), recursive=True))
        print('{} files'.format(dicom_files_count))
        dicom_files_processed = 0
        # update the status bar
        self.status_label.setText('Found {} files.'.format(dicom_files_count))
        # process GUI events to reflect the update value
        QApplication.processEvents()
        # Per-patient state, kept outside the destination because it holds source UIDs
        # and hospital IDs. uid_map and study_label_map used to be created here, empty,
        # once per run and shared by every patient: defects 2 and 3 in one line.
        state_dir = state_dir_for(destination_base_dir, self.state_home)
        orphans = unrecorded_folders(destination_base_dir, state_dir)
        if orphans:
            raise VerificationError(
                'The output folder already contains anonymised data that this tool has '
                'no record of, in:\n\n{}\n\nThat data was written by an older version, '
                'before the current checks existed. Its UID maps and date offsets cannot '
                'be reconstructed, so new files cannot safely be added beside it.\n\n'
                'Choose a new, empty output folder and process the source into that.'
                .format('\n'.join('  - ' + name for name in orphans)))
        # seed from previous runs, so a folder filled entirely from the wrong source
        # patient is caught even though nothing conflicts within this run
        for source_id, folder in recorded_owners(state_dir).items():
            self.verifier.record(source_id, folder)
        not_found_patients = []
        # find the patient directories
        patient_dirs_l = [ name for name in os.listdir(source_base_dir) if os.path.isdir(os.path.join(source_base_dir, name)) ]
        # Two source folders that parse to the same patient ID would be written into one
        # anon folder. Excel drops leading zeros, so the lookup file cannot even express
        # the difference between 0123_X and 123_Y; the collision has to be caught here.
        by_parsed_id = {}
        for name in patient_dirs_l:
            try:
                by_parsed_id.setdefault(self._parse_patient_id(name), []).append(name)
            except Exception:
                continue  # reported per patient in the loop below
        collisions = {pid: names for pid, names in by_parsed_id.items() if len(names) > 1}
        if collisions:
            raise VerificationError(
                'Different source folders have the same patient ID, so they would be '
                'written into the same anonymised folder:\n\n{}'.format('\n'.join(
                    '  - patient ID {} comes from: {}'.format(pid, ', '.join(sorted(names)))
                    for pid, names in sorted(collisions.items()))))
        if len(patient_dirs_l) == 0:
            self._display_error(f'There are no patient directories under {source_base_dir}')
        else:
            for patient_dir_idx,patient_dir in enumerate(patient_dirs_l):
                valid_file_count = 0
                invalid_file_count = 0
                try:
                    patient_id = self._parse_patient_id(patient_dir)
                except Exception as e:
                    self._display_error(f"Error parsing patient ID: {e}")
                    break
                patient_id_str = str(patient_id)
                if patient_id_str not in lookup_dict:
                    print('patient ID {} not found in lookup file - skipping'.format(patient_id))
                    not_found_patients.append(patient_id_str)
                    continue
                anon_patient_folder_name = lookup_dict[patient_id_str]
                new_patient = self._is_new_patient(patient_id, mapping_df)
                # reused for a patient already in the mapping, so studies added later
                # keep their true spacing from the ones already anonymised
                offsets = self._patient_offsets(mapping_df, patient_id)
                anon_patient_dir = destination_base_dir + os.sep + anon_patient_folder_name
                patient_full_dir = source_base_dir + os.sep + patient_dir
                dicom_files = glob.glob('{}/**/*.dcm'.format(patient_full_dir), recursive=True)
                # this patient's own maps, reloaded from the last run. A fresh map would
                # give the same source UID a new pseudonym (defect 2), and a shared one
                # would link patients through a UID they have in common (defect 3).
                state = (load_patient_state(state_dir, anon_patient_folder_name)
                         or new_patient_state(anon_patient_folder_name, patient_id))
                uid_map = state['uid_map']
                study_label_map = state['study_label_map']
                planned = [os.path.relpath(f, patient_full_dir) for f in dicom_files]
                stranded = stale_files(state, planned)
                if stranded:
                    raise VerificationError(
                        'Patient {} was last anonymised by version {}, and this is '
                        'version {}. Everything already written for them has to be '
                        'produced again, but the source no longer contains {} of those '
                        'files:\n\n{}\n\nWriting new files beside them would leave one '
                        'folder holding two different versions of the anonymisation. '
                        'Restore the missing source data, or process this patient into '
                        'a new, empty output folder.'.format(
                            patient_id, state.get('tool_version', 'an older version'),
                            TOOL_VERSION, len(stranded),
                            '\n'.join('  - ' + p for p in stranded[:10])
                            + ('\n  ... and {} more'.format(len(stranded) - 10)
                               if len(stranded) > 10 else '')))
                # update the status bar
                self.status_label.setText('Processing patient ID {}'.format(patient_id))
                # process GUI events to reflect the update value
                QApplication.processEvents()
                for source_file in dicom_files:
                    rel_path = os.path.relpath(source_file, patient_full_dir)  # use the same relative path for source and target
                    anon_patient_file = anon_patient_dir + os.sep + rel_path   # add the relative path to the anon directory
                    # load and process the file
                    try:
                        ds = dcmread(source_file)
                        valid_file_count += 1
                        # process GUI events
                        QApplication.processEvents()
                    except Exception as e:
                        print(e)
                        invalid_file_count += 1
                    else:
                        # capture the source identifiers before anonymise_dicom destroys
                        # them; nothing downstream of here can recover them
                        source = snapshot_source(ds)
                        ds = self.anonymise_dicom(ds=ds, anon_name=anon_patient_folder_name, uid_map=uid_map, study_label_map=study_label_map, offsets=offsets)
                        problems = verify_file(ds, source, anon_patient_folder_name)
                        if problems:
                            raise VerificationError(
                                'Anonymisation failed its own checks and the run was '
                                'stopped before this file was written.\n\n'
                                'Source file:\n{}\n\nProblems:\n{}'.format(
                                    source_file, '\n'.join('  - ' + p for p in problems)))
                        # the source PatientID is what makes this a real contamination
                        # check rather than the birth year proxy the university is stuck with
                        contamination = self.verifier.record(
                            source['patient_id'], anon_patient_folder_name,
                            source['birth_year'], source['sex'])
                        if contamination:
                            raise VerificationError(
                                'Patient data would be mixed up, and the run was stopped '
                                'before this file was written.\n\n'
                                'Source file:\n{}\n\nProblem:\n  - {}'.format(
                                    source_file, contamination))
                        # create the anon folder if it doesn't exist
                        target_dir = os.path.dirname(anon_patient_file)  # create the missing directories all the way to the DICOM file
                        if not os.path.exists(target_dir):
                            os.makedirs(target_dir)
                        ds.save_as(anon_patient_file)
                        # record what was written and at which version, so a later run
                        # can tell current output from output it must not write beside
                        state['files'][rel_path] = TOOL_VERSION
                        if source['patient_id'] and source['patient_id'] not in state['source_patient_ids']:
                            state['source_patient_ids'].append(source['patient_id'])
                    # update count of files processed
                    dicom_files_processed += 1
                    # update the progress bar
                    if dicom_files_count > 0:
                        proportion_completed = int((dicom_files_processed)/dicom_files_count*100)
                        self.pbar.setValue(proportion_completed)
                    # process GUI events to reflect the update value
                    QApplication.processEvents()
                # count the total sessions anonymised for this patient
                anon_patient_sessions_l = [ name for name in os.listdir(anon_patient_dir) if os.path.isdir(os.path.join(anon_patient_dir, name)) ]
                session_count = len(anon_patient_sessions_l)
                # update the status bar
                self.status_label.setText('Updating the patient ID mapping.')
                # process GUI events to reflect the update value
                QApplication.processEvents()
                # add or update the mapping
                date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if new_patient:
                    row = pd.Series({'patient_id':patient_id, 'anon_patient_dir_name':anon_patient_folder_name, 'total_session_count':session_count, 'valid_file_count':valid_file_count, 'invalid_file_count':invalid_file_count, 'last_updated':date_str, 'date_offset_days':offsets[0], 'time_offset_seconds':offsets[1]})
                    mapping_df = pd.concat([mapping_df, pd.DataFrame([row], columns=row.index)]).reset_index(drop=True)
                else:
                    row_index = mapping_df.loc[mapping_df['patient_id'] == patient_id].index[0]
                    mapping_df.loc[row_index, 'total_session_count'] = session_count
                    mapping_df.loc[row_index, 'last_updated'] = date_str
                    mapping_df.loc[row_index, 'valid_file_count'] += valid_file_count
                    mapping_df.loc[row_index, 'invalid_file_count'] += invalid_file_count
                    mapping_df.loc[row_index, 'date_offset_days'] = offsets[0]
                    mapping_df.loc[row_index, 'time_offset_seconds'] = offsets[1]
                # save as each patient finishes, not just at the end of the run. The
                # offsets are only reusable if they survive, and a run that stops on a
                # failed check must not lose the offsets it has already written files with.
                self._save_mapping(mapping_df, self.mapping_file)
                # the UID map is only worth having if it outlives the run that built it
                state['tool_version'] = TOOL_VERSION
                save_patient_state(state_dir, anon_patient_folder_name, state)

        return mapping_df, not_found_patients

    def anon_button_clicked(self):
        # get the file names under the directory selected
        if self.source_dir == "":
            self._display_error("Please select a source folder.")
            return
        if self.lookup_file == "":
            self._display_error("Please select an ID lookup file.")
            return
        # update the progress bar
        self.pbar.setValue(0)
        self.pbar.setVisible(True)
        QApplication.processEvents()
        # disable buttons
        self.source_button.setEnabled(False)
        self.destination_button.setEnabled(False)
        self.lookup_button.setEnabled(False)
        self.anon_button.setEnabled(False)
        # set up the mapping file
        mapping_file = self.mapping_file
        # load and check the lookup file, then check it against what earlier runs
        # already committed to. Rule 1: an assignment, once used, is permanent.
        try:
            mapping_df = self._read_mapping(mapping_file)
            lookup_dict = self._load_lookup(self.lookup_file)
            clashes = check_assignments(lookup_dict, self._recorded_assignments(mapping_df))
            if clashes:
                raise VerificationError(
                    'The ID lookup file disagrees with folders that have already been '
                    'written:\n\n{}\n\nThe earlier assignment is the one that counts. '
                    'Correct the lookup file to match it, and do not edit the ID mapping '
                    'file.'.format('\n'.join('  - ' + c for c in clashes)))
        except VerificationError as e:
            self._report_verification_failure(str(e))
            self.source_button.setEnabled(True)
            self.destination_button.setEnabled(True)
            self.lookup_button.setEnabled(True)
            self.anon_button.setEnabled(True)
            return
        except Exception as e:
            self._display_error(f"Failed to load lookup file: {e}")
            self.source_button.setEnabled(True)
            self.destination_button.setEnabled(True)
            self.lookup_button.setEnabled(True)
            self.anon_button.setEnabled(True)
            return
        # process UI events
        QApplication.processEvents()
        # verify as we go, and stop the run rather than write suspect data (defect 5)
        self.verifier = RunVerifier()
        try:
            mapping_df, not_found_patients = self.process_folder(self.source_dir, self.destination_dir, mapping_df, lookup_dict)
        except VerificationError as e:
            self._report_verification_failure(str(e))
            self.source_button.setEnabled(True)
            self.destination_button.setEnabled(True)
            self.lookup_button.setEnabled(True)
            self.anon_button.setEnabled(True)
            return
        # process UI events
        QApplication.processEvents()
        # update the status bar
        self.status_label.setText('Saving the ID mapping file.')
        # update the mapping file
        mapping_saved = mapping_df is not None
        if mapping_saved:
            self._save_mapping(mapping_df, mapping_file)
        # process UI events
        QApplication.processEvents()
        # enable buttons
        self.source_button.setEnabled(True)
        self.destination_button.setEnabled(True)
        self.lookup_button.setEnabled(True)
        self.anon_button.setEnabled(True)
        # update the status bar
        self.status_label.setText('Finished processing.')
        # report the checks that warn rather than stop the run
        self._report_verification_warnings()
        # report patients not found in the lookup
        if not_found_patients:
            patient_list = '\n'.join(f'  - {pid}' for pid in not_found_patients)
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Patients Not Processed")
            msg.setText(
                f"The following {len(not_found_patients)} patient(s) were not found in the "
                f"lookup file and were not processed:\n\n{patient_list}"
            )
            msg.exec()
        # tell the user where the ID mapping file was saved
        if mapping_saved:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("Finished Processing")
            msg.setText("Finished processing.")
            msg.setInformativeText(
                "The spreadsheet mapping the real patient IDs to the anonymised patient IDs "
                f"has been saved here:\n\n{os.path.normpath(mapping_file)}\n\n"
                "Keep this file safe - it is the only record linking the real and anonymised IDs."
            )
            msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            msg.exec()

    def source_button_clicked(self):
        # update the progress bar
        self.pbar.setValue(0)
        # update the status bar
        self.status_label.setText('')

        self.source_dir = str(QFileDialog.getExistingDirectory(self, "Select Directory"))
        if self.source_dir != "":
            self.source_field.setText(self.source_dir)

    def destination_button_clicked(self):
        # update the progress bar
        self.pbar.setValue(0)
        # update the status bar
        self.status_label.setText('')

        self.destination_dir = str(QFileDialog.getExistingDirectory(self, "Select Directory"))
        if self.destination_dir != "":
            self.destination_field.setText(self.destination_dir)

    def lookup_button_clicked(self):
        # update the progress bar
        self.pbar.setValue(0)
        # update the status bar
        self.status_label.setText('')

        file_path, _ = QFileDialog.getOpenFileName(self, "Select ID Lookup File", "", "Excel Files (*.xlsx *.xls)")
        if file_path:
            self.lookup_file = file_path
            self.lookup_field.setText(file_path)

def self_test(report_path=None):
    '''Verify the packaged app can actually start, without opening a window.

    Reaching this function already proves the Qt DLLs loaded, since the PyQt6
    imports at the top of this module run first. The remaining checks catch the
    mismatch that shipped in v0.4: PyQt6-Qt6 is only loosely constrained by
    PyQt6, so an unpinned install pairs new Qt libraries with old bindings and
    the app dies at startup on a missing symbol (macOS) or a missing DLL export
    (Windows, 'The specified procedure could not be found').

    Returns 0 on success, 1 on failure. Writes a report to report_path if given,
    because a windowed build has no console to print to.
    '''
    lines = []
    ok = True

    def record(message):
        lines.append(message)

    record(f'PyQt6 bindings: {PYQT_VERSION_STR}')
    record(f'Qt libraries:   {QT_VERSION_STR}')

    bindings_series = PYQT_VERSION_STR.split('.')[:2]
    qt_series = QT_VERSION_STR.split('.')[:2]
    if bindings_series != qt_series:
        record(f'FAIL: Qt {QT_VERSION_STR} does not match PyQt6 {PYQT_VERSION_STR} '
               '- pin PyQt6-Qt6 to the PyQt6 version in requirements.txt')
        ok = False
    else:
        record('OK: Qt libraries match the PyQt6 bindings')

    # Every entry in IDENTIFYING_KEYWORDS must be a real DICOM keyword, or it blanks
    # nothing and the tag ships in every file. Checked here because CI runs --self-test
    # on every build, so a typo fails the build rather than the next export (defect 7).
    dodgy = validate_keywords()
    if dodgy:
        record('FAIL: not DICOM keywords, so they blank nothing: {}'.format(
            ', '.join(dodgy)))
        ok = False
    else:
        record('OK: all {} identifying keywords are real DICOM tags'.format(
            len(IDENTIFYING_KEYWORDS)))

    # Build the real widget offscreen so the check covers QtWidgets and QtGui,
    # not just the QtCore import that fails first.
    try:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        app = QApplication(sys.argv[:1])
        app.setStyleSheet(StyleSheet)
        DicomAnonWidget()
        record('OK: main window constructed offscreen')
    except Exception as e:
        record(f'FAIL: could not construct the main window: {e!r}')
        ok = False

    record('SELF TEST PASSED' if ok else 'SELF TEST FAILED')
    report = '\n'.join(lines)

    if report_path:
        with open(report_path, 'w') as f:
            f.write(report + '\n')
    try:
        print(report)
    except Exception:
        pass  # a windowed build has no stdout to write to

    return 0 if ok else 1


if __name__ == "__main__":
    if '--self-test' in sys.argv:
        args = [a for a in sys.argv[1:] if a != '--self-test']
        sys.exit(self_test(args[0] if args else None))

    app = QApplication(sys.argv)
    app.setStyleSheet(StyleSheet)
    widget = DicomAnonWidget()
    widget.show()
    sys.exit(app.exec())
