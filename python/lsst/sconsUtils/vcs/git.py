#
# A simple python interface to git, using os.popen
# Based on the svn interface.
#
# If ever we want to do anything clever, we should use one of
# the supported python packages
#
import os, re

#
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
#
def guessVersionName():
    """Guess a version name"""
    status = os.popen("git status --porcelain --untracked-files=no").readline()
    if status.strip():
        raise RuntimeError("Error with git version: uncommitted changes")
    desc = os.popen("git describe --tags --long --always").readline()
    return desc.strip()
