"""Verification shared by the anonymiser and the console check (defect 5).

Imports nothing but pydicom and the standard library, deliberately: DicomAnon.py
imports this inside a frozen PyQt6 app that runs at the hospital, and
check-anon-output.py imports it from a plain Python install at the university. Keeping
PyQt6 and pandas out of here is what lets one copy of the logic serve both.

The two ends are not equivalent, and the difference is the point:

    In the app, at the hospital, the SOURCE PatientID is still there. Checking that one
    source patient's files go to exactly one anon folder, and that one anon folder
    receives exactly one source patient, is a direct test of defect 6. Nothing
    downstream can do this, because anonymise_dicom overwrites the evidence.

    After the fact, at the university, that evidence is gone. All that survives is birth
    year and sex, which is a proxy: it cannot see two patients of the same sex born in
    the same year. Use it because it is all there is out there, not because it is good.

IDENTIFYING_KEYWORDS lives here rather than in DicomAnon.py so that both ends blank and
check the same list, and so validate_keywords() can be run against it. That check found
defect 7: an entry that is not a real DICOM keyword can never satisfy `if kw in ds`, so
it blanks nothing and the tag survives in every file ever written.
"""
import collections
import datetime
import hashlib
import json
import os
import re
import secrets

from pydicom.datadict import tag_for_keyword

# Bumped whenever a change alters what the anonymiser WRITES. A patient whose folder was
# written by an older version cannot have new files added beside the old ones (defect 4),
# so this is compared against the version recorded in that patient's state.
#
# This is not the release version and is not expected to track it. Bumping it forces
# every patient's folder to be produced again, so it must only change when the output
# actually changes: v0.9 moved pydicom from 2.4.3 to 3.0.2 and left this at 0.8, because
# the two versions were measured to write byte-identical files.
#
# The per-file date carry was bumped to 0.9 and then put back, which is worth recording
# so nobody bumps it again for the same reason. It does change the bytes: a bare DA, one
# with no TM beside it, moves by offset_days plus the file's carry rather than
# offset_days alone. But measured against 12465 real source files, StudyDate carries a
# StudyTime in 100% of them, so it is paired, never bare, and never affected. The bare
# dates that do exist are PatientBirthDate (flattened to 1 January straight afterwards,
# so only a year boundary shows), a private tag (removed four lines later), and
# AcquisitionDate in 16 files. A byte comparison with an offset chosen to force the
# carry left 898 of 900 real files identical. Forcing every patient folder to be
# produced again for that is the expensive no-op the pydicom entry warns about.
TOOL_VERSION = '0.8'

STUDY_ID_RE = re.compile(r'STUDY_\d+$')

# Walk these by VR rather than by keyword, for the same reason the UID remapping walks
# by VR: a keyword list silently misses whatever nobody thought of, and defect 1 is what
# that looks like after a year in production.
DATE_VRS = ('DA', 'TM', 'DT')

# A date or a full timestamp embedded in free text, e.g. the SeriesDescription
# '20210819134732-1ABrain'. Both widths are needed: matching only 8 digits misses the
# timestamp entirely, because the date part is followed by more digits.
EMBEDDED_DATE_RE = re.compile(r'(?<!\d)(\d{14}|\d{8})(?!\d)')
TEXT_VRS = ('SH', 'LO', 'ST', 'LT', 'UT', 'UC')

# Identifying attributes to blank/remove (excluding PatientName/PatientID)
IDENTIFYING_KEYWORDS = {
    # Patient (except PatientName, PatientID)
    "OtherPatientIDs",
    "OtherPatientNames",
    "PatientBirthName",
    "PatientMotherBirthName",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "PatientInsurancePlanCodeSequence",
    "PatientComments",
    "EthnicGroup",
    "Occupation",
    "AdditionalPatientHistory",
    "PatientReligiousPreference",

    # General person/organization
    "ResponsiblePerson",
    "ResponsiblePersonRole",
    "PersonName",
    "PerformingPhysicianName",
    "ReferringPhysicianName",
    "ReferringPhysicianAddress",
    "ReferringPhysicianTelephoneNumbers",
    "RequestingPhysician",
    "OperatorsName",
    "PhysiciansOfRecord",
    # Was "PhysiciansReadingStudy", which is not a DICOM keyword and blanked nothing
    # in every release up to v0.7. See defect 7 in CLAUDE.md.
    "NameOfPhysiciansReadingStudy",

    # Institution / contact info
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",
    "DeviceSerialNumber",
    "SoftwareVersions",

    # Study / scheduling / admin IDs
    "AccessionNumber",
    "IssuerOfPatientID",
    "IssuerOfAccessionNumberSequence",
    "RequestingService",
    "AdmissionID",
    # "PatientAccountNumber" was here and is not a DICOM keyword either, but unlike the
    # one above it matches nothing in the dictionary, so which tag was meant is unknown.
    # Dropped rather than guessed; see defect 7 in CLAUDE.md.
    "InsurancePlanIdentification",
    "VisitComments",
    "ScheduledProcedureStepDescription",
    "RequestedProcedureDescription",
    "RequestedProcedureID",
    "RequestedProcedureLocation",

    # Free-text descriptions
    "ProtocolName",
    "PerformedProcedureStepDescription",
    "StudyComments",

    # Addresses / geographic
    "CountryOfResidence",
    "RegionOfResidence",
}


