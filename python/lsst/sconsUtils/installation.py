##
#  @file installation.py
#
#  Builders and path setup for installation targets.
##
import os.path
import glob
import re
import sys
import shutil

import SCons.Script
from SCons.Script.SConscript import SConsEnvironment

from .vcs import svn
from .vcs import hg
from .vcs import git

from . import state
from .utils import memberOf

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

##
# @brief return a path to use as the installation directory for a product
# @param pathFormat     the format string to process 
# @param env            the scons environment
# @param versionString  the versionString passed to MakeEnv
##
def makeProductPath(env, pathFormat):
    pathFormat = re.sub(r"%(\w)", r"%(\1)s", pathFormat)
    
    eupsPath = os.environ['PWD']
    if env.has_key('eupsProduct') and env['eupsPath']:
        eupsPath = env['eupsPath']

    return pathFormat % { "P": eupsPath,
                          "f": env['eupsFlavor'],
                          "p": env['eupsProduct'],
                          "v": env['version'],
                          "c": os.environ['PWD'] }
    
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

## @brief Set a version ID from env, or a version control ID string ($name$ or $HeadURL$)
def getVersion(env, versionString):

    version = "unknown"

    if env.has_key('version'):
        version = env['version']
        if env.has_key('baseversion') and \
                not version.startswith(env['baseversion']):
            utils.log.warn("Explicit version %s is incompatible with baseversion %s"
                           % (version, env['baseversion']))
    elif not versionString:
        version = "unknown"
    elif re.search(r"^[$]Name:\s+", versionString):
        # CVS.  Extract the tagname
        version = re.search(r"^[$]Name:\s+([^ $]*)", versionString).group(1)
        if version == "":
            version = "cvs"
    elif re.search(r"^[$]HeadURL:\s+", versionString):
        # SVN.  Guess the tagname from the last part of the directory
        HeadURL = re.search(r"^[$]HeadURL:\s+(.*)", versionString).group(1)
        HeadURL = os.path.split(HeadURL)[0]
        if env.installing or env.declaring:
            try:
                version = svn.guessVersionName(HeadURL)
            except RuntimeError as err:
                if env['force']:
                    version = "unknown"
                else:
                    state.log.fail(
                        "%s\nFound problem with svn revision number; update or specify force=True to proceed"
                        % err
                        )
            if env.has_key('baseversion'):
                version = env['baseversion'] + "+" + version
    elif versionString.lower() in ("hg", "mercurial"):
        # Mercurial (hg).
        try:
            version = hg.guessVersionName()
        except RuntimeError as err:
            if env['force']:
                version = "unknown"
            else:
                state.log.fail(
                    "%s\nFound problem with hg version; update or specify force=True to proceed" % err
                    )
    elif versionString.lower() in ("git",):
        # git.
        try:
            version = git.guessVersionName()
        except RuntimeError as err:
            if env['force']:
                version = "unknown"
            else:
                state.log.fail(
                    "%s\nFound problem with git version; update or specify force=True to proceed" % err
                    )
    state.log.flush()
    env["version"] = version
    return version

## @brief Set a prefix based on the EUPS_PATH, the product name, and a versionString from cvs or svn.
def setPrefix(env, versionString, eupsProductPath=None):
    if eupsProductPath:
        getVersion(env, versionString)
        eupsPrefix = makeProductPath(env, eupsProductPath)
    elif env.has_key('eupsPath') and env['eupsPath']:
        eupsPrefix = env['eupsPath']
	flavor = env['eupsFlavor']
	if not re.search("/" + flavor + "$", eupsPrefix):
	    eupsPrefix = os.path.join(eupsPrefix, flavor)
        prodPath = env['eupsProduct']
        if env.has_key('eupsProductPath') and env['eupsProductPath']:
            prodPath = env['eupsProductPath']
        eupsPrefix = os.path.join(eupsPrefix, prodPath, getVersion(env, versionString))
    else:
        eupsPrefix = None
    if env.has_key('prefix'):
        if getVersion(env, versionString) != "unknown" and eupsPrefix and eupsPrefix != env['prefix']:
            print >> sys.stderr, "Ignoring prefix %s from EUPS_PATH" % eupsPrefix
        return makeProductPath(env, env['prefix'])
    elif env.has_key('eupsPath') and env['eupsPath']:
        prefix = eupsPrefix
    else:
        prefix = "/usr/local"
    return prefix

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

