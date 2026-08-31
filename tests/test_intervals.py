"""Intervals between a patient's studies, measured across every date element.

The existing date tests check StudyDate, in whole days, and give every session the SAME
time of day. That makes them blind to the whole class of fault below by construction: if
two sessions share a time of day, the time offset carries them past midnight together,
so their dates stay in step whatever the code does. Every session here therefore has a
DIFFERENT time of day, and one sits late enough in the evening that the forced offset
carries it into the next day.

What this pins down:

  1. a file agrees with itself. Dates that were equal in the source come out equal, even
     when some have a time beside them and some do not;
  2. an interval survives even when a date is paired with its time in one session and
     bare in the next, which is real: the export carries AcquisitionDate on 40% of
     series but AcquisitionTime on only 37%;
  3. the carry reaches into sequences and into a timestamp embedded in free text;
  4. the documented limitation, that a gap measured from dates ALONE can differ by a day
     while the instant is exact, so that nobody later mistakes it for this bug returning.

Offsets are forced rather than random. new_offsets() picks a random time of day, so a
random run would exercise the wrap only sometimes, and a test that checks the hard case
only sometimes is not a test.
"""
import os, sys, tempfile, datetime as dt
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='intervals-'))
from PyQt6.QtWidgets import QApplication
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.uid import generate_uid
from DicomAnon import DicomAnonWidget
from anon_checks import shift_dates, _reference_carry

# 3600 seconds, so anything from 23:00 carries into the next day and anything earlier
# does not. Both sides of the wrap are needed, and a random offset gives neither
# reliably.
OFFSETS = (-100, 3600)


def make(day, time, acq_time=True, content_time=True):
    """One file. acq_time/content_time control whether a date has a time beside it."""
    ds = Dataset()
    ds.PatientID, ds.PatientName = '1234', 'SMITH^JOHN'
    ds.PatientBirthDate, ds.PatientSex = '19550312', 'M'
    ds.StudyDate = ds.SeriesDate = ds.AcquisitionDate = ds.ContentDate = day
    ds.StudyTime = ds.SeriesTime = time
    if acq_time:
        ds.AcquisitionTime = time
    if content_time:
        ds.ContentTime = time
    ds.AcquisitionDateTime = day + time
    ds.SeriesDescription = day + time + '-1ABrain'      # 14 digits: a whole instant
    ds.StudyDescription = day + '-BRAIN WITH CONTRAST'  # 8 digits: a bare date
    ds.StudyID = 'RMH-4471'
    ds.StudyInstanceUID = generate_uid()
    item = Dataset()
    item.StructureSetDate = day          # bare date inside a sequence, no time beside it
    ds.RequestAttributesSequence = Sequence([item])
    return ds


def dates(ds):
    return {
        'StudyDate': str(ds.StudyDate),
        'SeriesDate': str(ds.SeriesDate),
        'AcquisitionDate': str(ds.AcquisitionDate),
        'ContentDate': str(ds.ContentDate),
        'StructureSetDate': str(ds.RequestAttributesSequence[0].StructureSetDate),
        'SeriesDescription': str(ds.SeriesDescription)[:8],
        'StudyDescription': str(ds.StudyDescription)[:8],
        'AcquisitionDateTime': str(ds.AcquisitionDateTime)[:8],
    }


def day_gap(a, b, keyword):
    return (dt.datetime.strptime(dates(b)[keyword], '%Y%m%d')
            - dt.datetime.strptime(dates(a)[keyword], '%Y%m%d')).days


def instant(ds):
    return dt.datetime.strptime(str(ds.StudyDate) + str(ds.StudyTime), '%Y%m%d%H%M%S')


app = QApplication(sys.argv[:1])
w = DicomAnonWidget()


print('=== the reference time decides the carry, once per file ===')
print('  offset seconds {}, so 23:00 and later carries'.format(OFFSETS[1]))
for time, expected in (('093000', 0), ('225959', 0), ('230000', 1), ('233000', 1)):
    ds = make('20210815', time)
    carry = _reference_carry(ds, OFFSETS[1])
    print('  StudyTime {} -> carry {}'.format(time, carry))
    assert carry == expected, (time, carry, expected)

print('\n  StudyTime wins over a TM that sorts before it')
for study_time, creation_time, expected in (('233000', '093000', 1),
                                            ('093000', '233000', 0)):
    ds = make('20210815', study_time)
    ds.InstanceCreationTime = creation_time        # (0008,0013), before StudyTime
    carry = _reference_carry(ds, OFFSETS[1])
    print('  StudyTime {} with InstanceCreationTime {} -> carry {}'.format(
        study_time, creation_time, carry))
    assert carry == expected, (study_time, creation_time, carry, expected)

