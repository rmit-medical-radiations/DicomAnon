#!/usr/bin/env python3
"""Audit what each patient actually contains: studies, series, and the pieces the
modelling needs (read-only).

check-anon-output.py asks whether the anonymisation is sound. This asks a different
question: is the dataset USABLE. A folder can be perfectly anonymised and still be no
good for modelling because it has no structure set, or no post-contrast T1, or a
planning CT that nothing contours.

For every patient it reports the studies, the series in each, and then whether these
are present:

  planning CT    a CT series that an RTSTRUCT actually references
  PTV            a PTV region of interest in a structure set
  GTV            a GTV region of interest, the delineation the modelling targets
  FLAIR, T2      MR series matched from SeriesDescription
  T1c            a T1 with contrast. Post-contrast is decided from the description
                 first ('+C', 'post', 'Gd'), and only failing that from
                 ContrastBolusAgent being populated, which some protocols fill for
                 every series in the exam and which is therefore reported as inferred
                 rather than trusted.
  DWI            diffusion. ADC maps are counted separately, since a derived ADC is
                 not the same thing as having the diffusion series.

Two things it does NOT do, deliberately.

It does not judge. A missing FLAIR may be perfectly correct for that patient, so gaps
are reported and the exit code stays 0 unless you ask for --require-complete. What the
audit is for is knowing, not gating.

It does not trust its own sequence matching in silence. MR series are classified from
free text written by whoever set the protocol up, which is guesswork however careful
the patterns are. So every series that matches nothing is listed under UNCLASSIFIED
with its description, and --show-series prints the lot with the rule that fired. Read
that before believing any of the ticks. The patterns are at the top of this file and
are meant to be edited as the data teaches you about it.

The subject is the DELIVERY, not the source. It is meant to run at the university on
what actually arrived:

    python3 audit-study-content.py /mnt/data/datasets/GBM-SP
    python3 audit-study-content.py /mnt/data/datasets/GBM-SP --show-series
    python3 audit-study-content.py /mnt/data/datasets/GBM-SP --all-files --out audit.json

Patients are the immediate subdirectories of the path you give it. It needs pydicom and
the standard library only, and imports nothing from this repo, so it can be copied to
the server on its own. Unlike check-anon-output.py it does not import anon_checks, and
that is deliberate: it asks nothing about anonymisation, so it needs none of that.

It reads what survives anonymisation, and everything it depends on does: Modality,
SeriesDescription, ContrastBolusAgent and the structure set ROI names are all preserved,
and the UID remapping is internally consistent, so an RTSTRUCT still resolves to the CT
it contours. Verified on real DicomAnon output rather than assumed.
"""
import argparse
import collections
import concurrent.futures
import json
import os
import re
import sys

import pydicom

# --------------------------------------------------------------------------- rules
#
# Matched against SeriesDescription, lowercased, in this order. First hit wins, and the
# order is load-bearing: FLAIR contains 't2' in most vendors' naming, and an ADC map is
# usually described as diffusion, so both have to be tested before the thing they would
# otherwise be mistaken for.
#
# Written as regexes rather than substrings so that word boundaries can be enforced:
# 't2' as a substring matches 'T2*' and 'FIESTA-T2', which are not what is wanted.
SEQUENCE_RULES = [
    ('FLAIR', r'flair|dark[\s_-]*fluid|\btirm\b'),
    ('ADC',   r'adc\b|apparent[\s_-]*diff'),
    ('DWI',   r'dwi\b|diff(usion)?|ep2d[\s_-]*diff|\bb\d{3,4}\b|trace'),
    ('SWI',   r'\bswi\b|susceptibility'),
    ('T2',    r'\bt2\b|t2w|t2[\s_-]*tse|\bcube[\s_-]*t2\b'),
    ('T1',    r'\bt1\b|t1w|mprage|bravo|\btfe\b|spgr'),
]

# Evidence of contrast in the description. Checked only for series that matched T1.
POST_CONTRAST_RE = re.compile(
    r'\+\s*c\b|\bc\+|post[\s_-]*(contrast|gd|gad)?|\bgd\b|\bgad\b|gadolin|'
    r'\bce\b|contrast[\s_-]*enh|\bt1c\b', re.I)
PRE_CONTRAST_RE = re.compile(r'\bpre\b|pre[\s_-]*(contrast|gd|gad)|\bnative\b', re.I)

