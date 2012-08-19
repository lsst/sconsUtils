#
# A simple python interface to git, using os.popen
# Based on the svn interface.
#
# If ever we want to do anything clever, we should use one of
# the supported python packages
#
import os, re

from .. import state

#
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
#
def guessVersionName():
    """Guess a version name"""
    if not os.path.exists(".git"):
        state.log.warn("Cannot guess version without .git directory; version will be set to 'unknown'.")
        return "unknown"
    status = os.popen("git status --porcelain --untracked-files=no").readline()
    if status.strip():
        raise RuntimeError("Error with git version: uncommitted changes")
    desc = os.popen("git describe --tags --always").readline()
    return desc.strip()

def guessFingerprint():
    """Return (fingerprint, modified) where fingerprint is the repository's SHA1"""
    fingerprint, modified = "0x0", False
    if not os.path.exists(".git"):
        state.log.warn("Cannot guess fingerprint without .git directory; will be set to '%s'." % fingerprint)
    else:
        status = os.popen("git status --porcelain --untracked-files=no").readline()
        if status.strip():
            modified = True

        mat = re.search(r"-g([0-9a-z]+)$", os.popen("git describe --long --abbrev=128").readline())
        assert mat
        fingerprint = mat.group(1)

    return fingerprint, modified