class VerificationError(Exception):
    """Raised to stop a run. CLAUDE.md defect 5: fail loudly rather than carry on."""


def validate_keywords(keywords=None):
    """Entries that no DICOM tag answers to, and so blank nothing at all."""
    if keywords is None:
        keywords = IDENTIFYING_KEYWORDS
    return sorted(k for k in keywords if tag_for_keyword(k) is None)


def new_offsets():
    """A fresh (days, seconds) offset for one patient.

    Random, and stored in the ID mapping file rather than compiled in, because the old
    behaviour shifted StudyDate by a hard-coded 30 days in a public repository. Anyone
    could read the constant and undo the shift, which made the shift decorative.

    Per patient, not per run: two patients sharing an offset lets their timelines be
    lined up against each other. Because it is stored, a later run for the same patient
    reuses it, so the oncologist's added studies keep their true spacing from the
    earlier ones.

    Shifted backwards by one to ten years, so no study lands in the future.
    """
    return -(365 + secrets.randbelow(3285)), secrets.randbelow(86400)


def shift_da(value, offset_days):
    """YYYYMMDD, shifted. Empty if it will not parse, since a date we cannot shift is a
    date we cannot leave in place either."""
    text = str(value).strip()
    if not text:
        return value
    try:
        shifted = (datetime.datetime.strptime(text[:8], '%Y%m%d').date()
                   + datetime.timedelta(days=offset_days))
    except ValueError:
        return ''
    return shifted.strftime('%Y%m%d')


