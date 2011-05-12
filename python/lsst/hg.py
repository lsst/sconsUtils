#
# A simple python interface to hg (Mercurial), using os.popen
# Based on the svn interface.
#
# If ever we want to do anything clever, we should use one of
# the supported svn/python packages
#
import os, re


#
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
#
def guessVersionName():
    """Guess a version name"""

    idents = os.popen("hg id").readline()
    ident = re.split(r"\s+", idents)
    if re.search(r"\+", ident[0]):
        raise RuntimeError("Error with hg version: uncommited changes")
    if ident[1] == "tip":
        return ident[0]
    return ident[1]
