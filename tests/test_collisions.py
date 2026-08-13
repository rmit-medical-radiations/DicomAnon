"""Two source folders whose names parse to the same patient ID.

Both would be written into one anonymised folder, so the run must stop. But only when
the lookup actually names that patient: a source directory often holds folders belonging
to another delivery, and halting for a patient that would have been skipped anyway is a
false stop the researcher cannot act on.
"""
import os, sys, shutil, tempfile
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='dicomanon-test-'))

import pandas as pd
from PyQt6.QtWidgets import QApplication
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage

from DicomAnon import DicomAnonWidget
from anon_checks import RunVerifier, VerificationError

SRC = os.path.abspath('csrc')


def write(folder, pid):
    ds = Dataset()
    ds.PatientID, ds.PatientName = pid, 'NAME^' + pid
    ds.PatientBirthDate, ds.PatientSex = '19550312', 'M'
    ds.StudyDate, ds.StudyTime = '20210801', '101500'
    ds.StudyID = 'RMH-1'
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.SOPClassUID = MRImageStorage
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    d = os.path.join(SRC, folder, '20210801')
    os.makedirs(d, exist_ok=True)
    ds.save_as(os.path.join(d, 'i.dcm'), enforce_file_format=True)


shutil.rmtree(SRC, ignore_errors=True)
# 0123 and 123 both parse to 123; Excel cannot even express the leading zero
write('0123_SmithJohn', '123')
write('123_JonesMary', '123')
write('5678_BrownAnn', '5678')

app = QApplication(sys.argv[:1])
w = DicomAnonWidget()
w.state_home = os.path.abspath('chome')
w.mapping_file = os.path.abspath('chome/map.xlsx')
os.makedirs(w.state_home, exist_ok=True)


def attempt(label, ids, anons):
    pd.DataFrame({'Patient ID': ids, 'Anonymised ID': anons}).to_excel('lk.xlsx',
                                                                      index=False)
    lookup = w._load_lookup('lk.xlsx')
    w.verifier = RunVerifier()
    out = os.path.abspath('out_' + anons[0])
    os.makedirs(out, exist_ok=True)
    try:
        w.process_folder(SRC, out, None, lookup)
        print('  {:<46} proceeded'.format(label))
        return None
    except VerificationError as e:
        print('  {:<46} refused'.format(label))
        return str(e)


print('=== the colliding patient is not in the lookup ===')
assert attempt('only the unaffected patient is named', ['5678'], ['Brain-0002']) is None, \
    'halted for a patient that would have been skipped anyway'

print('\n=== the colliding patient IS in the lookup ===')
detail = attempt('the colliding patient is named', ['123'], ['Brain-0001'])
assert detail, 'two folders with the same patient ID were accepted'
assert '0123_SmithJohn' in detail and '123_JonesMary' in detail, detail
print('  both source folders named in the message:')
for line in detail.splitlines():
    if line.strip().startswith('-'):
        print('   ', line.strip())

print('\ncollision handling correct')
