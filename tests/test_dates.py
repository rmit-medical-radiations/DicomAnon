"""Defect 1: every date and time must move, and intervals must survive."""
import os, sys, shutil
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import os, sys, tempfile
# Run from a throwaway directory so a test can never touch the real output folder,
# the real ID mapping file, or the real state under the home folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='dicomanon-test-'))
import pandas as pd
from PyQt6.QtWidgets import QApplication
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage
from DicomAnon import DicomAnonWidget
from anon_checks import snapshot_source, verify_file, DATE_VRS

def make(study_date='20210819', series_date='20210819', study_time='134732'):
    ds = Dataset()
    ds.PatientID, ds.PatientName = '1234', 'SMITH^JOHN'
    ds.PatientBirthDate, ds.PatientSex, ds.PatientAge = '19550312', 'M', '066Y'
    ds.StudyDate, ds.SeriesDate, ds.AcquisitionDate = study_date, series_date, series_date
    ds.StudyTime, ds.SeriesTime, ds.AcquisitionTime, ds.ContentTime = study_time, '134800', '134900', '135000'
    ds.ContentDate = series_date
    ds.AcquisitionDateTime = series_date + '134732.500000+1000'
    ds.StudyID = 'RMH-4471'
    ds.SeriesDescription = '20210819134732-1ABrain'
    ds.StudyDescription = 'BRAIN WITH CONTRAST'
    ds.StudyInstanceUID = generate_uid(); ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = generate_uid(); ds.SOPClassUID = MRImageStorage
    item = Dataset(); item.ReferencedSOPClassUID = MRImageStorage
    item.ReferencedSOPInstanceUID = generate_uid()
    nested = Dataset(); nested.ContentDate = series_date; nested.ContentTime = '140000'
    item.ReferencedImageSequence = Sequence([nested])
    ds.ReferencedSeriesSequence = Sequence([item])
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    return ds

app = QApplication(sys.argv[:1]); w = DicomAnonWidget()
offsets = (-1234, 45678)

print('=== every DA/TM/DT element moves, including inside nested sequences ===')
ds = make(); snap = snapshot_source(ds)
before = {str(e.tag): str(e.value) for e in ds.iterall() if e.VR in DATE_VRS}
w.anonymise_dicom(ds=ds, anon_name='Brain-0001', offsets=offsets)
after = {str(e.tag): str(e.value) for e in ds.iterall() if e.VR in DATE_VRS}
unchanged = [t for t in before if t in after and before[t] == after[t] and before[t].strip()]
print('  {} date/time elements, {} unchanged'.format(len(before), len(unchanged)))
assert not unchanged, unchanged
print('  StudyDate  {} -> {}'.format(before.get('(0008,0020)'), after.get('(0008,0020)')))
print('  StudyTime  {} -> {}'.format(before.get('(0008,0030)'), after.get('(0008,0030)')))
print('  AcqDateTime -> {}'.format(after.get('(0008,002A)')))
print('  nested ContentDate moved too:', after.get('(0008,0023)'))
print('  SeriesDescription -> {}'.format(ds.SeriesDescription))
# a DA/TM pair and a DT holding the same instant must agree after shifting
assert after.get('(0008,002A)').startswith(after.get('(0008,0020)')), (
    'StudyDate {} disagrees with AcquisitionDateTime {}'.format(
        after.get('(0008,0020)'), after.get('(0008,002A)')))
print('  StudyDate agrees with AcquisitionDateTime')
assert '20210819' not in ds.SeriesDescription
print('  PatientAge kept: {}  birth date: {}'.format(ds.PatientAge, ds.PatientBirthDate))

print('\n=== the date check now passes, and catches an unshifted date ===')
problems = verify_file(ds, snap, 'Brain-0001')
print('  clean file problems: {}'.format(problems))
assert not problems
ds.SeriesDate = '20210819'   # as if one tag were missed
problems = verify_file(ds, snap, 'Brain-0001')
print('  after putting SeriesDate back: {}'.format(problems))
assert any('SeriesDate' in p for p in problems)

print('\n=== intervals between studies survive the shift ===')
a, b = make(study_date='20210801'), make(study_date='20210815')
w.anonymise_dicom(ds=a, anon_name='Brain-0001', offsets=offsets)
w.anonymise_dicom(ds=b, anon_name='Brain-0001', offsets=offsets)
import datetime as dt
gap = (dt.datetime.strptime(b.StudyDate, '%Y%m%d') - dt.datetime.strptime(a.StudyDate, '%Y%m%d')).days
print('  14 days apart before, {} days apart after'.format(gap))
assert gap == 14

print('\n=== the offset is not recoverable by differencing two tags ===')
c = make(study_date='20210801', series_date='20210801')
w.anonymise_dicom(ds=c, anon_name='Brain-0001', offsets=offsets)
print('  StudyDate {} == SeriesDate {}: {}'.format(c.StudyDate, c.SeriesDate, c.StudyDate == c.SeriesDate))
assert c.StudyDate == c.SeriesDate
print('\nall date tests passed')
