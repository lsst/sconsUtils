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
    version = "unknown"
    if not os.path.exists(".hg"):
        state.log.warn("Cannot guess version without .hg directory; will be set to '%s'." % version)
        return version

    idents = os.popen("hg id").readline()
    ident = re.split(r"\s+", idents)
    if len(ident) == 0:
        raise RuntimeError("Unable to determine hg version")

    if re.search(r"\+", ident[0]):
        raise RuntimeError("Error with hg version: uncommitted changes")

    if len(ident) == 1:
        # Somehow, this is all we've got...
        return ident[0]

    # Prefer tag name to branch name; branch names get printed in parens
    index = 1
    while ident[index].startswith('(') and ident[index].endswith(')') and len(ident) > index + 1:
        index += 1

    # Prefer hash to "tip"
    if ident[index] == "tip":
        return ident[0]

    return ident[index]

def guessFingerprint():
    """Return (fingerprint, modified) where fingerprint is the repository's SHA1"""
    fingerprint, modified = "0x0", False
    if not os.path.exists(".hg"):
        state.log.warn("Cannot guess fingerprint without .hg directory; will be set to '%s'." % fingerprint)
    else:
        idents = os.popen("hg id").readline()
        ident = re.split(r"\s+", idents)
        if len(ident) == 0:
            raise RuntimeError("Unable to determine hg version")

        fingerprint = os.popen("hg ident --id").readline().strip()
        if re.search(r"\+", ident[0]):
            modified = True

    return fingerprint, modified