# Region of interest names. Matched on the name with separators and case removed, so
# 'PTV_60', 'ptv 60Gy' and 'PTV60' all land together. Anchored at the start, because a
# name like 'Brain-PTV_margin' is a derived structure and not the target volume itself;
# those still appear in the reported ROI list, just not as the tick.
ROI_RULES = [('GTV', r'^gtv'), ('CTV', r'^ctv'), ('PTV', r'^ptv')]

# What a patient needs before the audit calls them complete.
REQUIRED = ['planning CT', 'PTV', 'GTV', 'FLAIR', 'T2', 'T1c', 'DWI']

# Enough to identify a series without reading pixel data. ContrastBolusAgent is the
# secondary evidence for T1c described above.
SCAN_TAGS = ['PatientID', 'PatientName', 'Modality', 'SeriesDescription',
             'SeriesInstanceUID', 'SeriesNumber', 'StudyInstanceUID', 'StudyDate',
             'StudyDescription', 'ContrastBolusAgent', 'SOPClassUID', 'SOPInstanceUID']

RTSTRUCT_SOP_CLASS = '1.2.840.10008.5.1.4.1.1.481.3'


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('root', help='folder holding one subfolder per patient')
    ap.add_argument('--patients', nargs='*', default=None,
                    help='limit to these patient folder names')
    ap.add_argument('--all-files', action='store_true',
                    help='read every file. By default one file per directory is read '
                         'and the rest counted, since a DICOM series directory is '
                         'homogeneous. Use this if directories hold mixed series.')
    ap.add_argument('--show-series', action='store_true',
                    help='list every series with the rule that classified it. Read '
                         'this before trusting the summary.')
    ap.add_argument('--require-complete', action='store_true',
                    help='exit non-zero if any patient is missing a required item')
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument('--out', default=None, help='write the full audit as JSON here')
    return ap.parse_args()


# --------------------------------------------------------------------------- scanning

def find_tasks(root, patients, all_files):
    """One task per file to read, plus the file count each task stands for.

    Sampling one file per directory is what makes this usable on a 760k file export.
    The cost is an assumption, that a directory holds one series, and --all-files is
    the way out of it when that is not true.
    """
    tasks = []
    names = sorted(d for d in os.listdir(root)
                   if os.path.isdir(os.path.join(root, d)) and not d.startswith('.'))
    if patients:
        wanted = set(patients)
        names = [n for n in names if n in wanted]
    for patient in names:
        for dirpath, _, filenames in os.walk(os.path.join(root, patient)):
            dicoms = sorted(f for f in filenames if not f.startswith('.'))
            if not dicoms:
                continue
            if all_files:
                for f in dicoms:
                    tasks.append((patient, os.path.join(dirpath, f), 1))
            else:
                tasks.append((patient, os.path.join(dirpath, dicoms[0]), len(dicoms)))
    return names, tasks


def read_one(task):
    """Identify one file. Never raises: a file we cannot read is a finding, not a stop.

    Structure sets are read in full, because the ROI names and the series they
    reference are the whole point and neither is in the header. There are few of them.
    """
    patient, path, count = task
    try:
        header = pydicom.dcmread(path, specific_tags=SCAN_TAGS, stop_before_pixels=True)
    except Exception as exc:
        return {'patient': patient, 'path': path, 'unreadable': str(exc)[:200]}

    record = {'patient': patient, 'path': path, 'instances': count,
              'modality': str(getattr(header, 'Modality', '') or ''),
              'description': str(getattr(header, 'SeriesDescription', '') or ''),
              'series_uid': str(getattr(header, 'SeriesInstanceUID', '') or ''),
              'series_number': str(getattr(header, 'SeriesNumber', '') or ''),
              'study_uid': str(getattr(header, 'StudyInstanceUID', '') or ''),
              'study_date': str(getattr(header, 'StudyDate', '') or ''),
              'contrast_agent': str(getattr(header, 'ContrastBolusAgent', '') or ''),
              'patient_id': str(getattr(header, 'PatientID', '') or '')}

    if str(getattr(header, 'SOPClassUID', '')) == RTSTRUCT_SOP_CLASS:
        record['rois'], record['references'] = read_structure_set(path)
    return record


def read_structure_set(path):
    """ROI names, and the series UIDs the structure set says it contours."""
    rois, references = [], []
    try:
        ds = pydicom.dcmread(path)
    except Exception:
        return rois, references
    for item in getattr(ds, 'StructureSetROISequence', []) or []:
        name = str(getattr(item, 'ROIName', '') or '').strip()
        if name:
            rois.append(name)
    for frame in getattr(ds, 'ReferencedFrameOfReferenceSequence', []) or []:
        for study in getattr(frame, 'RTReferencedStudySequence', []) or []:
            for series in getattr(study, 'RTReferencedSeriesSequence', []) or []:
                uid = str(getattr(series, 'SeriesInstanceUID', '') or '')
                if uid:
                    references.append(uid)
    return rois, references


