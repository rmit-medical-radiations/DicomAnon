"""Defects 2, 3 and 4: stable UIDs across runs, per-patient maps, no version mixing."""
import os, sys, shutil, json
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import os, sys, tempfile
# Run from a throwaway directory so a test can never touch the real output folder,
# the real ID mapping file, or the real state under the home folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='dicomanon-test-'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, pydicom
from PyQt6.QtWidgets import QApplication
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage
import anon_checks
from DicomAnon import DicomAnonWidget
from _fixtures import save_dicom
from anon_checks import RunVerifier, VerificationError, state_dir_for

SRC, DST, HOME = os.path.abspath('ssrc'), os.path.abspath('sout'), os.path.abspath('shome')

# a UID shared by both patients, as a vendor constant would be
SHARED_FOR = '1.2.826.0.1.3680043.8.498.1229313067498998618823'

def write(folder, pid, session, name, for_uid=SHARED_FOR, study_uid=None):
    ds = Dataset()
    ds.PatientID, ds.PatientName = pid, 'NAME^' + pid
    ds.PatientBirthDate, ds.PatientSex = '19550312', 'M'
    ds.StudyDate = ds.SeriesDate = session
    ds.StudyTime = ds.SeriesTime = '101500'
    ds.StudyID = 'RMH-1'
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.SeriesInstanceUID = generate_uid(); ds.SOPInstanceUID = generate_uid()
    ds.FrameOfReferenceUID = for_uid
    ds.SOPClassUID = MRImageStorage
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    d = os.path.join(SRC, folder, session); os.makedirs(d, exist_ok=True)
    save_dicom(ds, os.path.join(d, name))

def read_all():
    out = {}
    for dirpath, _, names in os.walk(DST):
        for n in names:
            ds = pydicom.dcmread(os.path.join(dirpath, n))
            rel = os.path.relpath(os.path.join(dirpath, n), DST)
            out[rel] = ds
    return out

for p in (SRC, DST, HOME):
    shutil.rmtree(p, ignore_errors=True)
os.makedirs(DST); os.makedirs(HOME)
pd.DataFrame({'Patient ID': ['1234', '5678'],
              'Anonymised ID': ['Brain-0001', 'Brain-0002']}).to_excel('lk4.xlsx', index=False)

app = QApplication(sys.argv[:1]); w = DicomAnonWidget()
w.mapping_file = os.path.join(HOME, 'map.xlsx'); w.state_home = HOME
lookup = w._load_lookup('lk4.xlsx')

def run():
    w.verifier = RunVerifier()
    m, _ = w.process_folder(SRC, DST, w._read_mapping(w.mapping_file), lookup)
    w._save_mapping(m, w.mapping_file)
    return m

print('=== run 1 ===')
write('1234_A', '1234', '20210801', 'a.dcm')
write('5678_B', '5678', '20210801', 'b.dcm')
run()
first = read_all()
print('  wrote {} files'.format(len(first)))

print('\n=== defect 3: the two patients must NOT share a pseudonymised UID ===')
fors = {rel: str(ds.FrameOfReferenceUID) for rel, ds in first.items()}
print('  Brain-0001 FrameOfReferenceUID:', [v for k, v in fors.items() if k.startswith('Brain-0001')][0][:44])
print('  Brain-0002 FrameOfReferenceUID:', [v for k, v in fors.items() if k.startswith('Brain-0002')][0][:44])
assert len(set(fors.values())) == 2, 'the shared source UID produced one pseudonym for both patients'
print('  distinct, even though both came from the same source UID')

print('\n=== defect 2: a second run must reuse the same pseudonyms ===')
write('1234_A', '1234', '20210815', 'c.dcm')      # oncologist adds a session
run()
second = read_all()
for rel in first:
    assert str(first[rel].SOPInstanceUID) == str(second[rel].SOPInstanceUID), rel
    assert str(first[rel].FrameOfReferenceUID) == str(second[rel].FrameOfReferenceUID), rel
print('  earlier files kept identical UIDs across runs')
new_series = [v for k, v in second.items() if '20210815' in k][0]
old_series = [v for k, v in second.items() if k.startswith('Brain-0001') and '20210801' in k][0]
print('  new session resolves to the same frame of reference:',
      str(new_series.FrameOfReferenceUID) == str(old_series.FrameOfReferenceUID))
assert str(new_series.FrameOfReferenceUID) == str(old_series.FrameOfReferenceUID)
labels = sorted({str(v.StudyID) for k, v in second.items() if k.startswith('Brain-0001')})
print('  StudyID numbering continued rather than restarting:', labels)
assert labels == ['STUDY_0001', 'STUDY_0002']

print('\n=== defect 4: a version change must not be mixed into the same folder ===')
state_dir = state_dir_for(DST, HOME)
sp = os.path.join(state_dir, 'Brain-0001.json')
st = json.load(open(sp))
st['tool_version'] = '0.7'
st['files']['20210701/gone.dcm'] = '0.7'    # written by 0.7, no longer in the source
json.dump(st, open(sp, 'w'))
try:
    run()
    print('  FAIL: version mixing was allowed')
    sys.exit(1)
except VerificationError as e:
    print('  stopped:', str(e).splitlines()[0])
    print('          ', [l.strip() for l in str(e).splitlines() if 'gone.dcm' in l][0])

print('\n=== a destination with unrecorded data must be refused ===')
shutil.rmtree(state_dir)
try:
    run()
    print('  FAIL: unrecorded output was accepted')
    sys.exit(1)
except VerificationError as e:
    print('  stopped:', str(e).splitlines()[0])

print('\nall state tests passed')