##
# Create current and declare targets for products.  products
# may be a list of (product, version) tuples.  If product is None
# it's taken to be self['eupsProduct']; if version is None it's
# taken to be self['version'].
##
@memberOf(SConsEnvironment)
def Declare(self, products=None):

    if "undeclare" in SCons.Script.COMMAND_LINE_TARGETS and not self.GetOption("silent"):
        state.log.warn("'scons undeclare' is deprecated; please use 'scons declare -c' instead")
    if \
           "declare" in SCons.Script.COMMAND_LINE_TARGETS or \
           "undeclare" in SCons.Script.COMMAND_LINE_TARGETS or \
           ("install" in SCons.Script.COMMAND_LINE_TARGETS and self.GetOption("clean")) or \
           "current" in SCons.Script.COMMAND_LINE_TARGETS:
        current = []; declare = []; undeclare = []

        if not products:
            products = [None]

        for prod in products:
            if not prod or isinstance(prod, str):   # i.e. no version
                product = prod

                if self.has_key('version'):
                    version = self['version']
                else:
                    version = None
            else:
                product, version = prod

            if not product:
                product = self['eupsProduct']

            if "EUPS_DIR" in os.environ.keys():
                self['ENV']['PATH'] += os.pathsep + "%s/bin" % (os.environ["EUPS_DIR"])

                if "undeclare" in SCons.Script.COMMAND_LINE_TARGETS or self.GetOption("clean"):
                    if version:
                        command = "eups undeclare --flavor %s %s %s" % \
                                  (self['eupsFlavor'], product, version)
                        if ("current" in SCons.Script.COMMAND_LINE_TARGETS 
                            and not "declare" in SCons.Script.COMMAND_LINE_TARGETS):
                            command += " --current"
                            
                        if self.GetOption("clean"):
                            self.Execute(command)
                        else:
                            undeclare += [command]
                    else:
                        state.log.warn("I don't know your version; not undeclaring to eups")
                else:
                    command = "eups declare --force --flavor %s --root %s" % \
                              (self['eupsFlavor'], self['prefix'])

                    if self.has_key('eupsPath'):
                        command += " -Z %s" % self['eupsPath']
                        
                    if version:
                        command += " %s %s" % (product, version)

                    current += [command + " --current"]
                    declare += [command]

        if current:
            self.Command("current", "", action=current)
        if declare:
            if "current" in SCons.Script.COMMAND_LINE_TARGETS:
                self.Command("declare", "", action="") # current will declare it for us
            else:
                self.Command("declare", "", action=declare)
        if undeclare:
            self.Command("undeclare", "", action=undeclare)

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

##
#  @brief SCons Action callable to recursively install a directory.
#
#  This is separate from the InstallDir function to allow the directory-walking
#  to happen when installation is actually invoked, rather than when the SConscripts
#  are parsed.  This still does not ensure that all necessary files are built as
#  prerequisites to installing, but if one explicitly marks the install targets
#  as dependent on the build targets, that should be enough.
##
class DirectoryInstaller(object):

    def __init__(self, ignoreRegex, recursive):
        self.ignoreRegex = re.compile(ignoreRegex)
        self.recursive = recursive

    def __call__(self, target, source, env):
        results = []
        prefix = os.path.abspath(os.path.join(target[0].abspath, ".."))
        destpath = os.path.join(target[0].abspath)
        if not os.path.isdir(destpath):
            state.log.info("Creating directory %s" % destpath)
            os.makedirs(destpath)
        for root, dirnames, filenames in os.walk(source[0].path):
            if not self.recursive:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames if d != ".svn"] # ignore .svn tree
            for dirname in dirnames:
                destpath = os.path.join(prefix, root, dirname)
                if not os.path.isdir(destpath):
                    state.log.info("Creating directory %s" % destpath)
                    os.makedirs(destpath)
            for filename in filenames:
                if self.ignoreRegex.search(filename):
                    continue
                destpath = os.path.join(prefix, root)
                srcpath = os.path.join(root, filename)
                state.log.info("Copying %s to %s" % (srcpath, destpath))
                shutil.copy(srcpath, destpath)
        return 0
        

