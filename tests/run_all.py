#!/usr/bin/env python3
"""Run every check in tests/ and report. Exits non-zero if any fail.

Plain scripts rather than a test framework, so this needs nothing that the build does
not already install. Each test chdirs to a throwaway directory and points the tool's
mapping file and state directory at it, so running these can never touch a real
delivery, a real ID mapping file, or the real state under the home folder.

    python3 tests/run_all.py
"""
import os
import subprocess
import sys

TESTS = [
    ('test_dates.py', 'defect 1: every date and time shifts, intervals survive'),
    ('test_lookup.py', 'the ID lookup file is checked, and rule 1 enforced'),
    ('test_inapp.py', 'defect 6: a foreign study stops the run before it is written'),
    ('test_mapping.py', 'offsets persist, so added studies keep their spacing'),
    ('test_state.py', 'defects 2, 3, 4: stable UIDs, per-patient maps, no version mixing'),
    ('test_longitudinal.py', 'three runs, RT objects referencing earlier studies'),
    ('test_collisions.py', 'one patient in several folders merges; two patients still stop'),
    ('test_offsets_survive.py', 'a failed spreadsheet write does not lose the offsets'),
    ('test_crash.py', 'a failed run leaves a report, not a dead window'),
    ('test_readme.py', 'the README lists exactly the tags the code blanks'),
    ('test_messy.py', 'defects 8 and 9: messy real data neither stops nor leaks'),
]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    failures = []
    for name, description in TESTS:
        sys.stdout.write('{:<24} {:<62} '.format(name, description))
        sys.stdout.flush()
        result = subprocess.run([sys.executable, os.path.join(here, name)],
                                capture_output=True, text=True)
        if result.returncode == 0:
            print('PASS')
        else:
            print('FAIL')
            failures.append((name, result))

    for name, result in failures:
        print('\n{}\n--- {} ---'.format('=' * 78, name))
        print((result.stdout or '').strip()[-3000:])
        print((result.stderr or '').strip()[-3000:])

    print('\n{} of {} passed'.format(len(TESTS) - len(failures), len(TESTS)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
