"""Would real, messy DICOM falsely stop a run?"""
import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='dicomanon-test-'))
from PyQt6.QtWidgets import QApplication
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage
from DicomAnon import DicomAnonWidget
from anon_checks import snapshot_source, verify_file

app = QApplication(sys.argv[:1]); w = DicomAnonWidget()

FAILURES = []

def check(label, build):
    ds = build()
    snap = snapshot_source(ds)
    ds = w.anonymise_dicom(ds=ds, anon_name='Brain-0001', offsets=(-400, 3600))
    problems = verify_file(ds, snap, 'Brain-0001')
    print('  {:<44} {}'.format(label, problems or 'ok'))
    if problems:
        FAILURES.append((label, problems))
    return problems

def base():
    ds = Dataset()
    ds.PatientID, ds.PatientName = '1234', 'SMITH^JOHN'
    ds.PatientBirthDate, ds.PatientSex = '19550312', 'M'
    ds.StudyDate, ds.StudyTime = '20210819', '134732'
    ds.StudyInstanceUID = generate_uid(); ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = generate_uid(); ds.SOPClassUID = MRImageStorage
    ds.StudyID = 'RMH-1'
    return ds

print('=== things real hospital data actually contains ===')
def no_study_uid():
    ds = base(); del ds.StudyInstanceUID; return ds
check('file with no StudyInstanceUID', no_study_uid)

def private_in_sequence():
    ds = base()
    item = Dataset()
    item.ReferencedSOPClassUID = MRImageStorage
    item.ReferencedSOPInstanceUID = generate_uid()
    item.add_new(0x00291010, 'LO', 'SIEMENS CSA VALUE')   # private tag inside a sequence
    ds.ReferencedImageSequence = Sequence([item])
    return ds
check('private tag nested in a sequence', private_in_sequence)

def identifying_in_sequence():
    ds = base()
    item = Dataset()
    item.InstitutionName = 'BIG HOSPITAL'
    item.ReferringPhysicianName = 'JONES^A'
    ds.RequestAttributesSequence = Sequence([item])
    return ds
check('InstitutionName nested in a sequence', identifying_in_sequence)

def malformed_date():
    ds = base(); ds.StudyDate = '2021'; ds.PatientBirthDate = '1955'; return ds
check('truncated dates', malformed_date)

def empty_time():
    ds = base(); ds.StudyTime = ''; ds.SeriesTime = '  '; return ds
check('empty and whitespace times', empty_time)

def multivalue_uid():
    ds = base()
    ds.add_new(0x00081140, 'SQ', [])
    ds.FrameOfReferenceUID = generate_uid()
    return ds
check('empty sequence', multivalue_uid)

# The hospital run of 2026-09-29 stopped halfway on this. pydicom's private dictionary
# gives Elscint (01F1,1026) VR FD, an 8-byte double, and the scanner wrote the text
# '0.773 '. It has to go through a real file: pydicom only converts a value when the
# element is first read, so a dataset built in memory never meets the problem.
def wrong_length_private():
    import tempfile as _tf
    from pydicom import dcmread
    ds = base()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.add_new(0x01F10010, 'LO', 'ELSCINT1')
    ds.add_new(0x01F11026, 'UN', b'0.773 ')
    ds.Rows = 512
    path = os.path.join(_tf.mkdtemp(), 'elscint.dcm')
    ds.save_as(path, enforce_file_format=True)
    # and a public binary element one byte short, which has no dictionary to blame
    with open(path, 'rb') as f:
        raw = f.read()
    rows = b'\x28\x00\x10\x00US\x02\x00\x00\x02'
    assert raw.count(rows) == 1
    with open(path, 'wb') as f:
        f.write(raw.replace(rows, b'\x28\x00\x10\x00US\x01\x00\x00'))
    return dcmread(path)
check('value whose length does not fit its VR', wrong_length_private)

# Nested identifying tags must actually be gone, not merely undetected: the old check
# used the same top-level test as the blanking, so it could only confirm its own bug.
def nested_check():
    from anon_checks import populated_identifying_tags
    ds = base()
    inner = Dataset(); inner.InstitutionName = 'DEEP'; inner.OperatorsName = 'OP^A'
    mid = Dataset(); mid.InstitutionName = 'BIG'; mid.ReferringPhysicianName = 'JONES^A'
    mid.RequestedProcedureCodeSequence = Sequence([inner])
    ds.RequestAttributesSequence = Sequence([mid])
    assert populated_identifying_tags(ds), 'the walk cannot see nested tags at all'
    w.anonymise_dicom(ds=ds, anon_name='Brain-0001', offsets=(-400, 3600))
    left = populated_identifying_tags(ds)
    print('  {:<44} {}'.format('nested tags actually blanked', left or 'ok'))
    if left:
        FAILURES.append(('nested tags survived', left))

nested_check()

if FAILURES:
    print('\n{} messy-data cases would stop a real run or leak:'.format(len(FAILURES)))
    for label, problems in FAILURES:
        print('  {}: {}'.format(label, problems))
    sys.exit(1)
print('\nno false stops, and nothing left populated')
