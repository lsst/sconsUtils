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

def revision(file=".", lastChanged=False):
    """Return file's Revision as a string"""

    info = getInfo(file)

    if lastChanged:
        return info["Last Changed Rev"]
    else:
        return info["Revision"]