def shift_tm(value, offset_seconds):
    """HHMMSS[.ffffff], shifted within the day, fractional seconds preserved.

    Only reached for a TM with no DA beside it: shift_dates pairs the two and shifts
    them as one instant wherever it can, so this is the leftover case. Such a time wraps
    within its day, having no date of its own to carry. The offset is constant, so
    intervals between two times survive except across the single wrap point.
    """
    text = str(value).strip()
    if not text:
        return value
    head, _, frac = text.partition('.')
    if not head.isdigit() or len(head) not in (2, 4, 6):
        return ''
    head = head.ljust(6, '0')
    try:
        seconds = (int(head[0:2]) * 3600 + int(head[2:4]) * 60 + int(head[4:6])
                   + offset_seconds) % 86400
    except ValueError:
        return ''
    shifted = '{:02d}{:02d}{:02d}'.format(
        seconds // 3600, (seconds % 3600) // 60, seconds % 60)
    return '{}.{}'.format(shifted, frac) if frac else shifted


def shift_dt(value, offset_days, offset_seconds):
    """YYYYMMDDHHMMSS[.ffffff][&ZZXX], shifted. Timezone suffix preserved."""
    text = str(value).strip()
    if not text:
        return value
    zone = ''
    for sign in ('+', '-'):
        idx = text.find(sign, 8)
        if idx != -1:
            text, zone = text[:idx], text[idx:]
            break
    body, _, frac = text.partition('.')
    if len(body) < 8 or not body.isdigit():
        return ''
    body = body.ljust(14, '0')
    try:
        moment = (datetime.datetime.strptime(body, '%Y%m%d%H%M%S')
                  + datetime.timedelta(days=offset_days, seconds=offset_seconds))
    except ValueError:
        return ''
    out = moment.strftime('%Y%m%d%H%M%S')
    if frac:
        out = '{}.{}'.format(out, frac)
    return out + zone


def shift_text_dates(text, offset_days, offset_seconds=0, carry=0):
    """Shift a date or timestamp embedded in free text.

    SeriesDescription carried a full timestamp on 2% of the series in the export, e.g.
    '20210819134732-1ABrain'. Shifting it keeps the description readable and keeps its
    ordering, while removing the lookup key. Only runs that parse as a real date are
    touched, so an eight digit accession number is left alone.

    A fourteen digit run is a whole instant and shifts exactly. An eight digit run is a
    bare date with no time to carry it past midnight, so it takes the file's carry, the
    same as any other bare DA. See _reference_carry.
    """
    def replace(match):
        run = match.group(1)
        if len(run) == 14:
            return shift_dt(run, offset_days, offset_seconds) or run
        return shift_da(run, offset_days + carry) or run

    return EMBEDDED_DATE_RE.sub(replace, str(text))


def shift_moment(date_text, time_text, offset_days, offset_seconds):
    """Shift a (DA, TM) pair as one instant. Returns (date, time), or None if unparsable.

    DICOM splits an instant across two elements, so shifting them separately puts them a
    day out of step whenever the time offset carries past midnight: StudyDate would land
    on the 3rd while AcquisitionDateTime, a DT holding the same instant, landed on the
    4th. Pairs are shifted together to keep a file agreeing with itself.
    """
    date_text, time_text = str(date_text).strip(), str(time_text).strip()
    head, _, frac = time_text.partition('.')
    if not head.isdigit() or len(head) not in (2, 4, 6):
        return None
    head = head.ljust(6, '0')
    try:
        moment = (datetime.datetime.strptime(
            '{}{}'.format(date_text[:8], head), '%Y%m%d%H%M%S')
            + datetime.timedelta(days=offset_days, seconds=offset_seconds))
    except ValueError:
        return None
    shifted_time = moment.strftime('%H%M%S')
    return (moment.strftime('%Y%m%d'),
            '{}.{}'.format(shifted_time, frac) if frac else shifted_time)


def blank_identifying_tags(ds):
    """Blank every identifying tag, including inside nested sequences.

    The tags are looked up by keyword, but the walk is by traversal, so a keyword
    appearing inside RequestAttributesSequence or OriginalAttributesSequence is caught
    as well as one at the top level. Real hospital data puts them in both.
    """
    for elem in ds:
        if elem.VR == 'SQ':
            for item in elem.value or []:
                blank_identifying_tags(item)
            if elem.keyword in IDENTIFYING_KEYWORDS:
                elem.value = []
        elif elem.keyword in IDENTIFYING_KEYWORDS:
            elem.value = ''


def populated_identifying_tags(ds):
    """Identifying tags that still hold a value anywhere in the dataset.

    Walks the same way blank_identifying_tags does. The previous version of this check
    used `kw in ds`, the same top-level test the blanking used, so it could only ever
    confirm what the blanking had already done and was blind to everything it missed.
    """
    found = set()
    for elem in ds.iterall():
        if elem.keyword in IDENTIFYING_KEYWORDS:
            value = elem.value
            if elem.VR == 'SQ':
                if value:
                    found.add(elem.keyword)
            elif value is not None and str(value).strip():
                found.add(elem.keyword)
    return sorted(found)


def _pair_keyword(keyword):
    """The TM element that partners a DA element, by name.

    Derived rather than listed, so StructureSetDate/StructureSetTime and
    DateOfLastCalibration/TimeOfLastCalibration both work without anybody enumerating
    them. Same reasoning as walking by VR: a list only covers what was thought of.
    """
    return keyword.replace('Date', 'Time') if 'Date' in keyword else None


def _seconds_of_day(value):
    """A DICOM TM as seconds past midnight, or None if it will not parse as a real time."""
    head = str(value).strip().partition('.')[0]
    if not head.isdigit() or len(head) not in (2, 4, 6):
        return None
    head = head.ljust(6, '0')
    hours, minutes, seconds = int(head[0:2]), int(head[2:4]), int(head[4:6])
    if hours > 23 or minutes > 59 or seconds > 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _reference_carry(ds, offset_seconds):
    """How many days this file's bare dates move, on top of the whole-day offset.

    A DA with a TM beside it is shifted as one instant, so its date carries past
    midnight by itself. A DA with no TM has no instant to carry it, and shifting it by
    whole days alone left it a day behind its own file whenever the time offset wrapped:
    four dates identical in the source came out as two pairs a day apart, and a date
    paired in one session and bare in the next lost a day from the interval between
    them. The carry is therefore decided ONCE per file, from a single reference time,
    and applied to every bare date in it, sequences included.

    StudyTime is the reference because it anchors the study timeline and was present on
    every series in the real export. Failing that, the first other TM in tag order, then
    the time inside a DT. A file with no time at all has nothing to reason from and
    keeps the old whole-day behaviour.

    Note what this does NOT fix: two studies whose times of day fall either side of the
    wrap still get different carries, so a gap measured from dates alone can differ by a
    day from the source. The instant is exact in both, and differencing date with time
    recovers the true interval. Fixing that would mean giving up either the time shift
    or a file agreeing with itself.
    """
    study_time = first_time = first_datetime = None
    for elem in ds:
        values = _values(elem)
        if not values:
            continue
        if elem.VR == 'TM':
            seconds = _seconds_of_day(values[0])
            if seconds is None:
                continue
            if elem.keyword == 'StudyTime':
                study_time = seconds
            elif first_time is None:
                first_time = seconds
        elif elem.VR == 'DT' and first_datetime is None:
            body = str(values[0]).strip().partition('.')[0]
            for sign in ('+', '-'):
                index = body.find(sign, 8)
                if index != -1:
                    body = body[:index]
                    break
            if len(body) > 8 and body.isdigit():
                first_datetime = _seconds_of_day(body[8:14].ljust(6, '0'))

    for reference in (study_time, first_time, first_datetime):
        if reference is not None:
            # Floor division so a negative time offset carries backwards just as
            # cleanly. shift_moment gets the same answer from timedelta arithmetic.
            return (reference + offset_seconds) // 86400
    return 0


def shift_dates(ds, offset_days, offset_seconds, carry=None):
    """Shift every DA, TM and DT element in the dataset and its sequences (defect 1).

    Walks by VR deliberately. The previous behaviour shifted StudyDate alone, which was
    worse than shifting nothing: SeriesDate sat beside it unshifted, so differencing the
    two recovered the offset and undid it everywhere. Either shift the whole timeline or
    do not pretend to.

    Bare dates, the ones with no TM beside them, move by offset_days plus the file's
    carry rather than by offset_days alone, so that every date in a file moves together
    even when the time offset wraps past midnight. See _reference_carry. The carry is
    computed once at the top level and passed down, because a sequence item holding a
    bare date and no time of its own has nothing to compute it from.
    """
    if carry is None:
        carry = _reference_carry(ds, offset_seconds)
    date_offset_days = offset_days + carry

    by_keyword = {}
    for elem in ds:
        if elem.VR in DATE_VRS and elem.keyword:
            by_keyword[elem.keyword] = elem

    handled = set()
    for keyword, elem in by_keyword.items():
        if elem.VR != 'DA' or id(elem) in handled:
            continue
        partner = by_keyword.get(_pair_keyword(keyword) or '')
        if partner is None or partner.VR != 'TM':
            continue
        dates, times = _values(elem), _values(partner)
        if len(dates) != 1 or len(times) != 1 or not str(dates[0]).strip():
            continue
        shifted = shift_moment(dates[0], times[0], offset_days, offset_seconds)
        if shifted is None:
            continue
        elem.value, partner.value = shifted
        handled.update((id(elem), id(partner)))

    for elem in ds:
        if elem.VR == 'SQ':
            for item in elem.value or []:
                shift_dates(item, offset_days, offset_seconds, carry)
            continue
        if id(elem) in handled:
            continue
        values = _values(elem)
        if not values:
            continue
        if elem.VR == 'DA':
            shifted = [shift_da(v, date_offset_days) for v in values]
        elif elem.VR == 'TM':
            shifted = [shift_tm(v, offset_seconds) for v in values]
        elif elem.VR == 'DT':
            shifted = [shift_dt(v, offset_days, offset_seconds) for v in values]
        elif elem.VR in TEXT_VRS:
            shifted = [shift_text_dates(v, offset_days, offset_seconds, carry)
                       if isinstance(v, str) else v for v in values]
            if shifted == values:
                continue
        else:
            continue
        elem.value = shifted if len(shifted) > 1 else shifted[0]


def _values(elem):
    """Element values as a list, whether it is single or multi-valued."""
    value = elem.value
    if value is None:
        return []
    if isinstance(value, (list, tuple)) or type(value).__name__ == 'MultiValue':
        return list(value)
    return [value]


def snapshot_source(ds):
    """Capture what verify_file needs to compare against, before ds is mutated.

    Must be called BEFORE anonymise_dicom, which overwrites all of it.

    Dates are keyed by tag and collected into a set, rather than compared positionally,
    because anonymise_dicom changes the shape of the dataset as well as its values:
    remove_private_tags() deletes elements and blanking an SQ empties its items, so the
    nth element on the way out is not the nth element on the way in.
    """
    uids = set()
    dates = collections.defaultdict(set)
    for elem in ds.iterall():
        if elem.VR == 'UI' and not (elem.keyword or '').endswith('SOPClassUID'):
            uids.update(str(v) for v in _values(elem) if v)
        elif elem.VR in DATE_VRS:
            dates[str(elem.tag)].update(str(v) for v in _values(elem) if str(v).strip())
    birth = str(getattr(ds, 'PatientBirthDate', '') or '')
    return {
        'uids': uids,
        'dates': {k: v for k, v in dates.items()},
        'patient_id': str(getattr(ds, 'PatientID', '') or ''),
        'patient_name': str(getattr(ds, 'PatientName', '') or ''),
        'birth_year': birth[:4],
        'sex': str(getattr(ds, 'PatientSex', '') or ''),
    }


def verify_file(ds, snapshot, anon_name, check_dates=True):
    """Problems with one anonymised dataset. Empty list means it passed.

    This is CLAUDE.md defect 5's assertion list in full, including the date and time
    one, which is on now that defect 1 is fixed. It is the assertion that would have
    caught defect 1 on the first file processed, so it stays on.
    """
    problems = []

    if str(getattr(ds, 'PatientID', '') or '') != anon_name:
        problems.append('PatientID is {!r}, expected {!r}'.format(
            str(getattr(ds, 'PatientID', '') or ''), anon_name))
    if str(getattr(ds, 'PatientName', '') or '') != anon_name:
        problems.append('PatientName is {!r}, expected {!r}'.format(
            str(getattr(ds, 'PatientName', '') or ''), anon_name))

    birth = str(getattr(ds, 'PatientBirthDate', '') or '')
    if len(birth) == 8 and birth[4:] != '0101':
        problems.append('PatientBirthDate {} still carries a month and day'.format(birth))

    study_id = str(getattr(ds, 'StudyID', '') or '')
    if study_id and not STUDY_ID_RE.match(study_id):
        problems.append('StudyID {!r} is not a STUDY_nnnn pseudonym'.format(study_id))

    populated = populated_identifying_tags(ds)
    if populated:
        problems.append('identifying tags still populated: {}'.format(
            ', '.join(populated)))

    source_uids = snapshot['uids']
    for elem in ds.iterall():
        if elem.VR == 'UI' and not (elem.keyword or '').endswith('SOPClassUID'):
            value = elem.value
            values = (value if isinstance(value, (list, tuple))
                      or type(value).__name__ == 'MultiValue' else [value])
            for v in values:
                if v and str(v) in source_uids:
                    problems.append('{} still holds the source UID {}'.format(
                        elem.keyword or elem.tag, v))
                    break

    if any(elem.tag.is_private for elem in ds.iterall()):
        problems.append('private tags were not removed')

    if check_dates:
        problems.extend(_verify_dates(ds, snapshot))

    return problems


def _verify_dates(ds, snapshot):
    """No DA, TM or DT element may still hold a value it had in the source (defect 1).

    Compares against the set of values that tag held in the source, not against a
    positional twin, because anonymise_dicom changes the dataset's shape. A value that
    was not there before is fine even if some other element once held it; what matters
    is that nothing survived where it was.
    """
    originals = snapshot.get('dates')
    if originals is None:
        return ['date verification is on but the snapshot captured no dates']
    problems = []
    for elem in ds.iterall():
        if elem.VR not in DATE_VRS:
            continue
        was = originals.get(str(elem.tag))
        if not was:
            continue
        for value in _values(elem):
            text = str(value).strip()
            if text and text in was:
                problems.append('{} still holds the source value {}'.format(
                    elem.keyword or elem.tag, text))
                break
    return problems


# Anon IDs become folder names, so they have to survive being one on Windows too.
UNSAFE_FOLDER_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_WINDOWS_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    *('COM{}'.format(i) for i in range(1, 10)),
    *('LPT{}'.format(i) for i in range(1, 10)),
}


