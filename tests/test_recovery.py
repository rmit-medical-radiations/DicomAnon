"""The recovery the failure dialog tells the operator to perform must actually work.

When the mapping file cannot be replaced, the run stops and the message says: rename
the temporary spreadsheet over the real one, keeping a copy of the original, and run
again. Nobody had ever executed that sequence. It is the instruction handed to someone
at the hospital who cannot debug it if it is wrong, and it is the situation that
already happened once, so it is worth a test rather than an argument.

The thing that must survive the recovery is the date offsets. Files written before the
failure are already shifted by them, and a later run that generated fresh ones would
leave that patient's own timeline inconsistent with itself while the earlier files sat
on disk untouched, skipped as already written.
"""
import os, sys, tempfile, shutil, hashlib, datetime as dt
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='recover-'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, pydicom, json
from PyQt6.QtWidgets import QApplication
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage
from DicomAnon import DicomAnonWidget
from _fixtures import save_dicom
from anon_checks import RunVerifier, VerificationError, state_dir_for

SRC, DST, HOME = (os.path.abspath(p) for p in ('rsrc', 'rout', 'rhome'))


def session(day, n=2):
    """One MR series for patient 1234 on the given day."""
    study_uid, series_uid = generate_uid(), generate_uid()
    for i in range(n):
        ds = Dataset()
        ds.PatientID, ds.PatientName = '1234', 'NAME^1234'
        ds.PatientBirthDate, ds.PatientSex = '19550312', 'M'
        ds.Modality = 'MR'
        ds.StudyDate = ds.SeriesDate = day
        ds.StudyTime = ds.SeriesTime = '101500'
        ds.StudyID = 'RMH-' + day
        ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
        ds.SOPInstanceUID = generate_uid()
        ds.SOPClassUID = MRImageStorage
        ds.file_meta = FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        d = os.path.join(SRC, '1234_A', day)
        os.makedirs(d, exist_ok=True)
        save_dicom(ds, os.path.join(d, 'mr{}.dcm'.format(i)))


def written():
    out = {}
    for dirpath, _, names in os.walk(DST):
        for n in names:
            p = os.path.join(dirpath, n)
            out[os.path.relpath(p, DST)] = p
    return out


def digest(path):
    return hashlib.sha1(open(path, 'rb').read()).hexdigest()


def study_dates():
    return sorted({str(pydicom.dcmread(p).StudyDate) for p in written().values()})


for p in (SRC, DST, HOME):
    shutil.rmtree(p, ignore_errors=True)
os.makedirs(DST); os.makedirs(HOME)
pd.DataFrame({'Patient ID': ['1234'],
              'Anonymised ID': ['Brain-0001']}).to_excel('lkr.xlsx', index=False)

app = QApplication(sys.argv[:1])
w = DicomAnonWidget()
w.mapping_file = os.path.join(HOME, 'map.xlsx')
w.state_home = HOME
lookup = w._load_lookup('lkr.xlsx')
tmp = w.mapping_file + '.tmp.xlsx'

real_replace = os.replace


def only_mapping_fails(a, b):
    if str(b).endswith('map.xlsx'):        # the spreadsheet, not the state file
        raise PermissionError(13, 'locked by another process')
    return real_replace(a, b)


print('=== run 1: the patient is anonymised, then the mapping cannot be saved ===')
session('20210801')
w.verifier = RunVerifier()
os.replace = only_mapping_fails
try:
    w.process_folder(SRC, DST, w._read_mapping(w.mapping_file), lookup)
except VerificationError as e:
    failure = str(e)
else:
    raise AssertionError('the failing mapping write did not stop the run')
finally:
    os.replace = real_replace

after1 = written()
print('  files written before it stopped :', len(after1))
assert after1, 'the run stopped before writing anything, so there is nothing to recover'
assert not os.path.isfile(w.mapping_file), 'the mapping file should not exist yet'
print('  real mapping file exists        :', os.path.isfile(w.mapping_file))
print('  temporary spreadsheet kept      :', os.path.isfile(tmp))
assert os.path.isfile(tmp), 'the only up-to-date copy of the mapping was deleted'

# The message has to carry the underlying OS error. Without it the operator forwards a
# sentence we wrote ourselves and the cause stays unknown, which is exactly what the
# last incident cost. Nothing asserted this before, so a refactor could drop it in
# silence, the same way a mistyped keyword sat in IDENTIFYING_KEYWORDS for months.
print('\n=== the failure message carries the evidence ===')
assert 'locked by another process' in failure, failure[:300]
print('  underlying OS error included    : True')
assert os.path.normpath(tmp) in failure, failure[:300]
print('  path of the kept copy included  : True')

