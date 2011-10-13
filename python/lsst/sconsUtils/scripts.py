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
from . import tests

def _getFileBase(node):
    name, ext = os.path.splitext(os.path.basename(str(node)))
    return name

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
    state.env.Default(*(item for item in ("include", "lib", "python", "tests") if os.path.isdir(item)))
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
    def python(swigNames=None, libs="main python"):
        if swigNames is None:
            swigNames = [state.env["packageName"].split("_")[-1] + "Lib"]
        if isinstance(libs, basestring):
            libs = state.env.getLibs(libs)
        elif libs is None:
            libs = []
        result = []
        for swigName in swigNames:
            result.extend(state.env.SwigLoadableModule("_" + swigName, Split(swigName + ".i"), LIBS=libs))
        return result

    @staticmethod
    def doc(config="doxygen.conf.in", projectName=None, projectNumber=None, **kw):
        if projectName is None:
            projectName = ".".join(["lsst"] + state.env["packageName"].split("_"))
        if projectNumber is None:
            projectNumber = state.env["version"]
        return state.env.Doxygen(
            "doxygen.conf.in", projectName=projectName, projectNumber=projectNumber,
            includes=state.env.doxygen["includes"],
            useTags=state.env.doxygen["tags"],
            makeTag=(state.env["packageName"] + ".tag"),
            **kw
            )

    @staticmethod
    def tests(pyTests=None, ccTests=None, swigNames=None, swigSrc=None, ignoreList=None):
        """Standard tests/SConscript boilerplate.

        Arguments:
          @param pyTests          A sequence of Python tests to run (including .py extensions).
                                  Defaults to a *.py glob of the tests directory, minus any
                                  files corresponding to the SWIG modules in swigFiles.
          @param ccTests          A sequence of C++ unit tests to run (including .cc extensions).
                                  Defaults to a *.cc glob of the tests directory, minus any
                                  files that end with *_wrap.cc and files present in swigSrc.
          @param swigNames        A sequence of SWIG modules to build (NOT including .i extensions).
          @param swigSrc          Additional source files to be compiled into SWIG modules, as a
                                  dictionary; each key must be an entry in swigNames, and each
                                  value a list of additional source files.
          @param ignoreList       List of ignored tests to be passed to tests.Control (note that
                                  ignored tests will be built, but not run).
        """
        if swigNames is None:
            swigFiles = Glob("*.i")
            swigNames = [_getFileBase(node) for node in swigFiles]
        else:
            swigFiles = [File(name) for name in swigNames]
        if swigSrc is None:
            swigSrc = {}
        allSwigSrc = set()
        for name, node in zip(swigNames, swigFiles):
            src = swigSrc.setdefault(name, [])
            allSwigSrc.update(str(element) for element in src)
            src.append(node)
        if pyTests is None:
            pyTests = [node for node in Glob("*.py") if _getFileBase(node) not in swigNames]
        if ccTests is None:
            ccTests = [node for node in Glob("*.cc") 
                       if (not str(node).endswith("_wrap.cc")) and str(node) not in allSwigSrc]
        if swigSrc is None:
            swigSrc = dict((name, ()) for name in swigNames)
        if ignoreList is None:
            ignoreList = []
        state.log.info("SWIG modules for tests: %s" % swigFiles)
        state.log.info("Python tests: %s" % pyTests)
        state.log.info("C++ tests: %s" % ccTests)
        state.log.info("Ignored tests: %s" % ignoreList)
        control = tests.Control(state.env, ignoreList=ignoreList, verbose=True)
        for ccTest in ccTests:
            state.env.Program(ccTest, LIBS=state.env.getLibs("main test"))
        swigMods = []
        for name, src in swigSrc.iteritems():
            swigMods.extend(
                state.env.SwigLoadableModule("_" + name, src, LIBS=state.env.getLibs("main python"))
            )
        ccTests = [control.run(str(node)) for node in ccTests]
        pyTests = [control.run(str(node)) for node in pyTests]
        for pyTest in pyTests:
            state.env.Depends(pyTest, swigMods)
            state.env.Depends(pyTest, "#python")
        return ccTests, pyTests

    @staticmethod
    def examples(ccExamples=None, swigNames=None, swigSrc=None):
        """Standard examples/SConscript boilerplate.

        Arguments:
          @param ccExamples       A sequence of C++ examples to build (including .cc extensions).
                                  Defaults to a *.cc glob of the tests directory, minus any
                                  files that end with *_wrap.cc and files present in swigSrc.
          @param swigNames        A sequence of SWIG modules to build (NOT including .i extensions).
          @param swigSrc          Additional source files to be compiled into SWIG modules, as a
                                  dictionary; each key must be an entry in swigNames, and each
                                  value a list of additional source files.
        """
        if swigNames is None:
            swigFiles = Glob("*.i")
            swigNames = [_getFileBase(node) for node in swigFiles]
        else:
            swigFiles = [File(name) for name in swigNames]
        if swigSrc is None:
            swigSrc = {}
        allSwigSrc = set()
        for name, node in zip(swigNames, swigFiles):
            src = swigSrc.setdefault(name, [])
            allSwigSrc.update(str(element) for element in src)
            src.append(node)
        if ccExamples is None:
            ccExamples = [node for node in Glob("*.cc") 
                          if (not str(node).endswith("_wrap.cc")) and str(node) not in allSwigSrc]
        if swigSrc is None:
            swigSrc = dict((name, ()) for name in swigNames)
        state.log.info("SWIG modules for examples: %s" % swigFiles)
        state.log.info("C++ examples: %s" % ccExamples)
        for ccExample in ccExamples:
            state.env.Program(ccExample, LIBS=state.env.getLibs("main"))
        swigMods = []
        for name, src in swigSrc.iteritems():
            swigMods.extend(
                state.env.SwigLoadableModule("_" + name, src, LIBS=state.env.getLibs("main python"))
            )
        return ccExamples, swigMods