print('\n  a DT is the last resort when there is no TM at all')
for time, expected in (('093000', 0), ('233000', 1)):
    ds = Dataset()
    ds.StudyDate = '20210815'
    ds.AcquisitionDateTime = '20210815' + time
    carry = _reference_carry(ds, OFFSETS[1])
    print('  AcquisitionDateTime ...{} -> carry {}'.format(time, carry))
    assert carry == expected, (time, carry, expected)

print('\n  a file with no time at all has nothing to reason from')
bare = Dataset()
bare.StudyDate = '20210815'
assert _reference_carry(bare, OFFSETS[1]) == 0
print('  carry 0, the old whole-day behaviour')


print('\n=== 1. a file agrees with itself when the offset wraps ===')
# Every date is 20210815 in the source. StudyDate and SeriesDate have a time beside
# them; AcquisitionDate, ContentDate and the one in the sequence do not.
ds = make('20210815', '233000', acq_time=False, content_time=False)
before = dates(ds)
assert len(set(before.values())) == 1, before
w.anonymise_dicom(ds=ds, anon_name='Brain-0001', offsets=OFFSETS)
after = dates(ds)
for keyword, value in sorted(after.items()):
    print('  {:<22} {} -> {}'.format(keyword, before[keyword], value))
assert len(set(after.values())) == 1, (
    'dates identical in the source came out on different days: {}'.format(after))
print('  all {} dates still agree'.format(len(after)))


print('\n=== 2. an interval survives a date paired in one session and bare in the next ===')
# The real case: AcquisitionDate is on 40% of series in the export and AcquisitionTime
# on 37%, so a patient can easily have one session with the time and one without.
a = make('20210801', '233000', acq_time=True)
b = make('20210815', '233000', acq_time=False)
print('  source AcquisitionDate 20210801 and 20210815, 14 days apart')
print('  session 1 has AcquisitionTime, session 2 does not')
for each in (a, b):
    w.anonymise_dicom(ds=each, anon_name='Brain-0001', offsets=OFFSETS)
for keyword in ('StudyDate', 'AcquisitionDate', 'ContentDate', 'StructureSetDate',
                'SeriesDescription', 'StudyDescription', 'AcquisitionDateTime'):
    gap = day_gap(a, b, keyword)
    print('  {:<22} gap {} days'.format(keyword, gap))
    assert gap == 14, '{} gap moved from 14 to {}'.format(keyword, gap)
print('  every element kept the 14 day gap, sequence and free text included')


print('\n=== 3. sessions at different times of day, both sides of the wrap ===')
# 09:12 does not carry, 23:50 does. Nothing here shares a time of day, which is exactly
# what the older date tests never varied.
PLAN = [('20210801', '091233'), ('20210815', '235010'),
        ('20210902', '070500'), ('20211130', '164459')]
files = [make(day, time) for day, time in PLAN]
source_instants = [instant(f) for f in files]
for each in files:
    w.anonymise_dicom(ds=each, anon_name='Brain-0001', offsets=OFFSETS)
output_instants = [instant(f) for f in files]

source_gaps = [source_instants[i + 1] - source_instants[i] for i in range(3)]
output_gaps = [output_instants[i + 1] - output_instants[i] for i in range(3)]
print('  source instant gaps: {}'.format([str(g) for g in source_gaps]))
print('  output instant gaps: {}'.format([str(g) for g in output_gaps]))
assert source_gaps == output_gaps, 'the true interval between studies moved'

print('\n  and every file still agrees with itself')
for each, (day, time) in zip(files, PLAN):
    values = dates(each)
    assert len(set(values.values())) == 1, (day, time, values)
print('  all four do, across both sides of the wrap')


print('\n=== 4. the documented limitation, pinned so it is not mistaken for the bug ===')
# A gap measured from dates ALONE can differ by a day, because the offset is not a whole
# number of days and the two studies fall either side of the wrap. The instant is exact.
# Fixing this would mean giving up either the time shift or a file agreeing with itself.
early, late = make('20210801', '093000'), make('20210815', '233000')
for each in (early, late):
    w.anonymise_dicom(ds=each, anon_name='Brain-0001', offsets=OFFSETS)
date_only = day_gap(early, late, 'StudyDate')
true_gap = instant(late) - instant(early)
print('  gap from StudyDate alone : {} days (source says 14)'.format(date_only))
print('  gap from date and time   : {} (source says 14 days, 14:00:00)'.format(true_gap))
assert date_only == 15, 'expected the known one day artefact, got {}'.format(date_only)
assert true_gap == dt.timedelta(days=14, hours=14), true_gap
print('  the instant is exact; only the date-only reading moves, and only by a day')

print('\nall interval tests passed')