def scan(root, patients, all_files, workers):
    names, tasks = find_tasks(root, patients, all_files)
    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for record in pool.map(read_one, tasks):
            records.append(record)
    return names, records


# --------------------------------------------------------------------------- rules

def classify_sequence(description, contrast_agent):
    """(label, rule) for one MR series. label is None when nothing matched.

    Returns the rule that fired as well as the label, so --show-series can show its
    working and the patterns can be corrected from evidence rather than from taste.
    """
    text = (description or '').lower()
    if not text.strip():
        return None, 'no SeriesDescription'
    for label, pattern in SEQUENCE_RULES:
        if not re.search(pattern, text):
            continue
        if label != 'T1':
            return label, 'matched /{}/'.format(pattern.split('|')[0])
        if POST_CONTRAST_RE.search(text):
            return 'T1c', 'T1 and a post-contrast marker in the description'
        if PRE_CONTRAST_RE.search(text):
            return 'T1', 'T1 and an explicit pre-contrast marker'
        if contrast_agent.strip():
            return 'T1c', 'T1, no marker, INFERRED from ContrastBolusAgent {!r}'.format(
                contrast_agent.strip()[:30])
        return 'T1', 'T1, no contrast evidence'
    return None, 'no rule matched'


def classify_roi(name):
    flat = re.sub(r'[\s_\-.]', '', name or '').lower()
    for label, pattern in ROI_RULES:
        if re.search(pattern, flat):
            return label
    return None


# --------------------------------------------------------------------------- audit

def audit_patient(patient, records):
    """Everything known about one patient, and what they are missing."""
    readable = [r for r in records if 'unreadable' not in r]
    unreadable = [r for r in records if 'unreadable' in r]

    series = {}
    for record in readable:
        key = record['series_uid'] or record['path']
        entry = series.setdefault(key, {
            'modality': record['modality'], 'description': record['description'],
            'series_number': record['series_number'], 'study_uid': record['study_uid'],
            'study_date': record['study_date'], 'instances': 0,
            'contrast_agent': record['contrast_agent'], 'rois': [], 'references': []})
        entry['instances'] += record.get('instances', 1)
        entry['rois'] = entry['rois'] or record.get('rois', [])
        entry['references'] = entry['references'] or record.get('references', [])

    for entry in series.values():
        if entry['modality'] == 'MR':
            entry['sequence'], entry['rule'] = classify_sequence(
                entry['description'], entry['contrast_agent'])
        else:
            entry['sequence'], entry['rule'] = None, 'not MR'

    studies = collections.defaultdict(list)
    for key, entry in series.items():
        studies[entry['study_uid']].append(entry)

    # One row per study, in date order, because a patient's studies ARE the timeline
    # here: the sessions accrue over weeks and which modalities landed in which
    # session is the thing being audited, not just how many there were.
    study_detail = []
    for uid, entries in studies.items():
        dates = sorted({e['study_date'] for e in entries if e['study_date']})
        study_detail.append({
            'study_uid': uid,
            'date': dates[0] if dates else '',
            'dates': dates,
            'series': len(entries),
            'instances': sum(e['instances'] for e in entries),
            'modalities': dict(collections.Counter(
                e['modality'] or '(none)' for e in entries)),
            'sequences': dict(collections.Counter(
                e['sequence'] for e in entries if e['sequence'])),
        })
    study_detail.sort(key=lambda st: (st['date'] or '99999999', st['study_uid']))

    modalities = collections.Counter(e['modality'] or '(none)' for e in series.values())
    sequences = collections.Counter(e['sequence'] for e in series.values()
                                    if e['sequence'])

    # Structure sets, and what they delineate.
    roi_names, roi_kinds, referenced = [], set(), set()
    for entry in series.values():
        if entry['modality'] != 'RTSTRUCT':
            continue
        for name in entry['rois']:
            roi_names.append(name)
            kind = classify_roi(name)
            if kind:
                roi_kinds.add(kind)
        referenced.update(entry['references'])

    # A planning CT is a CT series that a structure set actually points at. Falling
    # back to "there is a CT somewhere" would be wrong: this project has already
    # measured 2928 of 3603 references dangling in real registration objects, so an
    # unresolved reference is a real state and is reported as its own answer.
    ct_uids = {k for k, e in series.items() if e['modality'] == 'CT'}
    planning = ct_uids & referenced
    if planning:
        planning_ct = 'linked'
    elif ct_uids and referenced:
        planning_ct = 'unlinked'          # both exist, the reference resolves to neither
    elif ct_uids:
        planning_ct = 'no structure set'
    else:
        planning_ct = 'no CT'

    present = {
        'planning CT': planning_ct == 'linked',
        'PTV': 'PTV' in roi_kinds,
        'GTV': 'GTV' in roi_kinds,
        'FLAIR': sequences.get('FLAIR', 0) > 0,
        'T2': sequences.get('T2', 0) > 0,
        'T1c': sequences.get('T1c', 0) > 0,
        'DWI': sequences.get('DWI', 0) > 0,
    }
    inferred = sorted({e['description'] for e in series.values()
                       if e.get('sequence') == 'T1c' and 'INFERRED' in (e.get('rule') or '')})
    unclassified = sorted({e['description'] or '(no description)'
                           for e in series.values()
                           if e['modality'] == 'MR' and not e['sequence']})

    return {
        'patient': patient,
        'patient_ids': sorted({r['patient_id'] for r in readable if r['patient_id']}),
        'studies': len(studies),
        'study_detail': study_detail,
        'study_dates': sorted({e['study_date'] for e in series.values() if e['study_date']}),
        'series': len(series),
        'instances': sum(e['instances'] for e in series.values()),
        'modalities': dict(modalities),
        'sequences': dict(sequences),
        'roi_names': sorted(set(roi_names)),
        'roi_kinds': sorted(roi_kinds),
        'planning_ct': planning_ct,
        'present': present,
        'missing': [k for k in REQUIRED if not present[k]],
        't1c_inferred_from_contrast_agent': inferred,
        'unclassified_mr': unclassified,
        'unreadable': [{'path': r['path'], 'error': r['unreadable']} for r in unreadable],
        'series_detail': sorted(
            ({'modality': e['modality'], 'description': e['description'],
              'series_number': e['series_number'], 'instances': e['instances'],
              'study_date': e['study_date'], 'sequence': e['sequence'], 'rule': e['rule']}
             for e in series.values()),
            key=lambda e: (e['study_date'], e['modality'], e['series_number'])),
    }


