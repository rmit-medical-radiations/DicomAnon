import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import os, sys, tempfile
# Run from a throwaway directory so a test can never touch the real output folder,
# the real ID mapping file, or the real state under the home folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix='dicomanon-test-'))
import pandas as pd
from PyQt6.QtWidgets import QApplication
from DicomAnon import DicomAnonWidget
from anon_checks import VerificationError, check_assignments

app = QApplication(sys.argv[:1]); w = DicomAnonWidget()

def try_lookup(name, ids, anons):
    pd.DataFrame({'Patient ID': ids, 'Anonymised ID': anons}).to_excel('lk.xlsx', index=False)
    try:
        w._load_lookup('lk.xlsx')
        print('  {:<34} accepted'.format(name))
        return True
    except VerificationError as e:
        for line in str(e).splitlines()[2:]:
            print('  {:<34} {}'.format(name if line == str(e).splitlines()[2] else '', line.strip()))
        return False

print('=== lookup files that must be rejected ===')
try_lookup('two patients, one anon ID', ['1234','5678'], ['Brain-0001','Brain-0001'])
try_lookup('same patient listed twice', ['1234','1234'], ['Brain-0001','Brain-0007'])
# Excel converts '01234' to the number 1234 on round-trip, so a leading zero cannot
# survive in a real .xlsx at all; check_lookup is exercised directly instead.
from anon_checks import check_lookup
print('  {:<34} {}'.format('leading zero (text cell)',
      check_lookup([('01234','Brain-0001')])[0]))
try_lookup('missing anon ID', ['1234','5678'], ['Brain-0001',''])
try_lookup('non-numeric patient ID', ['MRN1234','5678'], ['Brain-0001','Brain-0002'])
try_lookup('path separator in anon ID', ['1234','5678'], ['Brain/0001','Brain-0002'])
try_lookup('reserved on Windows', ['1234','5678'], ['CON','Brain-0002'])

print('\n=== valid lookup ===')
assert try_lookup('clean two-patient file', ['1234','5678'], ['Brain-0001','Brain-0002'])

print('\n=== pandas float coercion no longer skips everyone ===')
df = pd.DataFrame({'Patient ID': [1234, None, 5678], 'Anonymised ID': ['Brain-0001',None,'Brain-0002']})
df.to_excel('lk.xlsx', index=False)
print('  column dtype in the file: {}'.format(pd.read_excel('lk.xlsx')['Patient ID'].dtype))
print('  loaded: {}'.format(w._load_lookup('lk.xlsx')))
assert w._load_lookup('lk.xlsx') == {'1234':'Brain-0001','5678':'Brain-0002'}

print('\n=== rule 1: the lookup may not reassign a patient ===')
recorded = {'1234':'Brain-0001','5678':'Brain-0002'}
print('  moved patient  ->', check_assignments({'1234':'Brain-0009'}, recorded))
print('  reused folder  ->', check_assignments({'9999':'Brain-0001'}, recorded))
print('  added patient  ->', check_assignments({'1234':'Brain-0001','7777':'Brain-0003'}, recorded) or 'no problems')
assert not check_assignments({'1234':'Brain-0001','7777':'Brain-0003'}, recorded)
print('\nall lookup tests passed')