state_path = os.path.join(state_dir_for(DST, HOME), 'Brain-0001.json')
offsets_in_state = tuple(json.load(open(state_path))['offsets'])
shifted1 = study_dates()
print('\n  offsets recorded in state       :', offsets_in_state)
print('  session 1 shifted study date    :', shifted1)

print('\n=== the operator does what the dialog told them to do ===')
real_replace(tmp, w.mapping_file)          # "rename that second file over the first"
recovered = w._read_mapping(w.mapping_file)
assert recovered is not None, 'the recovered file could not be read back'
row = recovered.loc[recovered['patient_id'] == 1234]
assert len(row) == 1, 'the recovered mapping does not name the patient'
offsets_in_mapping = (int(row.iloc[0]['date_offset_days']),
                      int(row.iloc[0]['time_offset_seconds']))
print('  mapping reads back              : {} row(s)'.format(len(recovered)))
print('  folder assignment recorded      :', row.iloc[0]['anon_patient_dir_name'])
print('  offsets in the recovered file   :', offsets_in_mapping)
assert offsets_in_mapping == offsets_in_state, 'the two records of the offsets disagree'
print('  they match the ones in state    : True')

print('\n=== run 2: a later session is added, as the oncologist actually works ===')
before = {rel: digest(p) for rel, p in after1.items()}
session('20210901')                        # 31 days after session 1
w2 = DicomAnonWidget()
w2.mapping_file = w.mapping_file
w2.state_home = HOME
w2.verifier = RunVerifier()
m, _, _ = w2.process_folder(SRC, DST, w2._read_mapping(w2.mapping_file), lookup)
w2._save_mapping(m, w2.mapping_file)

after2 = written()
print('  files in the destination        :', len(after2))
unchanged = all(digest(after2[rel]) == d for rel, d in before.items())
print('  run 1 files byte-identical      :', unchanged)
assert unchanged, 'the recovery rewrote files that were already correct'

dates = study_dates()
gap = (dt.datetime.strptime(dates[1], '%Y%m%d')
       - dt.datetime.strptime(dates[0], '%Y%m%d')).days
print('  shifted study dates             :', dates)
print('  real gap 31 days, shifted gap   :', gap)
assert gap == 31, 'the second session was shifted by a different offset from the first'
assert dates[0] == shifted1[0], 'session 1 moved during the second run'

final = w2._read_mapping(w2.mapping_file)
frow = final.loc[final['patient_id'] == 1234].iloc[0]
assert (int(frow['date_offset_days']), int(frow['time_offset_seconds'])) == offsets_in_mapping
print('  offsets unchanged after run 2   : True')
assert not os.path.isfile(tmp), 'a temporary file was left behind by a successful run'
print('  no temporary file left behind   : True')

print('\n=== a failed save must not damage the mapping that is already there ===')
# The dialog tells the operator "nothing was lost". That is only true if the existing
# spreadsheet survives untouched, which is the point of writing to a temporary file and
# swapping. Run 1 above had no mapping to damage, so this is the case that checks it.
good = digest(w2.mapping_file)
w3 = DicomAnonWidget()
w3.mapping_file = w2.mapping_file
w3.state_home = HOME
os.replace = only_mapping_fails
start = dt.datetime.now()
try:
    w3._save_mapping(pd.DataFrame([{'patient_id': 5678}]), w3.mapping_file)
except VerificationError:
    pass
else:
    raise AssertionError('a permanently failing replace did not stop the run')
finally:
    os.replace = real_replace
elapsed = (dt.datetime.now() - start).total_seconds()

print('  existing mapping untouched      :', digest(w3.mapping_file) == good)
assert digest(w3.mapping_file) == good, 'a failed save damaged the mapping already on disk'
survivor = w3._read_mapping(w3.mapping_file)
assert len(survivor.loc[survivor['patient_id'] == 1234]) == 1, 'the earlier patient was lost'
print('  and still names patient 1234    : True')

# It has to give up rather than block the window forever. Six attempts at half a second
# is the intent; anything past a few seconds looks to the operator like the hang that
# started all of this.
print('  gave up after                   : {:.1f} s'.format(elapsed))
assert elapsed < 15, 'the retry took too long to give up: {:.1f} s'.format(elapsed)
assert os.path.isfile(tmp), 'the kept copy is missing after the retries were exhausted'
print('  kept copy still present         : True')
real_replace(tmp, tmp + '.done')          # tidy up so nothing dangles

print('\nthe documented recovery works: renaming the kept copy into place preserves '
      'the offsets,\nand the patient timeline stays consistent across the failure')
