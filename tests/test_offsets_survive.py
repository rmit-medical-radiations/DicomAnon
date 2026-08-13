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
