"""Helpers shared by the tests.

save_dicom exists because pydicom changed the way you ask for a proper Part 10 file
between 2.x and 3.x. requirements.txt pins pydicom 2.4.3, which is what the released
build uses, so the tests must run there; but a developer machine may well have 3.x.
Writing for only one of them means the tests pass locally and fail in CI, which is
exactly what happened on the first attempt at tagging v0.8.
"""


def save_dicom(ds, path):
    """Write a file with a preamble and file meta, on pydicom 2.x or 3.x.

    The preamble matters: the anonymiser reads with a plain dcmread, which rejects a
    file lacking the DICM magic, so a fixture written 'like original' would not be
    readable by the code under test.
    """
    try:
        ds.save_as(path, enforce_file_format=True)          # pydicom 3.x
    except TypeError:
        ds.is_little_endian = True                          # pydicom 2.x
        ds.is_implicit_VR = False
        ds.save_as(path, write_like_original=False)
