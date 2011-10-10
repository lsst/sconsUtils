#
# Note that this file is called SConsUtils.py not SCons.py so as to allow us to import SCons
#
import glob
import os
import re
import shutil
from SCons.Script import *
from SCons.Script.SConscript import SConsEnvironment
SCons.progress_display = SCons.Script.Main.progress_display
import stat
import sys

from . import svn
from . import hg
from . import configure
from . import utils

try:
    import eups
except ImportError:
    pass


#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def Declare(self, products=None):
    """Create current and declare targets for products.  products
    may be a list of (product, version) tuples.  If product is None
    it's taken to be self['eupsProduct']; if version is None it's
    taken to be self['version'].
    
    We'll add Declare to class Environment"""

    if "undeclare" in COMMAND_LINE_TARGETS and not self.GetOption("silent"):
        print >> sys.stderr, "'scons undeclare' is deprecated; please use 'scons declare -c' instead"

    if \
           "declare" in COMMAND_LINE_TARGETS or \
           "undeclare" in COMMAND_LINE_TARGETS or \
           ("install" in COMMAND_LINE_TARGETS and self.GetOption("clean")) or \
           "current" in COMMAND_LINE_TARGETS:
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

                if "undeclare" in COMMAND_LINE_TARGETS or self.GetOption("clean"):
                    if version:
                        command = "eups undeclare --flavor %s %s %s" % \
                                  (self['eupsFlavor'], product, version)
                        if "current" in COMMAND_LINE_TARGETS and not "declare" in COMMAND_LINE_TARGETS:
                            command += " --current"
                            
                        if self.GetOption("clean"):
                            self.Execute(command)
                        else:
                            undeclare += [command]
                    else:
                        print >> sys.stderr, "I don't know your version; not undeclaring to eups"
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
            if "current" in COMMAND_LINE_TARGETS:
                self.Command("declare", "", action="") # current will declare it for us
            else:
                self.Command("declare", "", action=declare)
        if undeclare:
            self.Command("undeclare", "", action=undeclare)
                
SConsEnvironment.Declare = Declare

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def InstallDir(self, prefix, dir, ignoreRegex=r"(~$|\.pyc$|\.os?$)", recursive=True):
    """
    Install the directory dir into prefix, (along with all its descendents if recursive is True).
    Omit files and directories that match ignoreRegex

    Unless force is true, this routine won't do anything unless you specified an "install" target
    """

    if not self.installing:
        return

    targets = []
    for dirpath, dirnames, filenames in os.walk(dir):
        if not recursive:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames if d != ".svn"] # ignore .svn tree
        #
        # List of possible files to install
        #
        for f in filenames:
            if re.search(ignoreRegex, f):
                continue

            targets += self.Install(os.path.join(prefix, dirpath), os.path.join(dirpath, f))

    return targets

SConsEnvironment.InstallDir = InstallDir

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def InstallEups(env, dest, files=[], presetup=""):
    """Install a ups directory, setting absolute versions as appropriate
    (unless you're installing from the trunk, in which case no versions
    are expanded).  Any build/table files present in "./ups" are automatically
    added to files.
    
    If presetup is provided, it's expected to be a dictionary with keys
    product names and values the version that should be installed into
    the table files, overriding eups expandtable's usual behaviour. E.g.
    env.InstallEups(os.path.join(env['prefix'], "ups"), presetup={"sconsUtils" : env['version']})
    """

    if not env.installing:
        return

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
        # Add any build/table files to the desired files
        #
        files = [str(f) for f in files] # in case the user used Glob not glob.glob
        files += glob.glob(os.path.join("ups", "*.build")) + glob.glob(os.path.join("ups","*.table"))
        files = list(set(files))        # remove duplicates

        buildFiles = filter(lambda f: re.search(r"\.build$", f), files)
        build_obj = env.Install(dest, buildFiles)
        
        tableFiles = filter(lambda f: re.search(r"\.table$", f), files)
        table_obj = env.Install(dest, tableFiles)

        miscFiles = filter(lambda f: not re.search(r"\.(build|table)$", f), files)
        misc_obj = env.Install(dest, miscFiles)

        for i in build_obj:
            env.AlwaysBuild(i)

            cmd = "eups expandbuild -i --version %s %s" % (env['version'], str(i))
            env.AddPostAction(i, Action("%s" %(cmd), cmd, ENV = os.environ))

        for i in table_obj:
            env.AlwaysBuild(i)

            cmd = "eups expandtable -i -W '^(?!LOCAL:)' " # version doesn't start "LOCAL:"
            if presetup:
                cmd += presetup + " "
            cmd += str(i)

            env.AddPostAction(i, Action("%s" %(cmd), cmd, ENV = os.environ))

    return dest

SConsEnvironment.InstallEups = InstallEups

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def InstallLSST(self, prefix, dirs, ignoreRegex=None):
    """Install directories in the usual LSST way, handling "doc" and "ups" specially"""
    
    for d in dirs:
        if d == "ups":
            t = self.InstallEups(os.path.join(prefix, "ups"))
        else:
            t = self.InstallDir(prefix, d, ignoreRegex=ignoreRegex)

        self.Alias("install", t)
            
    self.Clean("install", prefix)

SConsEnvironment.InstallLSST = InstallLSST
