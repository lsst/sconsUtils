#
# A simple python interface to svn, using os.popen
#
# If ever we want to do anything clever, we should use one of
# the supported svn/python packages
#
import os, re, sys

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

    res = os.popen("svnversion . 2>&1").readline()

    if res == "exported\n":
        raise RuntimeError, "No svn revision information is available"

    mat = re.search(r"^(?P<oldest>\d+)(:(?P<youngest>\d+))?(?P<flags>[MS]*)", res)
    if mat:
        matches = mat.groupdict()
        if not matches["youngest"]:
            matches["youngest"] = matches["oldest"]
        return matches["oldest"], matches["youngest"], tuple(matches["flags"])

    raise RuntimeError, ("svnversion returned unexpected result \"%s\"" % res[:-1])

#
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
#
def guessVersionName(HeadURL):
    """Guess a version name given a HeadURL"""

    if re.search(r"/trunk$", HeadURL):
        versionName = ""
    elif re.search(r"/branches/(.+)$", HeadURL):
        versionName = "branch_%s+" % re.search(r"/branches/(.+)$", HeadURL).group(1)
    elif re.search(r"/tags/(\d+(\.\d+)*)([-+][_a-zA-Z0-9]+)?$", HeadURL):
        versionName = "%s" % re.search(r"/tags/(.*)$", HeadURL).group(1)

        return versionName              # no need for a "+svnXXXX"
    elif re.search(r"/branches/(.+)$", HeadURL):
        versionName = "branch_%s+" % re.search(r"/branches/(.+)$", HeadURL).group(1)
    else:
        print >> sys.stderr, "Unable to guess versionName name from %s" % HeadURL
        versionName = "unknown+"

    try:                    # Try to lookup the svn versionName
        (oldest, youngest, flags) = revision()

        okVersion = True
        if "M" in flags:
            msg = "You are installing, but have unchecked in files"
            okVersion = False
        if "S" in flags:
            msg = "You are installing, but have switched SVN URLs"
            okVersion = False
        if oldest != youngest:
            msg = "You have a range of revisions in your tree (%s:%s); adopting %s" % \
                  (oldest, youngest, youngest)
            okVersion = False

        if not okVersion:
            raise RuntimeError, ("Problem with determining svn revision: %s" % msg)

        versionName += "svn" + youngest
    except IOError:
        return "unknown"

    return versionName

def parseVersionName(versionName):
    """A callback that knows about the LSST convention that a tagname such as
       ticket_374
   means the top of ticket 374, and
      ticket_374+svn6021
   means revision 6021 on ticket 374.  You may replace "ticket" with "branch" if you wish

   The "versionName" may actually be the directory part of a URL, and ".../tags/tagname" is
   also supported
   """

    mat = re.search(r"/(tag)s/(\d+(?:\.\d+)*)(?:([-+])((svn)?(\d+)))?$", versionName)
    if not mat:
        mat = re.search(r"/(branch|ticket)_(\d+)(?:([-+])svn(\d+))?$", versionName)
    if mat:
        type = mat.group(1)
        ticket = mat.group(2)
        pm = mat.group(3)               # + or -
        revision = re.sub("^svn", "", mat.group(4))

        return (type, ticket, revision, pm)

    return (None, None, None, None)
