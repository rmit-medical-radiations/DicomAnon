#!/usr/bin/env python3
"""Double-check an anonymised export after it arrives at the university (read-only).

DicomAnon verifies as it writes, and that is the check that matters, because it runs at
the hospital where the source PatientID still exists. This script is the independent
second look at what actually arrived, for the end that only ever receives anonymised
folders. It cannot replace the in-app check and is not meant to: once anonymise_dicom
has run, the source identifiers are gone, so contamination can only be inferred from
what survives. Two patients of the same sex born in the same year are invisible here.

It also covers what the in-app check cannot: output written by earlier builds, which
predate the checks entirely and are most of the risk (defect 4).

Needs pydicom and the standard library only, plus anon_checks.py from this repo for the
identifying keyword list. It exits non-zero on contamination, so it can gate an import.

Four checks, cheapest first:

  identity    Distinct (birth year, sex) within one anon folder. Two birth YEARS or two
              sexes means the folder holds two people. Compare the year, not the whole
              birth date: the anonymiser zeroes month and day, so 19480722 and 19480101
              are one person recorded twice, once by an old build and once by a new one.
  labels      Every file's PatientID and PatientName must equal its anon folder name,
              since anonymise_dicom sets both from the folder assignment. Anything else
              is a file that was never anonymised, or one that arrived from elsewhere.
  stale       Files still carrying a real birth date, a raw StudyID, or a populated
              identifying tag. These are live PHI in a folder believed to be anonymised,
              left by an older build (defect 4). The keyword list comes from
              anon_checks.py, the same one the anonymiser blanks, so they cannot drift.
  crossfolder One patient's data under two anon folders. Two ways in: a real PatientID
              left by a stale file appearing under two folders (the folder assignment
              drifted, rule 1), or a pseudonymised UID appearing under two folders (one
              acquisition filed under two patients).

What this deliberately does NOT do is hash pixel data. That check already exists, in
2-mrlinac/convert/check-patient-integrity.py in the gbm-mrlinac repo, and it is the only
thing that finds copies whose identifiers were reset between runs (defect 2). Run both.

    python3 check-anon-output.py /path/to/export
    python3 check-anon-output.py /path/to/export --all-files --out report.json
"""
import argparse
import collections
import concurrent.futures
import json
import os
import sys

import pydicom

from anon_checks import IDENTIFYING_KEYWORDS, STUDY_ID_RE, validate_keywords

# Read one file per series directory by default. DICOM series are homogeneous, so this
# samples ~16k files rather than ~760k on an export this size. --all-files reads the lot.
IDENTITY_TAGS = ['PatientID', 'PatientName', 'PatientBirthDate', 'PatientSex',
                 'StudyID', 'StudyInstanceUID', 'SOPInstanceUID']

_KEYWORDS = []


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('destination', help='the anonymised output folder to check')
    ap.add_argument('--check', default='all',
                    choices=['all', 'keywords', 'identity', 'labels', 'stale',
                             'crossfolder'])
    ap.add_argument('--patients', nargs='*', default=None,
                    help='limit to these anon folder names')
    ap.add_argument('--all-files', action='store_true',
                    help='read every file, not one per series directory (much slower)')
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument('--out', default=None, help='write the findings as JSON here')
    return ap.parse_args()


def load_identifying_keywords():
    """The tags the anonymiser blanks, split into ones that work and ones that cannot.

    Comes straight from anon_checks.py, which is what DicomAnon blanks from, so the
    check cannot fall behind the tool. An entry that is not a DICOM keyword can never
    satisfy anonymise_dicom's `if kw in ds`, so it blanks nothing and the tag it was
    meant to cover survives in every file. Those are reported, not silently dropped.
    """
    invalid = validate_keywords()
    return sorted(set(IDENTIFYING_KEYWORDS) - set(invalid)), invalid


def find_files(destination, patients, all_files):
    """(anon folder, file path) pairs, one per series directory unless all_files."""
    tasks = []
    for folder in sorted(os.listdir(destination)):
        folder_dir = os.path.join(destination, folder)
        if not os.path.isdir(folder_dir):
            continue
        if patients and folder not in patients:
            continue
        for dirpath, _, names in os.walk(folder_dir):
            dcm = sorted(n for n in names if n.lower().endswith('.dcm'))
            if not dcm:
                continue
            for name in (dcm if all_files else dcm[:1]):
                tasks.append((folder, os.path.join(dirpath, name)))
    return tasks


def _init_worker(keywords):
    global _KEYWORDS
    _KEYWORDS = keywords