def check_lookup(pairs):
    """Problems with the ID lookup file, as (hospital id, anon id) pairs in file order.

    The lookup is where the oncologist decides which anon folder a patient gets, and it
    is the single most dangerous input the tool takes. Two hospital IDs sharing one anon
    ID puts two people in one folder. A hospital ID listed twice silently kept the last
    row, because the loader was dict(zip(...)). Neither was detected, and both are how
    the recorded incident could start.

    Returns a list of problems. Anything returned should stop the run: there is no
    partially valid lookup file worth processing.
    """
    problems = []
    seen_hospital = collections.defaultdict(list)
    seen_anon = collections.defaultdict(list)

    for row, (hospital_id, anon_id) in enumerate(pairs, start=2):  # row 1 is the header
        hospital_id = (hospital_id or '').strip()
        anon_id = (anon_id or '').strip()
        if not hospital_id and not anon_id:
            continue
        if not hospital_id:
            problems.append('row {}: no patient ID, but an anonymised ID of {!r}'.format(
                row, anon_id))
            continue
        if not anon_id:
            problems.append('row {}: patient ID {} has no anonymised ID'.format(
                row, hospital_id))
            continue
        if not hospital_id.isdigit():
            problems.append(
                'row {}: patient ID {!r} is not a number. Folder names are read as '
                '<patientID>_<name> with a numeric ID, so this row can never match a '
                'patient folder'.format(row, hospital_id))
        elif hospital_id != str(int(hospital_id)):
            problems.append(
                'row {}: patient ID {!r} has a leading zero. Folder IDs are compared as '
                'numbers, so this row and {!r} would be treated as the same patient'
                .format(row, hospital_id, str(int(hospital_id))))
        if UNSAFE_FOLDER_RE.search(anon_id) or anon_id in ('.', '..'):
            problems.append(
                'row {}: anonymised ID {!r} cannot be used as a folder name'.format(
                    row, anon_id))
        if anon_id.split('.')[0].upper() in RESERVED_WINDOWS_NAMES:
            problems.append(
                'row {}: anonymised ID {!r} is a reserved name on Windows'.format(
                    row, anon_id))
        if anon_id != anon_id.strip() or anon_id.endswith('.'):
            problems.append(
                'row {}: anonymised ID {!r} starts or ends with a space or a dot, which '
                'Windows silently strips from folder names'.format(row, anon_id))
        seen_hospital[hospital_id].append(row)
        seen_anon[anon_id].append(row)

    for hospital_id, rows in sorted(seen_hospital.items()):
        if len(rows) > 1:
            problems.append(
                'patient ID {} appears on rows {}. Only one of them would be used and '
                'the others silently ignored'.format(
                    hospital_id, ', '.join(str(r) for r in rows)))
    for anon_id, rows in sorted(seen_anon.items()):
        if len(rows) > 1:
            problems.append(
                'anonymised ID {!r} is given to more than one patient, on rows {}. '
                'Their studies would all be written into the same folder and given the '
                'same identity'.format(anon_id, ', '.join(str(r) for r in rows)))

    if not seen_hospital:
        problems.append('the lookup file has no usable rows')
    return problems


