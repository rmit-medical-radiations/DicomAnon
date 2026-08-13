"""If saving the spreadsheet fails, the patient's offsets must not be lost."""
import os, sys, tempfile
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(tempfile.mkdtemp(prefix='offs-'))
import pandas as pd, json
from PyQt6.QtWidgets import QApplication, QMessageBox
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage
import DicomAnon
from DicomAnon import DicomAnonWidget
from _fixtures import save_dicom
from anon_checks import RunVerifier, VerificationError, state_dir_for
QMessageBox.exec = lambda self: None

ds = Dataset()
ds.PatientID, ds.PatientName = '1111', 'NAME^1111'
ds.PatientBirthDate, ds.PatientSex = '19550312', 'M'
ds.StudyDate, ds.StudyTime, ds.StudyID = '20210801', '101500', 'RMH-1'
ds.StudyInstanceUID = generate_uid(); ds.SeriesInstanceUID = generate_uid()
ds.SOPInstanceUID = generate_uid(); ds.SOPClassUID = MRImageStorage
ds.file_meta = FileMetaDataset()
ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
os.makedirs('src/1111_One/20210801'); save_dicom(ds, 'src/1111_One/20210801/i.dcm')
pd.DataFrame({'Patient ID': ['1111'], 'Anonymised ID': ['Brain-0001']}).to_excel('lk.xlsx', index=False)
os.makedirs('home'); os.makedirs('out')

app = QApplication(sys.argv[:1]); w = DicomAnonWidget()
w.state_home = os.path.abspath('home'); w.mapping_file = os.path.abspath('home/map.xlsx')
w.source_dir = os.path.abspath('src'); w.destination_dir = os.path.abspath('out')
w.lookup_file = os.path.abspath('lk.xlsx')
w._verification_report_path = lambda: os.path.abspath('report.txt')
w.verifier = RunVerifier()

real_replace = os.replace
def only_mapping_fails(a, b):
    if str(b).endswith('map.xlsx'):          # the spreadsheet, not the state file
        raise PermissionError(13, 'locked')
    return real_replace(a, b)
os.replace = only_mapping_fails
try:
    w.anon_button_clicked()          # the spreadsheet cannot be written
finally:
    os.replace = real_replace

sd = state_dir_for(w.destination_dir, w.state_home)
st = json.load(open(os.path.join(sd, 'Brain-0001.json')))
print('mapping file written        :', os.path.isfile(w.mapping_file))
print('state written anyway        :', True)
print('offsets recorded in state   :', st.get('offsets'))
print('files recorded in state     :', len(st['files']))
assert st.get('offsets'), 'the offsets were lost with the spreadsheet'

w2 = DicomAnonWidget()
w2.state_home = w.state_home; w2.mapping_file = w.mapping_file
print('\nnext run reuses them        :', w2._patient_offsets(None, 1111, st))
assert tuple(w2._patient_offsets(None, 1111, st)) == tuple(st['offsets'])
print('\noffsets survive a failed spreadsheet write')

# The temporary spreadsheet must be KEPT when the swap fails. At the hospital it was the
# only up-to-date copy of the mapping, the only record of a patient's date offsets, and
# the only evidence of what had gone wrong. An earlier version of this fix deleted it.
tmp = w.mapping_file + '.tmp.xlsx'
print('\ntemporary spreadsheet kept  :', os.path.isfile(tmp))
assert os.path.isfile(tmp), 'the only up-to-date copy of the mapping was deleted'
report = open(os.path.abspath('report.txt')).read()
assert os.path.normpath(tmp) in report, 'the report does not say where that copy is'
print('report names it             : True')
assert 'Excel' in report and 'OneDrive' in report, report[:200]
print('cause left open, not blamed on Excel alone')

# and a transient holder should be ridden out rather than ending the run
attempts = {'n': 0}
def fails_twice(a, b):
    attempts['n'] += 1
    if str(b).endswith('map.xlsx') and attempts['n'] <= 2:
        raise PermissionError(13, 'locked')
    return real_replace(a, b)

os.replace = fails_twice
try:
    w3 = DicomAnonWidget()
    w3.state_home = w.state_home
    w3._save_mapping(pd.DataFrame([{'patient_id': 1111}]), w.mapping_file)
finally:
    os.replace = real_replace
print('\nretried through a transient lock, {} attempts, run continued'.format(attempts['n']))
assert attempts['n'] > 1, 'no retry happened'
assert not os.path.isfile(tmp), 'the temporary file was left behind after success'
print('temporary file cleared once it succeeded')
