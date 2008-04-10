#
# A simple python interface to svn, using os.popen
#
# If ever we want to do anything clever, we should use one of
# the supported svn/python packages
#
import os, re

def isSvnFile(file):
    """Is file under svn control?"""

    return re.search(r"is not a working copy",
                     "".join(os.popen("svn info %s 2>&1" % file).readlines())) == None

def getInfo(file="."):
    """Return a dictionary of all the information returned by "svn info" for the specified file"""

    if not isSvnFile(file):
        raise RuntimeError, "%s is not under svn control" % file

    infoList = os.popen("svn info %s" % file).readlines()

    info = {}
    for line in infoList:
        mat = re.search(r"^([^:]+)\s*:\s*(.*)", line)
        if mat:
            info[mat.group(1)] = mat.group(2)
        
    return info

def isTrunk(file="."):
    """Is file on the trunk?"""

    info = getInfo(file)

    return re.search(r"/trunk($|/)", info["URL"]) != None

def revision(file=None, lastChanged=False):
    """Return file's Revision as a string; if file is None return
    a tuple (oldestRevision, youngestRevision, flags) as reported
    by svnversion; e.g. (4123, 4168, ("M", "S")) (oldestRevision
    and youngestRevision may be equal)
    """

    if file:
        info = getInfo(file)

        if lastChanged:
            return info["Last Changed Rev"]
        else:
            return info["Revision"]

    if lastChanged:
        raise RuntimeError, "lastChanged makes no sense if file is None"

    res = os.popen("svnversion 2>&1").readline()

    if res == "exported\n":
        raise RuntimeError, "No svn revision information is available"

    mat = re.search(r"^(?P<oldest>\d+)(:(?P<youngest>\d+))?(?P<flags>[MS]*)", res)
    if mat:
        matches = mat.groupdict()
        if not matches["youngest"]:
            matches["youngest"] = matches["oldest"]
        return matches["oldest"], matches["youngest"], tuple(matches["flags"])

    raise RuntimeError, ("svnversion returned unexpected result \"%s\"" % res[:-1])
