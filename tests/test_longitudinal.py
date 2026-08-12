"""Three anonymising sessions, RT objects referencing earlier studies across runs.

Closest thing to the real workflow: the hospital exports only the new session each
time, and a structure set drawn in a later session points back at a series that was
anonymised weeks earlier and is no longer in the source folder at all.
"""
import os, sys, shutil, json, datetime as dt
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import os, sys, tempfile
# Run from a throwaway directory so a test can never touch the real output folder,
# the real ID mapping file, or the real state under the home folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='dicomanon-test-'))
import pandas as pd, pydicom
from PyQt6.QtWidgets import QApplication
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import (generate_uid, ExplicitVRLittleEndian, MRImageStorage,
                         RTStructureSetStorage)
from DicomAnon import DicomAnonWidget
from anon_checks import RunVerifier, VerificationError

SRC, DST, HOME = (os.path.abspath(p) for p in ('lsrc', 'lout', 'lhome'))
SPATIAL_REG = '1.2.840.10008.5.1.4.1.1.66.1'

def meta(ds, sop_class):
    ds.SOPClassUID = sop_class
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = sop_class
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    return ds

def save(ds, folder, session, name):
    d = os.path.join(SRC, folder, session); os.makedirs(d, exist_ok=True)
    ds.save_as(os.path.join(d, name), enforce_file_format=True)

def patient_bits(ds, pid, day):
    ds.PatientID, ds.PatientName = pid, 'NAME^' + pid
    ds.PatientBirthDate, ds.PatientSex, ds.PatientAge = '19550312', 'M', '066Y'
    ds.StudyDate = ds.SeriesDate = ds.ContentDate = day
    ds.StudyTime = ds.SeriesTime = ds.ContentTime = '101500'
    ds.StudyID = 'RMH-' + day

def mr_session(folder, pid, day, for_uid, n=3):
    """One MR series. Returns (study_uid, series_uid, [sop_uids])."""
    study_uid, series_uid = generate_uid(), generate_uid()
    sops = []
    for i in range(n):
        ds = Dataset(); patient_bits(ds, pid, day)
        ds.Modality = 'MR'
        ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
        ds.SOPInstanceUID = generate_uid()
        ds.FrameOfReferenceUID = for_uid
        ds.SeriesDescription = '{}101500-T2Brain'.format(day)
        save(meta(ds, MRImageStorage), folder, day, 'mr{}.dcm'.format(i))
        sops.append(str(ds.SOPInstanceUID))
    return study_uid, series_uid, sops

def rtstruct(folder, pid, day, for_uid, ref_study, ref_series, ref_sops):
    """A structure set drawn on an EARLIER session's series."""
    ds = Dataset(); patient_bits(ds, pid, day)
    ds.Modality = 'RTSTRUCT'
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.StructureSetDate, ds.StructureSetTime = day, '113000'
    contours = Sequence()
    for sop in ref_sops:
        c = Dataset(); c.ReferencedSOPClassUID = MRImageStorage
        c.ReferencedSOPInstanceUID = sop
        contours.append(c)
    series = Dataset(); series.SeriesInstanceUID = ref_series
    series.ContourImageSequence = contours
    study = Dataset(); study.ReferencedSOPClassUID = MRImageStorage
    study.ReferencedSOPInstanceUID = ref_study
    study.RTReferencedSeriesSequence = Sequence([series])
    frame = Dataset(); frame.FrameOfReferenceUID = for_uid
    frame.RTReferencedStudySequence = Sequence([study])
    ds.ReferencedFrameOfReferenceSequence = Sequence([frame])
    save(meta(ds, RTStructureSetStorage), folder, day, 'struct.dcm')
    return str(ds.SOPInstanceUID)

def registration(folder, pid, day, fixed_for, moving_for):
    """A registration matching two sessions by frame of reference."""
    ds = Dataset(); patient_bits(ds, pid, day)
    ds.Modality = 'REG'
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.FrameOfReferenceUID = fixed_for
    items = Sequence()
    for f in (fixed_for, moving_for):
        r = Dataset(); r.FrameOfReferenceUID = f
        items.append(r)
    ds.RegistrationSequence = items
    save(meta(ds, SPATIAL_REG), folder, day, 'reg.dcm')

def read_out():
    out = {}
    for dirpath, _, names in os.walk(DST):
        for n in names:
            p = os.path.join(dirpath, n)
            out[os.path.relpath(p, DST)] = pydicom.dcmread(p)
    return out

def all_uids(ds):
    got = set()
    for e in ds.iterall():
        if e.VR == 'UI' and not (e.keyword or '').endswith('SOPClassUID') and e.value:
            got.add(str(e.value))
    return got

for p in (SRC, DST, HOME):
    shutil.rmtree(p, ignore_errors=True)
os.makedirs(DST); os.makedirs(HOME)
pd.DataFrame({'Patient ID': ['1234', '5678'],
              'Anonymised ID': ['Brain-0001', 'Brain-0002']}).to_excel('lk5.xlsx', index=False)