##
#  Install the directory dir into prefix, (along with all its descendents if recursive is True).
#  Omit files and directories that match ignoreRegex
##
@memberOf(SConsEnvironment)
def InstallDir(self, prefix, dir, ignoreRegex=r"(~$|\.pyc$|\.os?$)", recursive=True):
    if not self.installing:
        return []
    result = self.Command(target=os.path.join(self.Dir(prefix).abspath, dir), source=dir,
                          action=DirectoryInstaller(ignoreRegex, recursive))
    self.AlwaysBuild(result)
    return result

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

##
# Install a ups directory, setting absolute versions as appropriate
# (unless you're installing from the trunk, in which case no versions
# are expanded).  Any build/table files present in "./ups" are automatically
# added to files.
#
# If presetup is provided, it's expected to be a dictionary with keys
# product names and values the version that should be installed into
# the table files, overriding eups expandtable's usual behaviour. E.g.
# env.InstallEups(os.path.join(env['prefix'], "ups"), presetup={"sconsUtils" : env['version']})
##
@memberOf(SConsEnvironment)
def InstallEups(env, dest, files=[], presetup=""):

    if not env.installing:
        return []

    if env.GetOption("clean"):
        print >> sys.stderr, "Removing", dest
        shutil.rmtree(dest, ignore_errors=True)
    else:
        presetupStr = []
        for p in presetup:
            presetupStr += ["--product %s=%s" % (p, presetup[p])]
        presetup = " ".join(presetupStr)

        env = env.Clone(ENV = os.environ)
        #
        # Add any build/table/cfg files to the desired files
        #
        files = [str(f) for f in files] # in case the user used Glob not glob.glob
        files += glob.glob(os.path.join("ups", "*.build")) + glob.glob(os.path.join("ups","*.table")) \
            + glob.glob(os.path.join("ups", "*.cfg"))
        files = list(set(files))        # remove duplicates

        buildFiles = filter(lambda f: re.search(r"\.build$", f), files)
        build_obj = env.Install(dest, buildFiles)
        
        tableFiles = filter(lambda f: re.search(r"\.table$", f), files)
        table_obj = env.Install(dest, tableFiles)

        miscFiles = filter(lambda f: not re.search(r"\.(build|table)$", f), files)
        misc_obj = env.Install(dest, miscFiles)

        for i in build_obj:
            env.AlwaysBuild(i)

            cmd = "eups expandbuild -i --version %s " % env['version']
            if env.has_key('baseversion'):
                cmd += " --repoversion %s " % env['baseversion']
            cmd += str(i)
            env.AddPostAction(i, env.Action("%s" %(cmd), cmd, ENV = os.environ))

        for i in table_obj:
            env.AlwaysBuild(i)

            cmd = "eups expandtable -i -W '^(?!LOCAL:)' " # version doesn't start "LOCAL:"
            if presetup:
                cmd += presetup + " "
            cmd += str(i)

            env.AddPostAction(i, env.Action("%s" %(cmd), cmd, ENV = os.environ))

    return dest

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

## @brief Install directories in the usual LSST way, handling "ups" specially.
@memberOf(SConsEnvironment)
def InstallLSST(self, prefix, dirs, ignoreRegex=None):
    results = []
    for d in dirs:
        if d == "ups":
            t = self.InstallEups(os.path.join(prefix, "ups"))
        else:
            t = self.InstallDir(prefix, d, ignoreRegex=ignoreRegex)
        self.Depends(t, d)
        results.extend(t)
        self.Alias("install", t)
    self.Clean("install", prefix)
    return results
