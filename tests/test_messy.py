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