def read_one(task):
    """Pull the identity and leak fields from one file. None if it will not read."""
    folder, path = task
    try:
        ds = pydicom.dcmread(path, stop_before_pixels=True,
                             specific_tags=IDENTITY_TAGS + _KEYWORDS)
    except Exception:
        return None
    birth = str(getattr(ds, 'PatientBirthDate', '') or '')
    populated = sorted(kw for kw in _KEYWORDS
                       if kw in ds and str(ds.data_element(kw).value or '').strip())
    return {
        'folder': folder,
        'path': path,
        'patient_id': str(getattr(ds, 'PatientID', '') or ''),
        'patient_name': str(getattr(ds, 'PatientName', '') or ''),
        'birth_date': birth,
        'birth_year': birth[:4],
        'sex': str(getattr(ds, 'PatientSex', '') or ''),
        'study_id': str(getattr(ds, 'StudyID', '') or ''),
        'study_uid': str(getattr(ds, 'StudyInstanceUID', '') or ''),
        'sop_uid': str(getattr(ds, 'SOPInstanceUID', '') or ''),
        'populated_identifying_tags': populated,
    }


def scan(destination, patients, all_files, workers, keywords):
    tasks = find_files(destination, patients, all_files)
    print('reading {} files across {} folders using {} workers'.format(
        len(tasks), len({t[0] for t in tasks}), workers))
    records, unreadable = [], 0
    if workers > 1:
        with concurrent.futures.ProcessPoolExecutor(
                max_workers=workers, initializer=_init_worker,
                initargs=(keywords,)) as pool:
            results = list(pool.map(read_one, tasks, chunksize=64))
    else:
        _init_worker(keywords)
        results = [read_one(task) for task in tasks]
    for rec in results:
        if rec:
            records.append(rec)
        else:
            unreadable += 1
    if unreadable:
        print('{} files could not be read and were skipped'.format(unreadable))
    return records


def by_folder(records):
    grouped = collections.defaultdict(list)
    for rec in records:
        grouped[rec['folder']].append(rec)
    return grouped


def check_identity(records, out):
    print('\n=== identity: distinct (birth year, sex) per folder ===')
    print('PatientID and PatientName are set from the folder name, so they cannot show')
    print('this. Birth year and sex are what survive anonymisation.\n')
    findings = {}
    for folder, recs in sorted(by_folder(records).items()):
        counts = collections.Counter((r['birth_year'], r['sex']) for r in recs
                                     if r['birth_year'] or r['sex'])
        if not counts:
            continue
        years = {y for y, _ in counts if y}
        sexes = {s for _, s in counts if s}
        mixed = len(years) > 1 or len(sexes) > 1
        findings[folder] = {
            'identities': [{'birth_year': k[0], 'sex': k[1], 'files': v}
                           for k, v in counts.most_common()],
            'two_people': bool(mixed)}
        if mixed:
            print('{:<16} TWO PEOPLE  {}'.format(folder, '  |  '.join(
                '{} {} x{}'.format(k[0] or '?', k[1] or '?', v)
                for k, v in counts.most_common())))
    mixed = sorted(f for f, v in findings.items() if v['two_people'])
    print('\nfolders holding more than one person: {} of {}'.format(
        len(mixed), len(findings)))
    if mixed:
        print('  {}'.format(', '.join(mixed)))
        print('  same sex and same birth year is invisible to this check, so this is a')
        print('  floor on the contamination, not a count of it')
    out['identity'] = findings


def check_labels(records, out):
    print('\n=== labels: PatientID and PatientName must equal the folder name ===')
    findings = {}
    for folder, recs in sorted(by_folder(records).items()):
        wrong = [r for r in recs
                 if r['patient_id'] != folder or r['patient_name'] != folder]
        if not wrong:
            continue
        values = collections.Counter((r['patient_id'], r['patient_name']) for r in wrong)
        findings[folder] = {'files': len(wrong),
                            'values': [{'patient_id': k[0], 'patient_name': k[1],
                                        'files': v} for k, v in values.most_common()],
                            'examples': [r['path'] for r in wrong[:3]]}
        print('{:<16} {:>6} mislabelled  {}'.format(folder, len(wrong), '  |  '.join(
            '{!r}/{!r} x{}'.format(k[0], k[1], v) for k, v in values.most_common(3))))
    print('\nfolders containing files labelled for someone else: {}'.format(len(findings)))
    if findings:
        print('  a real name or hospital ID here is unanonymised PHI, not just a mislabel')
    out['labels'] = findings


def check_keyword_list(invalid, out):
    """Entries in IDENTIFYING_KEYWORDS that no DICOM tag answers to.

    anonymise_dicom blanks a tag with `if kw in ds`, which is False for a keyword the
    dictionary does not know, so these entries blank nothing at all. The README lists
    them among the tags that are cleared, which makes this a documented guarantee the
    tool does not deliver.
    """
    print('\n=== keyword list: entries that can never match a tag ===')
    if not invalid:
        print('  every entry in IDENTIFYING_KEYWORDS is a real DICOM keyword')
    else:
        for kw in invalid:
            print('  {} is not a DICOM keyword, so it blanks nothing'.format(kw))
        print('  these tags survive in every file the tool has ever written')
    out['keyword_list'] = {'invalid': invalid}


