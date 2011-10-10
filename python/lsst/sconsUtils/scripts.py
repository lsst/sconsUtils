#
# @file scripts.py
#
# Convenience functions to do the work of standard LSST SConstruct/SConscript files.
#

import os.path
from SCons.Script import *
from .environment import MakeEnv, CleanTree
from . import utils

def BasicSConstruct(packageName, versionString, eupsProduct=None, eupsProductPath=None, variables=None, 
                    subDirs=None, cleanExt=None, ignoreRegex=None, traceback=True):
    utils.log.traceback = traceback
    if subDirs is None:
        subDirs = []
        for path in os.listdir("."):
            if os.path.isdir(path) and not path.startswith("."):
                subDirs.append(path)
    if cleanExt is None:
        cleanExt = r"*~ core *.so *.os *.o *.pyc *.pkgc"
    if ignoreRegex is None:
        ignoreRegex = r"(~$|\.pyc$|^\.svn$|\.o|\.os$)"
    env = MakeEnv(packageName, versionString, eupsProduct=eupsProduct, eupsProductPath=eupsProductPath)
    for root, dirs, files in os.walk("."):
        dirs = [d for d in dirs if (not d.startswith('.'))]
        if "SConscript" in files:
            SConscript(os.path.join(root, "SConscript"))
    env.InstallLSST(env["prefix"], [subDir for subDir in subDirs if os.path.exists(subDir)],
                    ignoreRegex=ignoreRegex)
    env.BuildETags()
    CleanTree(cleanExt)
    env.Declare()
    return env

class BasicSConscript(object):

    def __init__(self, env):
        self.env = env

    def lib(self, libName=None, src=None, libs="self"):
        if libName is None:
            libName = self.env["packageName"]
        if src is None:
            src = Glob("#src/*.cc") + Glob("#src/*/*.cc") + Glob("#src/*/*/*.cc")
        if isinstance(libs, basestring):
            libs = self.env.getLibs(libs)
        elif libs is None:
            libs = []
        return self.env.SharedLibrary(libName, src, LIBS=libs)

    def python(self, swigName=None, libs="main python"):
        if swigName is None:
            swigName = self.env["packageName"].split("_")[-1] + "Lib"
        if isinstance(libs, basestring):
            libs = self.env.getLibs(libs)
        elif libs is None:
            libs = []
        return self.env.LoadableModuleIncomplete("_" + swigName, Split(swigName + ".i"), LIBS=libs)