app = QApplication(sys.argv[:1]); w = DicomAnonWidget()
w.mapping_file = os.path.join(HOME, 'map.xlsx'); w.state_home = HOME
lookup = w._load_lookup('lk5.xlsx')

def run(label):
    w.verifier = RunVerifier()
    m, missing = w.process_folder(SRC, DST, w._read_mapping(w.mapping_file), lookup)
    w._save_mapping(m, w.mapping_file)
    print('  {}: {} files in the destination'.format(label, len(read_out())))
    return m

FOR_A = generate_uid()          # patient 1234's frame of reference, stable across sessions
FOR_B = generate_uid()

print('=== session 1 (run 1): patient 1234 baseline MR ===')
s1_study, s1_series, s1_sops = mr_session('1234_A', '1234', '20210801', FOR_A)
run('run 1')
after1 = read_out()

print('\n=== session 2 (run 2): only the new session is exported ===')
shutil.rmtree(os.path.join(SRC, '1234_A', '20210801'))     # hospital exports new data only
s2_study, s2_series, s2_sops = mr_session('1234_A', '1234', '20210815', FOR_A)
registration('1234_A', '1234', '20210815', FOR_A, FOR_A)
# a new patient joins the delivery at this point
mr_session('5678_B', '5678', '20210815', FOR_B)
run('run 2')

print('\n=== session 3 (run 3): structure set drawn on SESSION 1 series ===')
shutil.rmtree(os.path.join(SRC, '1234_A', '20210815'))
shutil.rmtree(os.path.join(SRC, '5678_B'))
mr_session('1234_A', '1234', '20210902', FOR_A)
struct_sop = rtstruct('1234_A', '1234', '20210902', FOR_A, s1_study, s1_series, s1_sops)
run('run 3')
out = read_out()

print('\n=== every reference resolves to a file actually in the destination ===')
written_sops = {str(ds.SOPInstanceUID) for ds in out.values()}
written_series = {str(ds.SeriesInstanceUID) for ds in out.values()}
struct = [ds for ds in out.values() if ds.Modality == 'RTSTRUCT'][0]
frame = struct.ReferencedFrameOfReferenceSequence[0]
study = frame.RTReferencedStudySequence[0]
series = study.RTReferencedSeriesSequence[0]
refs = [str(c.ReferencedSOPInstanceUID) for c in series.ContourImageSequence]
print('  structure set references {} images from session 1'.format(len(refs)))
dangling = [r for r in refs if r not in written_sops]
assert not dangling, 'dangling image references: {}'.format(dangling)
print('  all resolve to files written in RUN 1, three runs earlier')
assert str(series.SeriesInstanceUID) in written_series, 'dangling series reference'
print('  referenced SeriesInstanceUID resolves too')

session1_files = {k: v for k, v in out.items() if '20210801' in k}
assert {str(v.SOPInstanceUID) for v in session1_files.values()} == set(refs), 'wrong targets'
print('  and they point at the session 1 files specifically, not some other series')

print('\n=== frame of reference is stable across all three sessions ===')
fors = {str(ds.FrameOfReferenceUID) for k, ds in out.items()
        if k.startswith('Brain-0001') and 'FrameOfReferenceUID' in ds}
print('  patient 1234 distinct FrameOfReferenceUIDs across 3 sessions: {}'.format(len(fors)))
assert len(fors) == 1
reg = [ds for ds in out.values() if ds.Modality == 'REG'][0]
assert {str(i.FrameOfReferenceUID) for i in reg.RegistrationSequence} == fors
print('  the registration still matches it')

print('\n=== the two patients share nothing ===')
a = set().union(*[all_uids(v) for k, v in out.items() if k.startswith('Brain-0001')])
b = set().union(*[all_uids(v) for k, v in out.items() if k.startswith('Brain-0002')])
print('  overlapping UIDs between Brain-0001 and Brain-0002: {}'.format(len(a & b)))
assert not (a & b)

print('\n=== source UIDs never leak into the output ===')
source_uids = {str(s1_study), str(s1_series), FOR_A, FOR_B, struct_sop, *s1_sops, *s2_sops}
leaked = source_uids & set().union(a, b)
assert not leaked, leaked
print('  none of the {} source UIDs appear anywhere in the output'.format(len(source_uids)))

print('\n=== study numbering and intervals across three runs ===')
labels = sorted({str(v.StudyID) for k, v in out.items() if k.startswith('Brain-0001')})
print('  StudyIDs for Brain-0001:', labels)
dates = sorted({str(v.StudyDate) for k, v in out.items()
                if k.startswith('Brain-0001') and v.Modality == 'MR'})
gaps = [(dt.datetime.strptime(dates[i+1], '%Y%m%d')
         - dt.datetime.strptime(dates[i], '%Y%m%d')).days for i in range(len(dates)-1)]
print('  real gaps 14 and 18 days; shifted gaps {}'.format(gaps))
assert gaps == [14, 18]
print('\nall longitudinal tests passed')