def compare_patient_id(folder_patient_id, dicom_patient_id):
    """How a folder's ID relates to the PatientID inside its files.

    The folder name decides which anonymised folder a patient is written to, and the
    lookup file is keyed on it, so a misnamed folder sends a patient to somebody else's
    identity. The PatientID in the files is the second, independent witness to who they
    are, and comparing the two is what turns a naming mistake into a caught error rather
    than a silent one.

    Returns 'match', 'differ' or 'incomparable'. Only a numeric PatientID is compared,
    numerically, so a site that prefixes its IDs or pads them differently is reported
    rather than blocked: refusing a run on a format nobody has seen would repeat the
    mistake the duplicate-folder check made.
    """
    dicom = str(dicom_patient_id or '').strip()
    if not dicom or not dicom.isdigit():
        return 'incomparable'
    try:
        return 'match' if int(dicom) == int(folder_patient_id) else 'differ'
    except (TypeError, ValueError):
        return 'incomparable'


def check_assignments(lookup, recorded):
    """Rule 1: a patient's anon folder, once assigned, is permanent.

    lookup and recorded are both {hospital id: anon folder}. The lookup file may only
    ADD patients. If it disagrees with an assignment already recorded in the ID mapping
    file, that is the failure that started the whole incident: the patient gets written
    to a second folder, the first copy stays where it is, and nothing links them.

    Honouring the new value is never right, so this returns problems rather than a
    reconciliation.
    """
    problems = []
    for hospital_id, folder in sorted(recorded.items()):
        current = lookup.get(hospital_id)
        if current is not None and current != folder:
            problems.append(
                'patient {} was previously anonymised into folder {!r}, but the lookup '
                'file now says {!r}. The earlier folder cannot be unwritten, so this '
                'would split one patient across two identities'.format(
                    hospital_id, folder, current))
    claimed = {}
    for hospital_id, folder in sorted(recorded.items()):
        claimed.setdefault(folder, hospital_id)
    for hospital_id, folder in sorted(lookup.items()):
        owner = claimed.get(folder)
        if owner is not None and owner != hospital_id:
            problems.append(
                'the lookup file gives folder {!r} to patient {}, but that folder '
                'already holds patient {}'.format(folder, hospital_id, owner))
    return problems


