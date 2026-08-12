"""The oncologist's workflow: add studies to a patient already anonymised."""
import os, sys, shutil, datetime as dt
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import os, sys, tempfile
# Run from a throwaway directory so a test can never touch the real output folder,
# the real ID mapping file, or the real state under the home folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='dicomanon-test-'))
import pandas as pd, pydicom
from PyQt6.QtWidgets import QApplication
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage
from DicomAnon import DicomAnonWidget
from anon_checks import RunVerifier, VerificationError

SRC, DST, MAP = 'msrc', 'mout', 'mapping.xlsx'

def write(session, day):
    ds = Dataset()
    ds.PatientID, ds.PatientName = '1234', 'SMITH^JOHN'
    ds.PatientBirthDate, ds.PatientSex = '19550312', 'M'
    ds.StudyDate = ds.SeriesDate = day
    ds.StudyTime = ds.SeriesTime = '101500'
    ds.StudyID = 'RMH-1'
    ds.StudyInstanceUID = generate_uid(); ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = generate_uid(); ds.SOPClassUID = MRImageStorage
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    d = os.path.join(SRC, '1234_SmithJohn', session); os.makedirs(d, exist_ok=True)
    ds.save_as(os.path.join(d, 'i.dcm'), enforce_file_format=True)

def study_dates():
    out = {}
    for dirpath, _, names in os.walk(DST):
        for n in names:
            ds = pydicom.dcmread(os.path.join(dirpath, n))
            out[os.path.basename(dirpath)] = ds.StudyDate
    return out

shutil.rmtree(SRC, ignore_errors=True); shutil.rmtree(DST, ignore_errors=True)
for f in (MAP,):
    if os.path.exists(f): os.remove(f)
os.makedirs(DST)
pd.DataFrame({'Patient ID': ['1234'], 'Anonymised ID': ['Brain-0001']}).to_excel('lk2.xlsx', index=False)

app = QApplication(sys.argv[:1]); w = DicomAnonWidget()
w.mapping_file = MAP
w.state_home = os.path.abspath('map-home')
shutil.rmtree(w.state_home, ignore_errors=True); os.makedirs(w.state_home)
lookup = w._load_lookup('lk2.xlsx')

print('=== run 1: first two sessions ===')
write('20210801', '20210801'); write('20210815', '20210815')
w.verifier = RunVerifier()
mapping, _ = w.process_folder(SRC, DST, w._read_mapping(MAP), lookup)
w._save_mapping(mapping, MAP)
first = study_dates(); print('  ', first)
offsets1 = (int(mapping.iloc[0]['date_offset_days']), int(mapping.iloc[0]['time_offset_seconds']))
print('   stored offsets:', offsets1)

print('\n=== run 2: the oncologist adds a session weeks later ===')
write('20210902', '20210902')
w.verifier = RunVerifier()
mapping, _ = w.process_folder(SRC, DST, w._read_mapping(MAP), lookup)
w._save_mapping(mapping, MAP)
second = study_dates(); print('  ', second)
offsets2 = (int(mapping.iloc[0]['date_offset_days']), int(mapping.iloc[0]['time_offset_seconds']))
print('   offsets reused:', offsets2 == offsets1, offsets2)
assert offsets2 == offsets1
for sess in first:
    assert first[sess] == second[sess], (sess, first[sess], second[sess])
print('   earlier sessions kept the same shifted dates')

d = lambda s: dt.datetime.strptime(second[s], '%Y%m%d')
print('   real gaps 14 and 18 days; shifted gaps {} and {}'.format(
    (d('20210815') - d('20210801')).days, (d('20210902') - d('20210815')).days))
assert (d('20210815') - d('20210801')).days == 14
assert (d('20210902') - d('20210815')).days == 18

print('\n=== the mapping file warns against hand editing ===')
sheets = pd.read_excel(MAP, sheet_name=None)
print('   sheets:', list(sheets))
assert list(sheets)[0] == 'DO NOT EDIT'
print('   first line:', sheets['DO NOT EDIT'].iloc[0, 0])
print('   columns:', list(sheets['mapping'].columns)[1:])

print('\n=== rule 1: reassigning the patient is refused ===')
pd.DataFrame({'Patient ID': ['1234'], 'Anonymised ID': ['Brain-0009']}).to_excel('lk3.xlsx', index=False)
from anon_checks import check_assignments
problems = check_assignments(w._load_lookup('lk3.xlsx'), w._recorded_assignments(w._read_mapping(MAP)))
print('  ', problems[0])
assert problems
print('\nall mapping tests passed')
