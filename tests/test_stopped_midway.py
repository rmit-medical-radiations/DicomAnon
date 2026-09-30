"""A run that stops partway through a patient must say where, and how to recover.

The HN run of 2026-09-29 crashed halfway, on a file in the middle of a patient. State
is saved once per patient, after their last file, so that patient's folder had files and
no record. The report did not name the patient, and the next run would have refused the
folder as data from an older version and asked for an empty output folder, throwing away
every patient already finished. The real recovery is to delete that one folder.

This runs the whole sequence: crash, read the report, re-run, delete what the report
names, re-run, and check the finished patient was never touched.
"""
import os, sys, tempfile, shutil, hashlib
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='dicomanon-test-'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from PyQt6.QtWidgets import QApplication, QMessageBox
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage

import DicomAnon
from DicomAnon import DicomAnonWidget
from _fixtures import save_dicom
from anon_checks import VerificationError, incomplete_folders, state_dir_for

QMessageBox.exec = lambda self: None          # dialogs must not block the test


def write(folder, pid, day, n):
    study_uid, series_uid = generate_uid(), generate_uid()
    for i in range(n):
        ds = Dataset()
        ds.PatientID, ds.PatientName = pid, 'NAME^' + pid
        ds.PatientBirthDate, ds.PatientSex = '19550312', 'M'
        ds.StudyDate, ds.StudyTime, ds.StudyID = day, '101500', 'RMH-1'
        ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
        ds.SOPInstanceUID = generate_uid()
        ds.SOPClassUID = MRImageStorage
        ds.file_meta = FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        d = os.path.join('src', folder, day)
        os.makedirs(d, exist_ok=True)
        save_dicom(ds, os.path.join(d, 'mr{}.dcm'.format(i)))


def widget(tag):
    w = DicomAnonWidget()
    w.state_home = os.path.abspath('home_' + tag)
    w.mapping_file = os.path.join(w.state_home, 'map.xlsx')
    w.report_path = os.path.abspath('report_{}.txt'.format(tag))
    w._verification_report_path = lambda p=w.report_path: p
    os.makedirs(w.state_home, exist_ok=True)
    w.source_dir = os.path.abspath('src')
    w.destination_dir = os.path.abspath('out_' + tag)
    w.lookup_file = os.path.abspath('lk.xlsx')
    os.makedirs(w.destination_dir, exist_ok=True)
    return w


def run(w, fail_on=None, fail_with=RuntimeError):
    """Run from the button, raising from inside the file loop at the named source file."""
    real = DicomAnon.snapshot_source
    seen = []

    def faulty(ds):
        seen.append(1)
        if fail_on and fail_on(ds, len(seen)):
            raise fail_with('simulated fault')
        return real(ds)

    DicomAnon.snapshot_source = faulty
    try:
        if os.path.exists(w.report_path):
            os.remove(w.report_path)
        w.anon_button_clicked()
    finally:
        DicomAnon.snapshot_source = real
    assert w.anon_button.isEnabled(), 'the app was left with its buttons disabled'
    return open(w.report_path).read() if os.path.exists(w.report_path) else ''


def digests(folder):
    out = {}
    for dirpath, _, names in os.walk(folder):
        for n in names:
            p = os.path.join(dirpath, n)
            out[os.path.relpath(p, folder)] = hashlib.sha1(open(p, 'rb').read()).hexdigest()
    return out


def second_file_of(pid):
    count = []

    def hit(ds, _):
        if str(ds.PatientID) == pid:
            count.append(1)
            return len(count) == 2
        return False
    return hit


app = QApplication(sys.argv[:1])
write('1111_One', '1111', '20210801', 2)
write('2222_Two', '2222', '20210801', 3)
pd.DataFrame({'Patient ID': ['1111', '2222'],
              'Anonymised ID': ['Brain-0001', 'Brain-0002']}).to_excel('lk.xlsx', index=False)

print('=== a crash partway through a new patient ===')
w = widget('new')
state_dir = state_dir_for(w.destination_dir, w.state_home)
body = run(w, second_file_of('2222'))
assert 'stopped unexpectedly' in body, body[:300]
assert 'patient 2222' in body and 'mr1.dcm' in body, body
half = os.path.normpath(os.path.join(w.destination_dir, 'Brain-0002'))
assert half in body and 'Delete that one folder' in body, body
print('  the report names the patient, the file, and the folder to delete')
assert incomplete_folders(state_dir) == {'Brain-0002'}, incomplete_folders(state_dir)
assert os.path.isfile(os.path.join(state_dir, 'Brain-0001.json'))
print('  the finished patient is recorded; the stopped one is marked incomplete')
finished = digests(os.path.join(w.destination_dir, 'Brain-0001'))

print('\n=== the next run, before anything is deleted ===')
body = run(w)
assert 'verification failure' in body, body[:300]
assert 'stopped partway through this patient' in body and 'Brain-0002' in body, body
assert 'older version' not in body, 'a marked folder was still blamed on an older version'
assert 'Brain-0001' not in body
print('  refused, naming only the stopped patient, with "delete that folder"')

print('\n=== delete what the report named, and run again ===')
shutil.rmtree(half)
body = run(w)
assert body == '', body
assert len(digests(half)) == 3
assert digests(os.path.join(w.destination_dir, 'Brain-0001')) == finished
assert not incomplete_folders(state_dir)
print('  finished: the stopped patient written in full, the other untouched, no markers')

print('\n=== a folder stopped by a version that left no marker ===')
w = widget('old')
state_dir = state_dir_for(w.destination_dir, w.state_home)
run(w, second_file_of('2222'))
os.remove(os.path.join(state_dir, 'Brain-0002.incomplete'))    # as v0.12 would leave it
body = run(w)
assert 'no record of' in body and 'Brain-0002' in body, body
assert 'delete nothing' in body and 'stopped partway through' in body
assert 'new, empty output folder' in body
print('  refused, with the lost-record, stopped-run and older-version remedies in order')

print('\n=== a crash partway through a patient recorded by an earlier run ===')
w = widget('known')
assert run(w) == ''
write('2222_Two', '2222', '20220301', 3)          # a new session arrives for 2222
body = run(w, second_file_of('2222'))
assert 'patient 2222' in body and 'nothing needs deleting' in body, body
assert 'Delete that one folder' not in body
assert run(w) == '', 'a recorded patient stopped midway should resume without help'
assert len(digests(os.path.join(w.destination_dir, 'Brain-0002'))) == 6
print('  the report says nothing needs deleting, and the next run just finishes')
shutil.rmtree(os.path.join('src', '2222_Two', '20220301'))

print('\n=== a failed check partway through a new patient ===')
w = widget('check')
body = run(w, second_file_of('2222'), fail_with=VerificationError)
assert 'verification failure' in body and 'simulated fault' in body, body[:300]
assert 'patient 2222' in body and 'Delete that one folder' in body, body
print('  the verification report carries the same note')

print('\na stopped run says where it stopped, and the recovery it gives works')