def state_dir_for(destination_dir, home):
    """Where this destination's state lives. Never inside the destination itself.

    The state holds source UIDs and hospital patient IDs, so it is re-identifying and
    must not travel with the delivery. It is keyed to the destination rather than kept
    loose in the home folder, so pointing the tool at a different output folder cannot
    quietly reuse another delivery's UID maps.
    """
    key = hashlib.sha1(os.path.abspath(destination_dir).encode('utf-8')).hexdigest()[:16]
    return os.path.join(home, '.dicom-anon-state', key)


def load_patient_state(state_dir, anon_folder):
    """This patient's recorded state, or None if they have never been processed here."""
    path = os.path.join(state_dir, '{}.json'.format(anon_folder))
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_patient_state(state_dir, anon_folder, state):
    """Write state through a temporary file, so a crash cannot truncate it.

    Losing this file loses the UID map, which means the next run pseudonymises the same
    source UIDs differently and produces the undetectable duplicates of defect 2.
    """
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, '{}.json'.format(anon_folder))
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, path)


def new_patient_state(anon_folder, patient_id):
    return {
        'anon_folder': anon_folder,
        'patient_id': patient_id,
        'source_patient_ids': [],
        'tool_version': TOOL_VERSION,
        'uid_map': {},
        'study_label_map': {},
        'files': {},
        'permanently_stale': [],
    }


