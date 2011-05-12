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

    ident = os.popen("hg id").readlines()
    if len(ident) != 1:
        raise RuntimeError("Unable to interpret id: %s" % ident)
    ident = re.split(r"\s+", ident[0])
    return ident[1] if len(ident) > 1 and ident[1] != "tip" else ident[0]
