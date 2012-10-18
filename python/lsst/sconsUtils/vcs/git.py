#
# A simple python interface to git, using os.popen
# Based on the svn interface.
#
# If ever we want to do anything clever, we should use one of
# the supported python packages
#
import os, re
import subprocess
from .. import state

#
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
#
def guessVersionName():
    """Guess a version name"""
    with open("/dev/null", "a") as null:
        if not os.path.exists(".git"):
            state.log.warn("Cannot guess version without .git directory; version will be set to 'unknown'.")
            return "unknown"
        status = subprocess.check_output("git status --porcelain --untracked-files=no",
                                         shell=True, stderr=null)
        if status.strip():
            raise RuntimeError("Error with git version: uncommitted changes")
        desc = subprocess.check_output("git describe --tags --always",
                                       shell=True, stderr=null)
    return desc.strip()

def guessFingerprint():
    """Return (fingerprint, modified) where fingerprint is the repository's SHA1"""
    fingerprint, modified = "0x0", False
    with open("/dev/null", "a") as null:
        if not os.path.exists(".git"):
            state.log.warn("Cannot guess fingerprint without .git directory; will be set to '%s'."
                           % fingerprint)
        else:
            status = subprocess.check_output("git status --porcelain --untracked-files=no",
                                             shell=True, stderr=null)
            if status.strip():
                modified = True
            try:
                status = subprocess.check_output("git rev-parse HEAD", shell=True, stderr=null)
            except:
                state.log.warn("Cannot guess fingerprint; will be set to '%s'." % fingerprint)

            fingerprint = status.strip()

    return fingerprint, modified