def recorded_owners(state_dir):
    """{source PatientID: anon folder} across every patient recorded for this delivery.

    Seeds RunVerifier so contamination is caught across runs, not just within one. If a
    whole folder is filled from the wrong source patient there is no within-run conflict
    to notice, and this is what catches it.
    """
    owners = {}
    if not os.path.isdir(state_dir):
        return owners
    for name in sorted(os.listdir(state_dir)):
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(state_dir, name)) as f:
                state = json.load(f)
        except (OSError, ValueError):
            continue
        for source_id in state.get('source_patient_ids', []):
            owners[str(source_id)] = state.get('anon_folder', name[:-5])
    return owners


def unrecorded_folders(destination_dir, state_dir):
    """Anon folders holding files that no state file accounts for.

    On a destination written before state tracking existed, that is all of them. Those
    files were produced by a build with none of the current checks, and rule 4 says new
    files at the current version must never be written beside them. There is no way to
    reconstruct their UID maps or offsets after the fact, so the only correct answer is
    a fresh destination.
    """
    if not os.path.isdir(destination_dir):
        return []
    recorded = set()
    if os.path.isdir(state_dir):
        recorded = {n[:-5] for n in os.listdir(state_dir) if n.endswith('.json')}
    unrecorded = []
    for name in sorted(os.listdir(destination_dir)):
        folder = os.path.join(destination_dir, name)
        if not os.path.isdir(folder) or name in recorded:
            continue
        if any(f.lower().endswith('.dcm') for _, _, files in os.walk(folder)
               for f in files):
            unrecorded.append(name)
    return unrecorded


def stale_files(state, planned_paths):
    """Recorded files at an older version that this run would not rewrite (defect 4).

    A version change means everything in the folder has to be written again. Whatever
    the source can no longer produce cannot be brought up to date, and mixing it with
    current output is exactly how a third of the export kept its 2025-era state.
    """
    planned = set(planned_paths)
    return sorted(path for path, version in state.get('files', {}).items()
                  if version != TOOL_VERSION and path not in planned)


