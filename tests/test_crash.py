"""A run must never leave the operator with a dead window.

The oncologist reported v0.10 anonymising one patient and then crashing. Two paths in
process_folder could do that, and neither was caught by anon_button_clicked, which only
handled VerificationError:

  - a patient whose folders yield no .dcm files: the destination is created inside the
    file loop, so os.listdir on it raised FileNotFoundError;
  - a write failing at all: os.makedirs and ds.save_as sat outside any try.

Both now finish with a saved report and a dialog that says what it means for the data.
"""
import os, sys, tempfile
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
from anon_checks import RunVerifier

QMessageBox.exec = lambda self: None          # dialogs must not block the test


def write(folder, pid, name='i.dcm'):
    ds = Dataset()
    ds.PatientID, ds.PatientName = pid, 'NAME^' + pid
    ds.PatientBirthDate, ds.PatientSex = '19550312', 'M'
    ds.StudyDate, ds.StudyTime, ds.StudyID = '20210801', '101500', 'RMH-1'
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.SOPClassUID = MRImageStorage
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    d = os.path.join('src', folder, '20210801')
    os.makedirs(d, exist_ok=True)
    save_dicom(ds, os.path.join(d, name))


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
    w.verifier = RunVerifier()
    return w


app = QApplication(sys.argv[:1])
write('1111_One', '1111')
os.makedirs(os.path.join('src', '2222_Two', '20210801'), exist_ok=True)   # no .dcm at all
pd.DataFrame({'Patient ID': ['1111', '2222'],
              'Anonymised ID': ['Brain-0001', 'Brain-0002']}).to_excel('lk.xlsx', index=False)

print('=== a patient folder with no .dcm files ===')
w = widget('empty')
_, _, no_files = w.process_folder(w.source_dir, w.destination_dir, None,
                                  w._load_lookup('lk.xlsx'))
written = sum(len(f) for _, _, f in os.walk(w.destination_dir))
print('  run completed, {} file(s) written for the other patient'.format(written))
assert written == 1, written
assert no_files and no_files[0][0] == 2222, no_files
print('  patient {} reported as having no DICOM files'.format(no_files[0][0]))

print('\n=== a write fails partway through the run ===')
write('2222_Two', '2222')          # give patient 2 real files this time
w = widget('drop')
real_makedirs = os.makedirs


def flaky(path, *a, **k):
    if 'Brain-0002' in str(path):
        raise OSError(5, 'Input/output error')
    return real_makedirs(path, *a, **k)


DicomAnon.os.makedirs = flaky
try:
    w.anon_button_clicked()
finally:
    DicomAnon.os.makedirs = real_makedirs

assert w.anon_button.isEnabled(), 'the app was left with its buttons disabled'
print('  the app survived and is usable again')
assert os.path.isfile(w.report_path), 'no report was written for the operator to send'
body = open(w.report_path).read()
assert 'stopped unexpectedly' in body and 'Traceback' in body, body[:200]
assert w.source_dir in body and w.destination_dir in body
print('  a report naming the source, output and fault was saved')
written = sum(len(f) for _, _, f in os.walk(w.destination_dir))
print('  {} file(s) written before the failure, and the run did not pretend to finish'
      .format(written))

print('\nneither failure leaves a dead window')
