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
import re

from pydicom.datadict import tag_for_keyword

STUDY_ID_RE = re.compile(r'STUDY_\d+$')

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


def snapshot_source(ds):
    """Capture what verify_file needs to compare against, before ds is mutated.

    Must be called BEFORE anonymise_dicom, which overwrites all of it.
    """
    uids = set()
    for elem in ds.iterall():
        if elem.VR == 'UI' and not (elem.keyword or '').endswith('SOPClassUID'):
            value = elem.value
            if value is None:
                continue
            if isinstance(value, (list, tuple)) or type(value).__name__ == 'MultiValue':
                uids.update(str(v) for v in value if v)
            elif str(value):
                uids.add(str(value))
    birth = str(getattr(ds, 'PatientBirthDate', '') or '')
    return {
        'uids': uids,
        'patient_id': str(getattr(ds, 'PatientID', '') or ''),
        'patient_name': str(getattr(ds, 'PatientName', '') or ''),
        'birth_year': birth[:4],
        'sex': str(getattr(ds, 'PatientSex', '') or ''),
    }


def verify_file(ds, snapshot, anon_name, check_dates=False):
    """Problems with one anonymised dataset. Empty list means it passed.

    This is CLAUDE.md defect 5's assertion list, minus the date and time one.

    check_dates stays False until defect 1 is fixed. Turning it on today fails on the
    first file of every run, correctly: StudyTime, SeriesDate, AcquisitionDate and the
    rest are still written out untouched. That is a real defect, not a broken assertion,
    but the switch is here so fixing defect 1 is what enables it rather than a rewrite.
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

    populated = sorted(kw for kw in IDENTIFYING_KEYWORDS
                       if kw in ds and str(ds.data_element(kw).value or '').strip())
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
    """Every DA/TM/DT element must differ from its source value (defect 1).

    Not reachable until defect 1 is fixed and snapshot carries the source dates. Kept
    adjacent to the switch that enables it so the two cannot drift apart.
    """
    originals = snapshot.get('dates')
    if originals is None:
        return ['date verification is on but the snapshot has no dates; fix defect 1']
    problems = []
    for elem in ds.iterall():
        if elem.VR in ('DA', 'TM', 'DT') and elem.value:
            key = str(elem.tag)
            if key in originals and str(elem.value) == originals[key]:
                problems.append('{} is unchanged from the source'.format(
                    elem.keyword or elem.tag))
    return problems


class RunVerifier:
    """Cross-folder checks that only make sense once a whole run is seen.

    Fed one record per file while the run is in progress, from inside the app, where
    the source PatientID still exists.
    """

    def __init__(self):
        self.folders_by_source = collections.defaultdict(set)
        self.sources_by_folder = collections.defaultdict(collections.Counter)
        self.identities = collections.defaultdict(collections.Counter)
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
        for folder, identities in self.mixed_identities().items():
            problems.append(
                'anon folder {} holds more than one birth year or sex: {}'.format(
                    folder, '  |  '.join(
                        '{} {} x{}'.format(i['birth_year'] or '?', i['sex'] or '?',
                                           i['files']) for i in identities)))
        return problems
