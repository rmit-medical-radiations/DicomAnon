"""Several source folders parsing to the same patient ID.

This is normal, not an error. The export names folders <PatientID>_<PatientName>, so a
patient whose name is recorded two ways gets one folder per spelling: a real export
contains 900001_SURNAME^GIVEN^R and 900001_SURNAME^GIVEN^R^MR, same person, same DICOM
PatientID, different studies. Those must merge into that patient's one anon folder.

What must still stop the run is two DIFFERENT patients sharing a parsed ID, which the
folder name cannot distinguish but the source PatientID can, and two folders whose files
would be written to the same path, where one would silently overwrite the other.
"""
import os, sys, shutil, tempfile
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='dicomanon-test-'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import pydicom
from PyQt6.QtWidgets import QApplication
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage

from DicomAnon import DicomAnonWidget
from _fixtures import save_dicom
from anon_checks import RunVerifier, VerificationError


def write(root, folder, pid, session, name, sop=None):
    ds = Dataset()
    ds.PatientID, ds.PatientName = pid, folder.split('_', 1)[1]
    ds.PatientBirthDate, ds.PatientSex = '19550312', 'M'
    ds.StudyDate, ds.StudyTime = '20210801', '101500'
    ds.StudyID = 'RMH-1'
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = sop or generate_uid()
    ds.SOPClassUID = MRImageStorage
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    d = os.path.join(root, folder, session)
    os.makedirs(d, exist_ok=True)
    save_dicom(ds, os.path.join(d, name))


app = QApplication(sys.argv[:1])
w = DicomAnonWidget()
run_no = [0]


def attempt(label, root, ids, anons):
    run_no[0] += 1
    pd.DataFrame({'Patient ID': ids, 'Anonymised ID': anons}).to_excel('lk.xlsx', index=False)
    w.state_home = os.path.abspath('home{}'.format(run_no[0]))
    w.mapping_file = os.path.join(w.state_home, 'map.xlsx')
    os.makedirs(w.state_home, exist_ok=True)
    lookup = w._load_lookup('lk.xlsx')
    w.verifier = RunVerifier()
    out = os.path.abspath('out{}'.format(run_no[0]))
    os.makedirs(out, exist_ok=True)
    try:
        w.process_folder(root, out, None, lookup)
        print('  {:<48} proceeded'.format(label))
        return out, None
    except VerificationError as e:
        print('  {:<48} stopped'.format(label))
        return out, str(e)


print('=== one patient, two folders, name recorded two ways ===')
SAME = os.path.abspath('same')
write(SAME, '900001_SURNAME^GIVEN^R', '900001', '20210801', 'a.dcm')
write(SAME, '900001_SURNAME^GIVEN^R^MR', '900001', '20210915', 'c.dcm')
write(SAME, '900001_SURNAME^GIVEN^R^MR', '900001', '20211001', 'd.dcm')
out, err = attempt('same DICOM PatientID, distinct paths', SAME,
                   ['900001'], ['Brain-0001'])
assert err is None, err
written = sorted(f for _, _, fs in os.walk(out) for f in fs)
print('    merged into one anon folder: {} files, sessions {}'.format(
    len(written), sorted(os.listdir(os.path.join(out, 'Brain-0001')))))
assert len(written) == 3, written
ids = {str(pydicom.dcmread(os.path.join(d, f)).PatientID)
       for d, _, fs in os.walk(out) for f in fs}
assert ids == {'Brain-0001'}, ids
print('    every file carries the one anonymised identity')

print('\n=== two DIFFERENT patients sharing a parsed ID ===')
DIFF = os.path.abspath('diff')
write(DIFF, '0123_SmithJohn', '123', '20210801', 'a.dcm')
write(DIFF, '123_JonesMary', '999', '20210801', 'b.dcm')   # a different person
out, err = attempt('different DICOM PatientIDs', DIFF, ['123'], ['Brain-0002'])
assert err, 'two different patients were merged into one folder'
print('    {}'.format([l.strip() for l in err.splitlines() if l.strip()][-1][:110]))

print('\n=== two folders whose files land on the same path ===')
CLASH = os.path.abspath('clash')
write(CLASH, '555_A^B', '555', '20210801', 'i.dcm')
write(CLASH, '555_A^B^MR', '555', '20210801', 'i.dcm')     # same rel path, different image
out, err = attempt('same path, different instances', CLASH, ['555'], ['Brain-0003'])
assert err, 'one file would have silently overwritten the other'
print('    {}'.format(err.splitlines()[0][:110]))

print('\n=== the same instance exported into both folders is not a collision ===')
DUP = os.path.abspath('dup')
shared = generate_uid()
write(DUP, '777_C^D', '777', '20210801', 'i.dcm', sop=shared)
write(DUP, '777_C^D^MR', '777', '20210801', 'i.dcm', sop=shared)
out, err = attempt('same path, same instance', DUP, ['777'], ['Brain-0004'])
assert err is None, err

print('\n=== a folder the lookup never names causes no false stop ===')
out, err = attempt('colliding patient not in the lookup', DIFF, ['5678'], ['Brain-0005'])
assert err is None, err


print('\n=== a folder named for one patient but filled with another\'s files ===')
MISNAMED = os.path.abspath('misnamed')
write(MISNAMED, '1234_SmithJohn', '9999', '20210801', 'a.dcm')   # name says 1234
out, err = attempt('folder name disagrees with the PatientID', MISNAMED,
                   ['1234'], ['Brain-0006'])
assert err, "a misnamed folder was accepted, filing one patient under another's identity"
print('    {}'.format(err.splitlines()[0][:110]))
assert not any(f.endswith('.dcm') for _, _, fs in os.walk(out) for f in fs), \
    'files were written before the mismatch was noticed'
print('    nothing was written')

print('\n=== a non-numeric PatientID is reported, not blocked ===')
ODD = os.path.abspath('odd')
write(ODD, '4321_Odd^Format', 'MRN-4321', '20210801', 'a.dcm')
out, err = attempt('PatientID that cannot be compared', ODD, ['4321'], ['Brain-0007'])
assert err is None, err
notes = w.verifier.problems()
assert any('could not be checked' in p for p in notes), notes
print('    warned: {}'.format(notes[0][:100]))

print('\nmerge, collision and folder-name handling correct')