def check_stale(records, keywords, out):
    print('\n=== stale: files an older build left unanonymised ===')
    findings = {}
    for folder, recs in sorted(by_folder(records).items()):
        real_birth = [r for r in recs
                      if len(r['birth_date']) == 8 and r['birth_date'][4:] != '0101']
        raw_study = [r for r in recs
                     if r['study_id'] and not STUDY_ID_RE.match(r['study_id'])]
        leaked = [r for r in recs if r['populated_identifying_tags']]
        if not (real_birth or raw_study or leaked):
            continue
        tags = collections.Counter(
            kw for r in leaked for kw in r['populated_identifying_tags'])
        findings[folder] = {
            'real_birth_date': len(real_birth),
            'raw_study_id': len(raw_study),
            'populated_identifying_tags': dict(tags),
            'examples': [r['path'] for r in (real_birth or raw_study or leaked)[:3]]}
        print('{:<16} birth date {:>5}   raw StudyID {:>5}   identifying tags {:>5}'.format(
            folder, len(real_birth), len(raw_study), len(leaked)))
    print('\nfolders holding stale output: {}'.format(len(findings)))
    if findings:
        worst = collections.Counter()
        for v in findings.values():
            worst.update(v['populated_identifying_tags'])
        if worst:
            print('  tags still populated: {}'.format(', '.join(
                '{} x{}'.format(k, v) for k, v in worst.most_common(8))))
        print('  a genuine 1 January birthday reads as anonymised here, so the birth date')
        print('  count is a floor')
    if not keywords:
        print('  note: the identifying-tag list could not be loaded, so that column is 0')
    out['stale'] = findings


def check_crossfolder(records, out):
    print('\n=== crossfolder: one patient under two anon folders ===')
    real_ids = collections.defaultdict(set)
    uids = collections.defaultdict(set)
    for rec in records:
        # A PatientID that is not the folder name came from a stale, unanonymised file
        # and is the patient's real hospital ID. It is the one thing that can link two
        # anon folders back to a single person.
        if rec['patient_id'] and rec['patient_id'] != rec['folder']:
            real_ids[rec['patient_id']].add(rec['folder'])
        for kind in ('study_uid', 'sop_uid'):
            if rec[kind]:
                uids[(kind, rec[kind])].add(rec['folder'])

    drifted = {pid: sorted(f) for pid, f in real_ids.items() if len(f) > 1}
    shared = collections.defaultdict(list)
    for (kind, uid), folders in uids.items():
        if len(folders) > 1:
            shared[kind].append({'uid': uid, 'folders': sorted(folders)})

    print('  real patient IDs appearing under more than one folder: {}'.format(len(drifted)))
    for pid, folders in sorted(drifted.items())[:5]:
        print('      {} in {}'.format(pid, ', '.join(folders)))
    for kind in ('study_uid', 'sop_uid'):
        rows = shared.get(kind, [])
        print('  {:<10} shared by more than one folder: {}'.format(kind, len(rows)))
        for row in rows[:3]:
            print('      {} ... {}'.format(row['uid'][:44], ', '.join(row['folders'])))
    if drifted:
        print('  a real ID under two folders means the folder assignment changed between')
        print('  runs, which rule 1 in CLAUDE.md says must fail the run instead')
    if shared:
        print('  a shared UID means one acquisition is filed under two patients; note this')
        print('  only catches it within a run, since uid_map resets between runs')
    out['crossfolder'] = {'assignment_drift': drifted,
                          'shared_uids': {k: v for k, v in shared.items()}}


def main():
    args = parse_args()
    if not os.path.isdir(args.destination):
        raise SystemExit('not a directory: {}'.format(args.destination))
    keywords, invalid_keywords = load_identifying_keywords()
    records = scan(args.destination, args.patients, args.all_files,
                   args.workers, keywords)
    if not records:
        raise SystemExit('no readable DICOM files under {}'.format(args.destination))

    out = {}
    if args.check in ('all', 'keywords'):
        check_keyword_list(invalid_keywords, out)
    if args.check in ('all', 'identity'):
        check_identity(records, out)
    if args.check in ('all', 'labels'):
        check_labels(records, out)
    if args.check in ('all', 'stale'):
        check_stale(records, keywords, out)
    if args.check in ('all', 'crossfolder'):
        check_crossfolder(records, out)

    if args.out:
        with open(args.out, 'w') as f:
            json.dump(out, f, indent=2)
        print('\nwrote {}'.format(args.out))

    cross = out.get('crossfolder', {})
    contaminated = (
        [f for f, v in out.get('identity', {}).items() if v['two_people']]
        + list(out.get('labels', {}))
        + list(cross.get('assignment_drift', {}))
        + [r['uid'] for rows in cross.get('shared_uids', {}).values() for r in rows])
    print('\n{}'.format('FAILED: this output should not be copied anywhere until the'
                        ' findings above are resolved' if contaminated
                        else 'PASSED: no contamination found by these checks'))
    return 1 if contaminated else 0


if __name__ == '__main__':
    sys.exit(main())