# --------------------------------------------------------------------------- output

def tick(ok):
    return 'yes' if ok else ' - '


def report(audits, show_series):
    width = max([len(a['patient']) for a in audits] + [7])

    print('\n{}  {:>7} {:>7} {:>9}  {}'.format(
        'patient'.ljust(width), 'studies', 'series', 'instances',
        '  '.join(k.replace('planning CT', 'planCT').rjust(6) for k in REQUIRED)))
    print('-' * (width + 28 + 8 * len(REQUIRED)))
    for a in audits:
        print('{}  {:>7} {:>7} {:>9}  {}'.format(
            a['patient'].ljust(width), a['studies'], a['series'], a['instances'],
            '  '.join(tick(a['present'][k]).rjust(6) for k in REQUIRED)))

    print('\n=== per patient ===')
    for a in audits:
        print('\n{}   {} studies, {} series, {} instances'.format(
            a['patient'], a['studies'], a['series'], a['instances']))
        if a['study_detail']:
            print('  studies, in date order:')
            for i, st in enumerate(a['study_detail'], 1):
                mods = ', '.join('{} x{}'.format(k, v)
                                 for k, v in sorted(st['modalities'].items()))
                seqs = ', '.join(sorted(st['sequences']))
                print('    {:>2}. {:<10} {:>3} series {:>6} inst   {}{}'.format(
                    i, st['date'] or '(no date)', st['series'], st['instances'], mods,
                    '   [{}]'.format(seqs) if seqs else ''))
                if len(st['dates']) > 1:
                    print('        NOTE: this study carries more than one StudyDate: '
                          '{}'.format(', '.join(st['dates'])))
        print('  modalities        : {}'.format(', '.join(
            '{} x{}'.format(k, v) for k, v in sorted(a['modalities'].items()))) or 'none')
        if a['sequences']:
            print('  MR sequences      : {}'.format(', '.join(
                '{} x{}'.format(k, v) for k, v in sorted(a['sequences'].items()))))
        print('  planning CT       : {}'.format(a['planning_ct']))
        if a['roi_names']:
            print('  structures ({:>3})  : {}'.format(
                len(a['roi_names']), ', '.join(a['roi_names'][:14])
                + (' ...' if len(a['roi_names']) > 14 else '')))
        else:
            print('  structures        : none')
        if a['missing']:
            print('  MISSING           : {}'.format(', '.join(a['missing'])))
        if a['t1c_inferred_from_contrast_agent']:
            print('  T1c INFERRED from ContrastBolusAgent, not from the description:')
            for d in a['t1c_inferred_from_contrast_agent']:
                print('      {!r}'.format(d))
        if a['unclassified_mr']:
            print('  UNCLASSIFIED MR   : {}'.format(
                '; '.join(repr(d) for d in a['unclassified_mr'][:8])
                + (' ...' if len(a['unclassified_mr']) > 8 else '')))
        if a['unreadable']:
            print('  UNREADABLE        : {} files, first: {}'.format(
                len(a['unreadable']), a['unreadable'][0]['path']))
        if show_series:
            for s in a['series_detail']:
                print('      {:<9} {:<10} {:>5} inst  {:<42} {}'.format(
                    s['study_date'], s['modality'], s['instances'],
                    (s['description'] or '(no description)')[:42],
                    '[{}] {}'.format(s['sequence'], s['rule']) if s['modality'] == 'MR'
                    else ''))


