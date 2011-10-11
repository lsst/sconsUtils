#
# @file scripts.py
#
# Convenience functions to do the work of standard LSST SConstruct/SConscript files.
#

import os.path
from SCons.Script import *

from . import dependencies
from . import builders
from . import installation
from . import state

def BasicSConstruct(packageName, versionString, eupsProduct=None, eupsProductPath=None, 
                    subDirs=None, cleanExt=None, ignoreRegex=None):
    if subDirs is None:
        subDirs = []
        for path in os.listdir("."):
            if os.path.isdir(path) and not path.startswith("."):
                subDirs.append(path)
    if cleanExt is None:
        cleanExt = r"*~ core *.so *.os *.o *.pyc *.pkgc"
    if ignoreRegex is None:
        ignoreRegex = r"(~$|\.pyc$|^\.svn$|\.o|\.os$)"
    dependencies.configure(packageName, versionString, eupsProduct, eupsProductPath)
    for root, dirs, files in os.walk("."):
        dirs = [d for d in dirs if (not d.startswith('.'))]
        if "SConscript" in files:
            SCons.Script.SConscript(os.path.join(root, "SConscript"))
    state.env.InstallLSST(state.env["prefix"], [subDir for subDir in subDirs if os.path.exists(subDir)],
                          ignoreRegex=ignoreRegex)
    state.env.BuildETags()
    state.env.CleanTree(cleanExt)
    state.env.Declare()
    return state.env

class BasicSConscript(object):

    @staticmethod
    def lib(libName=None, src=None, libs="self"):
        if libName is None:
            libName = state.env["packageName"]
        if src is None:
            src = Glob("#src/*.cc") + Glob("#src/*/*.cc") + Glob("#src/*/*/*.cc")
        if isinstance(libs, basestring):
            libs = state.env.getLibs(libs)
        elif libs is None:
            libs = []
        return state.env.SharedLibrary(libName, src, LIBS=libs)

    @staticmethod
    def python(swigName=None, libs="main python"):
        if swigName is None:
            swigName = state.env["packageName"].split("_")[-1] + "Lib"
        if isinstance(libs, basestring):
            libs = state.env.getLibs(libs)
        elif libs is None:
            libs = []
        return state.env.SwigLoadableModule("_" + swigName, Split(swigName + ".i"), LIBS=libs)
