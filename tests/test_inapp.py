"""End-to-end: does the app stop a run when a source folder holds two patients?"""
import os, shutil, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import os, sys, tempfile
# Run from a throwaway directory so a test can never touch the real output folder,
# the real ID mapping file, or the real state under the home folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='dicomanon-test-'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from PyQt6.QtWidgets import QApplication
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage

from DicomAnon import DicomAnonWidget
from _fixtures import save_dicom
from anon_checks import VerificationError

SRC, DST = 'testsrc', 'testout'

def write(patient_folder, session, name, pid, pname, birth='19550312', sex='M', **kw):
    ds = Dataset()
    ds.PatientID, ds.PatientName = pid, pname
    ds.PatientBirthDate, ds.PatientSex = birth, sex
    ds.StudyID = kw.get('study_id', 'RMH-001')
    ds.StudyDate = '20210801'
    ds.StudyInstanceUID = kw.get('study_uid', generate_uid())
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.SOPClassUID = MRImageStorage
    ds.Modality = 'MR'
    ds.InstitutionName = 'Big Hospital'
    ds.ReferringPhysicianName = 'JONES^A'
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    d = os.path.join(SRC, patient_folder, session)
    os.makedirs(d, exist_ok=True)
    save_dicom(ds, os.path.join(d, name))

def build(contaminate):
    shutil.rmtree(SRC, ignore_errors=True); shutil.rmtree(DST, ignore_errors=True)
    os.makedirs(DST)
    for i in range(3):
        write('1234_SmithJohn', '20210801', 'a{}.dcm'.format(i), '1234', 'SMITH^JOHN')
    for i in range(2):
        write('5678_JonesMary', '20210801', 'b{}.dcm'.format(i), '5678', 'JONES^MARY',
              birth='19620704', sex='F')
    if contaminate:
        # a study belonging to patient 5678 sitting inside 1234's folder: defect 6 path A
        write('1234_SmithJohn', '20210902', 'c0.dcm', '5678', 'JONES^MARY',
              birth='19620704', sex='F')
    pd.DataFrame({'Patient ID': ['1234', '5678'],
                  'Anonymised ID': ['Brain-0001', 'Brain-0002']}).to_excel(
                      'lookup.xlsx', index=False)

app = QApplication(sys.argv[:1])
w = DicomAnonWidget()
w.mapping_file = os.path.abspath('inapp-mapping.xlsx')  # never the real one in ~
w.state_home = os.path.abspath('inapp-home'); os.makedirs(w.state_home, exist_ok=True)

print('=== clean source ===')
build(contaminate=False)
lookup = w._load_lookup('lookup.xlsx')
w.verifier = __import__('anon_checks').RunVerifier()
mapping, missing = w.process_folder(SRC, DST, None, lookup)
written = sum(len(f) for _, _, f in os.walk(DST))
print('  completed, {} files written, warnings: {}'.format(written, w.verifier.problems()))
assert written == 5, written

print('\n=== contaminated source: 5678 study inside 1234 folder ===')
build(contaminate=True)
w.verifier = __import__('anon_checks').RunVerifier()
try:
    w.process_folder(SRC, DST, None, lookup)
    print('  FAIL: the run completed and wrote the contaminating file')
    sys.exit(1)
except VerificationError as e:
    print('  stopped, as intended:')
    for line in str(e).splitlines():
        print('    ' + line)
    written = sum(len(f) for _, _, f in os.walk(DST))
    # glob() is unsorted, so which file trips the check depends on directory order;
    # what must hold is that it stopped before writing all six
    print('  {} of 6 source files written before the stop'.format(written))
    assert written < 6, written
    for folder in os.listdir(DST):
        ids = set()
        for dirpath, _, names in os.walk(os.path.join(DST, folder)):
            for n in names:
                import pydicom
                ids.add(str(pydicom.dcmread(os.path.join(dirpath, n)).PatientID))
        assert ids <= {folder}, (folder, ids)
    print('  every written file is labelled for the folder it sits in')

print('\n=== a broken anonymiser must be caught per file ===')
build(contaminate=False)
original = DicomAnonWidget.anonymise_dicom
def leaky(self, ds, anon_name, uid_map=None, study_label_map=None, offsets=None):
    ds = original(self, ds, anon_name, uid_map, study_label_map, offsets)
    ds.ReferringPhysicianName = 'JONES^A'   # as if a keyword entry silently blanked nothing
    return ds
DicomAnonWidget.anonymise_dicom = leaky
w.verifier = __import__('anon_checks').RunVerifier()
try:
    w.process_folder(SRC, DST, None, lookup)
    print('  FAIL: a leaking anonymiser was not caught')
    sys.exit(1)
except VerificationError as e:
    print('  stopped on the first file:')
    for line in str(e).splitlines():
        print('    ' + line)
finally:
    DicomAnonWidget.anonymise_dicom = original

print('\nall cases behaved correctly')