def summarise(audits):
    print('\n=== summary ===')
    complete = [a for a in audits if not a['missing']]
    print('patients                     : {}'.format(len(audits)))
    print('complete on all {} items      : {}'.format(len(REQUIRED), len(complete)))
    gaps = collections.Counter()
    for a in audits:
        for item in a['missing']:
            gaps[item] += 1
    if gaps:
        print('\nmissing, by item:')
        for item in REQUIRED:
            if gaps[item]:
                who = [a['patient'] for a in audits if item in a['missing']]
                print('  {:<12} {:>3} patients: {}{}'.format(
                    item, gaps[item], ', '.join(who[:8]),
                    ' ...' if len(who) > 8 else ''))

    # "No T1c" has two very different causes and only one of them needs a person to
    # look. A patient with no T1 at all simply did not have one acquired. A patient
    # with T1 series that none of the contrast rules matched is either genuinely
    # pre-contrast only, or a description this script does not understand.
    ambiguous = [a['patient'] for a in audits
                 if 'T1c' in a['missing'] and a['sequences'].get('T1', 0) > 0]
    if ambiguous:
        print('\n{} patients have T1 series but none identified as post-contrast.\n'
              'That is either pre-contrast only, or a naming convention these rules do\n'
              'not know. Worth --show-series on these before believing the T1c column:'
              .format(len(ambiguous)))
        for name in ambiguous[:12]:
            print('  {}'.format(name))
    no_t1 = [a['patient'] for a in audits
             if 'T1c' in a['missing'] and not a['sequences'].get('T1', 0)]
    if no_t1:
        print('\n{} patients have no T1 series of any kind, so the missing T1c is an\n'
              'acquisition gap rather than a classification one.'.format(len(no_t1)))

    unclassified = sorted({d for a in audits for d in a['unclassified_mr']})
    if unclassified:
        print('\n{} MR descriptions matched no rule. A tick above can only be as good\n'
              'as these patterns, so check whether any of these should have counted:'
              .format(len(unclassified)))
        for d in unclassified[:30]:
            print('  {!r}'.format(d))
        if len(unclassified) > 30:
            print('  ... and {} more'.format(len(unclassified) - 30))

    inferred = sorted({d for a in audits for d in a['t1c_inferred_from_contrast_agent']})
    if inferred:
        print('\n{} series counted as T1c only because ContrastBolusAgent was populated.\n'
              'Some protocols fill that for every series in the exam, so confirm these:'
              .format(len(inferred)))
        for d in inferred[:20]:
            print('  {!r}'.format(d))

    unreadable = sum(len(a['unreadable']) for a in audits)
    if unreadable:
        print('\n{} files could not be read and were skipped.'.format(unreadable))
    return complete


def main():
    args = parse_args()
    if not os.path.isdir(args.root):
        print('not a directory: {}'.format(args.root))
        return 2

    names, records = scan(args.root, args.patients, args.all_files, args.workers)
    if not names:
        print('no patient folders found in {}'.format(args.root))
        return 2

    by_patient = collections.defaultdict(list)
    for record in records:
        by_patient[record['patient']].append(record)
    audits = [audit_patient(name, by_patient.get(name, [])) for name in names]

    report(audits, args.show_series)
    complete = summarise(audits)

    if args.out:
        with open(args.out, 'w') as f:
            json.dump(audits, f, indent=2)
        print('\nfull audit written to {}'.format(args.out))

    if args.require_complete and len(complete) != len(audits):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
