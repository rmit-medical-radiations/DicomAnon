"""The README documents which tags are blanked. It has to be true.

Defect 7 was exactly this failing: the README listed `PhysiciansReadingStudy` among the
tags that are cleared, the code held the same misspelling, and since nothing compared
either against the DICOM dictionary the tag shipped populated in every release. A
documented guarantee that nobody checks is how that happens.

This compares the list in the README against the list the anonymiser actually blanks, so
adding a tag to one and forgetting the other fails the build rather than the next export.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anon_checks import IDENTIFYING_KEYWORDS, validate_keywords

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def documented_keywords(text):
    """The tag bullets between the 'except PatientName, PatientID' heading and Installation.

    PatientName and PatientID are documented separately, because they are replaced with
    the anonymised ID rather than blanked, so they are outside this range on purpose.
    """
    marker = '### Patient (except PatientName, PatientID)'
    assert marker in text, 'the README tag section has been renamed; update this test'
    body = text.split(marker, 1)[1].split('## Installation', 1)[0]
    return set(re.findall(r'^\* ([A-Za-z]+)$', body, re.M))


readme = open(os.path.join(REPO, 'README.md')).read()
documented = documented_keywords(readme)
code = set(IDENTIFYING_KEYWORDS)

print('documented in README : {}'.format(len(documented)))
print('blanked by the code  : {}'.format(len(code)))

only_readme = sorted(documented - code)
only_code = sorted(code - documented)
if only_readme:
    print('\nREADME promises these are cleared, but the code does not blank them:')
    for k in only_readme:
        print('  ' + k)
if only_code:
    print('\nthe code blanks these, but the README does not mention them:')
    for k in only_code:
        print('  ' + k)
assert not only_readme and not only_code, 'README and IDENTIFYING_KEYWORDS disagree'

# Anything documented must also be a tag that exists, or blanking it does nothing.
dodgy = validate_keywords(documented)
assert not dodgy, 'documented but not real DICOM keywords: {}'.format(dodgy)
print('\nREADME and the anonymiser agree, and every entry is a real DICOM tag')

# The anonymised ID is used verbatim: no prefix is added anywhere in the code.
assert 'Brain-<' not in readme, (
    "README still says the tool builds a 'Brain-<...>' value; it uses the lookup "
    "file's anonymised ID exactly as given")
print('README does not claim a prefix the tool does not add')