class RunVerifier:
    """Cross-folder checks that only make sense once a whole run is seen.

    Fed one record per file while the run is in progress, from inside the app, where
    the source PatientID still exists.
    """

    def __init__(self):
        self.folders_by_source = collections.defaultdict(set)
        self.sources_by_folder = collections.defaultdict(collections.Counter)
        self.identities = collections.defaultdict(collections.Counter)
        self.unmatched_ids = set()
        self.files = 0

    def record(self, source_patient_id, anon_folder, birth_year='', sex=''):
        """Record one file. Returns a problem string if THIS file just revealed
        contamination, so the caller can stop before writing it rather than at the end
        of a run that has already scattered files across folders.

        Only the source-PatientID checks abort. A folder whose birth years disagree
        while its source PatientID is constant is a source data quality problem, not
        contamination, and stopping a twenty-thousand-file run for it would be wrong.
        Those surface in problems() at the end instead.
        """
        self.files += 1
        problem = None
        if source_patient_id:
            self.folders_by_source[source_patient_id].add(anon_folder)
            self.sources_by_folder[anon_folder][source_patient_id] += 1
            others = sorted(p for p in self.sources_by_folder[anon_folder]
                            if p != source_patient_id)
            if others:
                problem = ('anon folder {} already holds files from source patient {}, '
                           'and this file belongs to source patient {}'.format(
                               anon_folder, ', '.join(others), source_patient_id))
            elif len(self.folders_by_source[source_patient_id]) > 1:
                problem = ('source patient {} is being written to more than one anon '
                           'folder: {}'.format(source_patient_id, ', '.join(
                               sorted(self.folders_by_source[source_patient_id]))))
        if birth_year or sex:
            self.identities[anon_folder][(birth_year, sex)] += 1
        return problem

    def note_unmatched_id(self, folder_patient_id, dicom_patient_id):
        """A folder whose ID could not be compared with the PatientID in its files.

        Reported at the end rather than stopping the run, because an ID format this code
        cannot parse is not evidence of anything being wrong, only that the strongest
        check could not run.
        """
        self.unmatched_ids.add((str(folder_patient_id), str(dicom_patient_id)))

    def contaminated_folders(self):
        """Anon folders that received files from more than one source patient."""
        return {folder: dict(counts)
                for folder, counts in sorted(self.sources_by_folder.items())
                if len(counts) > 1}

    def split_patients(self):
        """Source patients whose files were written to more than one anon folder."""
        return {source: sorted(folders)
                for source, folders in sorted(self.folders_by_source.items())
                if len(folders) > 1}

    def mixed_identities(self):
        """Folders holding more than one birth year or sex.

        Redundant with contaminated_folders() inside the app, and kept because it is
        the same computation the university end has to rely on. If these two ever
        disagree, the proxy is what is wrong.
        """
        mixed = {}
        for folder, counts in sorted(self.identities.items()):
            years = {y for y, _ in counts if y}
            sexes = {s for _, s in counts if s}
            if len(years) > 1 or len(sexes) > 1:
                mixed[folder] = [{'birth_year': k[0], 'sex': k[1], 'files': v}
                                 for k, v in counts.most_common()]
        return mixed

    def problems(self):
        """Human-readable problems, worst first. Empty means the run is clean."""
        problems = []
        for folder, counts in self.contaminated_folders().items():
            problems.append(
                'anon folder {} received files from {} different source patients: {}'
                .format(folder, len(counts), ', '.join(
                    '{} ({} files)'.format(pid, n)
                    for pid, n in sorted(counts.items()))))
        for source, folders in self.split_patients().items():
            problems.append(
                'source patient {} was written to {} anon folders: {}'.format(
                    source, len(folders), ', '.join(folders)))
        for folder_id, dicom_id in sorted(self.unmatched_ids):
            problems.append(
                'source folder {} holds files whose PatientID is {!r}, which is not a '
                'number and could not be checked against the folder name'.format(
                    folder_id, dicom_id))
        for folder, identities in self.mixed_identities().items():
            problems.append(
                'anon folder {} holds more than one birth year or sex: {}'.format(
                    folder, '  |  '.join(
                        '{} {} x{}'.format(i['birth_year'] or '?', i['sex'] or '?',
                                           i['files']) for i in identities)))
        return problems
