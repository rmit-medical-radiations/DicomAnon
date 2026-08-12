import sys
import glob
import os
from PyQt6.QtWidgets import QWidget, QPushButton, QProgressBar, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QApplication, QFileDialog, QLabel, QLineEdit, QMessageBox, QSizePolicy
from PyQt6.QtCore import Qt, QT_VERSION_STR, PYQT_VERSION_STR
from pydicom import dcmread
import pandas as pd
from os.path import expanduser
from datetime import datetime, timedelta
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from pydicom.multival import MultiValue
from anon_checks import (IDENTIFYING_KEYWORDS, RunVerifier, VerificationError,
                         snapshot_source, validate_keywords, verify_file)


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

    def _shift_study_date(self, ds: Dataset, offset_days: int) -> None:
        """
        Shift StudyDate by a fixed number of days.

        Using the same offset for all studies preserves the exact
        day differences between any two StudyDates.
        """
        s = getattr(ds, "StudyDate", None)
        if not (s and len(s) == 8):
            return
        try:
            dt = datetime.strptime(s, "%Y%m%d").date()
            dt_new = dt + timedelta(days=offset_days)
            ds.StudyDate = dt_new.strftime("%Y%m%d")
        except Exception:
            # If parsing fails, leave as-is
            pass

    def _anonymise_birthdate(self, ds: Dataset) -> None:
        """Replace PatientBirthDate but keep the year."""
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
    ) -> Dataset:
        """
        Anonymise a DICOM dataset in place for hospital→research sharing.

        - PatientName, PatientID → anon_name
        - PatientBirthDate → same year, set to YYYY0101
        - StudyDate → add 1 month
        - Private tags removed
        - Other identifying attributes blanked
        - UIDs pseudonymised consistently using uid_map
        - StudyID pseudonymised using study_label_map
        - StudyDescription is NOT changed
        """
        if uid_map is None:
            uid_map = {}
        if study_label_map is None:
            study_label_map = {}

        # dates
        self._anonymise_birthdate(ds)
        self._shift_study_date(ds, offset_days=30)

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

    def _load_lookup(self, lookup_file):
        """Load the ID lookup Excel file. Returns a dict {internal_id_str: anon_id_str}."""
        df = pd.read_excel(lookup_file)
        col_internal = df.columns[0]
        col_anon = df.columns[1]
        return dict(zip(df[col_internal].astype(str), df[col_anon].astype(str)))

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
        # initialise maps
        uid_map = {}
        study_label_map = {}
        not_found_patients = []
        # find the patient directories
        patient_dirs_l = [ name for name in os.listdir(source_base_dir) if os.path.isdir(os.path.join(source_base_dir, name)) ]
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
                anon_patient_dir = destination_base_dir + os.sep + anon_patient_folder_name
                patient_full_dir = source_base_dir + os.sep + patient_dir
                dicom_files = glob.glob('{}/**/*.dcm'.format(patient_full_dir), recursive=True)
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
                        ds = self.anonymise_dicom(ds=ds, anon_name=anon_patient_folder_name, uid_map=uid_map, study_label_map=study_label_map)
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
                    row = pd.Series({'patient_id':patient_id, 'anon_patient_dir_name':anon_patient_folder_name, 'total_session_count':session_count, 'valid_file_count':valid_file_count, 'invalid_file_count':invalid_file_count, 'last_updated':date_str})
                    mapping_df = pd.concat([mapping_df, pd.DataFrame([row], columns=row.index)]).reset_index(drop=True)
                else:
                    row_index = mapping_df.loc[mapping_df['patient_id'] == patient_id].index[0]
                    mapping_df.loc[row_index, 'total_session_count'] = session_count
                    mapping_df.loc[row_index, 'last_updated'] = date_str
                    mapping_df.loc[row_index, 'valid_file_count'] += valid_file_count
                    mapping_df.loc[row_index, 'invalid_file_count'] += invalid_file_count

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
        # load the lookup file
        try:
            lookup_dict = self._load_lookup(self.lookup_file)
        except Exception as e:
            self._display_error(f"Failed to load lookup file: {e}")
            self.source_button.setEnabled(True)
            self.destination_button.setEnabled(True)
            self.lookup_button.setEnabled(True)
            self.anon_button.setEnabled(True)
            return
        # set up the mapping file
        mapping_file = '{}dicom-anon-mapping.xlsx'.format(expanduser('~')+os.sep)
        if os.path.isfile(mapping_file):
            mapping_df = pd.read_excel(mapping_file, index_col=0)
        else:
            mapping_df = None
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
            mapping_df.to_excel(mapping_file)
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
