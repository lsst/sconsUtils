##
# @file scripts.py
#
# Convenience functions to do the work of standard LSST SConstruct/SConscript files.
#
# @defgroup sconsUtilsScripts Convenience functions for SConstruct/SConscript files
# @{
##

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

##
# @brief Convenience function to replace standard SConstruct boilerplate.
#
# This function:
#  - Calls all SConscript files found in subdirectories.
#  - Configures dependencies.
#  - Sets up installation paths.
#  - Sets how the --clean option works.
#  - Tells SCons to only do MD5 checks when timestamps have changed.
#  - Sets the "include", "lib", "python", and "tests" targets as the defaults
#    to be built when scons is run with no target arguments.
#
# Arguments:
#  @param packageName          Name of the package being built; must correspond to a .cfg file in ups/.
#  @param versionString        Version-control system string to be parsed for version information
#                              ($HeadURL$ for SVN).
#  @param eupsProduct          Name of the EUPS product being built.  Defaults to and is almost always
#                              the name of the package.
#  @param eupsProductPath      An alternate directory where the package should be installed.
#  @param subDirs              An explicit list of subdirectories that should be installed.  By default,
#                              all non-hidden subdirectories will be installed.
#  @param cleanExt             Whitespace delimited sequence of globs for files to remove with --clean.
#  @param ignoreRegex          Regular expression that matches files that should not be installed.
#
#  @returns an SCons Environment object (which is also available as lsst.sconsUtils.env).
##
class BasicSConstruct(object):

    def __new__(cls, packageName, versionString, eupsProduct=None, eupsProductPath=None, cleanExt=None,
                defaults=("lib", "python", "tests"), subDirs=None, ignoreRegex=None):
        cls.initialize(packageName, versionString, eupsProduct, eupsProductPath, cleanExt)
        cls.finish(defaults, subDirs, ignoreRegex)
        return state.env

    @staticmethod
    def initialize(packageName, versionString, eupsProduct=None, eupsProductPath=None, cleanExt=None):
        if cleanExt is None:
            cleanExt = r"*~ core *.so *.os *.o *.pyc *.pkgc"
        dependencies.configure(packageName, versionString, eupsProduct, eupsProductPath)
        state.env.BuildETags()
        state.env.CleanTree(cleanExt)
        for root, dirs, files in os.walk("."):
            dirs = [d for d in dirs if (not d.startswith('.'))]
            if "SConscript" in files:
                SCons.Script.SConscript(os.path.join(root, "SConscript"))

    @staticmethod
    def finish(defaults=("lib", "python", "tests"), subDirs=None, ignoreRegex=None):
        if ignoreRegex is None:
            ignoreRegex = r"(~$|\.pyc$|^\.svn$|\.o|\.os$)"
        if subDirs is None:
            subDirs = []
            for path in os.listdir("."):
                if os.path.isdir(path) and not path.startswith("."):
                    subDirs.append(path)
        install = state.env.InstallLSST(state.env["prefix"],
                                        [subDir for subDir in subDirs if os.path.exists(subDir)],
                                        ignoreRegex=ignoreRegex)
        for name, target in state.targets.iteritems():
            state.env.Requires(install, target)
        state.env.Declare()
        defaults = tuple(state.targets[t] for t in defaults)
        state.env.Default(defaults)
        state.env.Decider("MD5-timestamp") # if timestamps haven't changed, don't do MD5 checks

##
# @brief A scope-only class for SConscript-replacement convenience functions.
#
# All methods of BasicSConscript are static.
##
class BasicSConscript(object):

    ##
    #  @brief Convenience function to replace standard lib/SConscript boilerplate.
    #
    #  With no arguments, this will build a shared library with the same name as the package.
    #  This uses env.SourcesForSharedLibrary to support the optFiles/noOptFiles command-line variables.
    #
    #  @param libName    Name of the shared libray to be built (defaults to env["packageName"]).
    #  @param src        Source to compile into the library.  Defaults to a 4-directory deep glob
    #                    of all *.cc files in \#src.
    #  @param libs       Libraries to link against, either as a string argument to be passed to 
    #                    env.getLibs() or a sequence of actual libraries to pass in.
    ##
    @staticmethod
    def lib(libName=None, src=None, libs="self"):
        if libName is None:
            libName = state.env["packageName"]
        if src is None:
            src = Glob("#src/*.cc") + Glob("#src/*/*.cc") + Glob("#src/*/*/*.cc") + Glob("#src/*/*/*/*.cc")
        src = state.env.SourcesForSharedLibrary(src)
        if isinstance(libs, basestring):
            libs = state.env.getLibs(libs)
        elif libs is None:
            libs = []
        result = state.env.SharedLibrary(libName, src, LIBS=libs)
        state.targets["lib"].extend(result)
        return result

    ##
    #  @brief Convenience function to replace standard python/*/SConscript boilerplate.
    #
    #  With no arguments, this will build a SWIG module with the name determined according
    #  to our current pseudo-convention: last part of env["packageName"], split by underscores,
    #  with "Lib" appended to the end.
    #
    #  @param swigNames    Sequence of SWIG modules to be built (does not include the file extensions).
    #  @param libs         Libraries to link against, either as a string argument to be passed to 
    #                      env.getLibs() or a sequence of actual libraries to pass in.
    #  @param swigSrc      A dictionary of additional source files that go into the modules.  Each
    #                      key should be an entry in swigNames, and each value should be a list
    #                      of additional C++ source files not generated by SWIG.
    ##
    @staticmethod
    def python(swigNames=None, libs="main python", swigSrc=None):
        if swigNames is None:
            swigNames = [state.env["packageName"].split("_")[-1] + "Lib"]
        swigFiles = [File(name + ".i") for name in swigNames]
        if swigSrc is None:
            swigSrc = {}
        for name, node in zip(swigNames, swigFiles):
            swigSrc.setdefault(name, []).append(node)
        if isinstance(libs, basestring):
            libs = state.env.getLibs(libs)
        elif libs is None:
            libs = []
        result = []
        for name, src in swigSrc.iteritems():
            result.extend(state.env.SwigLoadableModule("_" + name, src, LIBS=libs))
        state.targets["python"].extend(result)
        return result

    ##
    #  @brief Convenience function to replace standard doc/SConscript boilerplate.
    #
    #  With no arguments, this will generate a Doxygen config file and run Doxygen
    #  with env.Doxygen(), using the projectName and projectNumber from
    #  env["packageName"] and env["version"], respectively.
    #
    #  This essentially just forwards all arguments (which should be passed as
    #  keyword arguments) to env.Doxygen().
    ##
    @staticmethod
    def doc(config="doxygen.conf.in", projectName=None, projectNumber=None, **kw):
        if projectName is None:
            projectName = ".".join(["lsst"] + state.env["packageName"].split("_"))
        if projectNumber is None:
            projectNumber = state.env["version"]
        result = state.env.Doxygen(
            "doxygen.conf.in", projectName=projectName, projectNumber=projectNumber,
            includes=state.env.doxygen["includes"],
            useTags=state.env.doxygen["tags"],
            makeTag=(state.env["packageName"] + ".tag"),
            **kw
            )
        state.targets["doc"].extend(result)
        return result

    ##
    #  @brief Convenience function to replace standard tests/SConscript boilerplate.
    #
    #  With no arguments, will attempt to figure out which files should be run as tests
    #  and which are support code (like SWIG modules).
    #
    #  Python tests will be marked as dependent on the entire \#python directory and
    #  any SWIG modules built in the tests directory.  This should ensure tests are always
    #  run when their results might have changed, but may result in them being re-run more often
    #  than necessary.
    #
    #  @param pyTests          A sequence of Python tests to run (including .py extensions).
    #                          Defaults to a *.py glob of the tests directory, minus any
    #                          files corresponding to the SWIG modules in swigFiles.
    #  @param ccTests          A sequence of C++ unit tests to run (including .cc extensions).
    #                          Defaults to a *.cc glob of the tests directory, minus any
    #                          files that end with *_wrap.cc and files present in swigSrc.
    #  @param swigNames        A sequence of SWIG modules to build (NOT including .i extensions).
    #  @param swigSrc          Additional source files to be compiled into SWIG modules, as a
    #                          dictionary; each key must be an entry in swigNames, and each
    #                          value a list of additional source files.
    #  @param ignoreList       List of ignored tests to be passed to tests.Control (note that
    #                          ignored tests will be built, but not run).
    #  @param args             A dictionary of program arguments for tests, passed directly
    #                          to tests.Control.
    ##
    @staticmethod
    def tests(pyTests=None, ccTests=None, swigNames=None, swigSrc=None, ignoreList=None, args=None):
        if swigNames is None:
            swigFiles = Glob("*.i")
            swigNames = [_getFileBase(node) for node in swigFiles]
        else:
            swigFiles = [File(name + ".i") for name in swigNames]
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
        if ignoreList is None:
            ignoreList = []
        s = lambda l: [str(i) for i in l]
        state.log.info("SWIG modules for tests: %s" % s(swigFiles))
        state.log.info("Python tests: %s" % s(pyTests))
        state.log.info("C++ tests: %s" % s(ccTests))
        state.log.info("Ignored tests: %s" % ignoreList)
        control = tests.Control(state.env, ignoreList=ignoreList, args=args, verbose=True)
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
        result = ccTests + pyTests
        state.targets["tests"].extend(result)
        return result

    ##
    #  @brief Convenience function to replace standard examples/SConscript boilerplate.
    #
    #  @param ccExamples       A sequence of C++ examples to build (including .cc extensions).
    #                          Defaults to a *.cc glob of the examples directory, minus any
    #                          files that end with *_wrap.cc and files present in swigSrc.
    #  @param swigNames        A sequence of SWIG modules to build (NOT including .i extensions).
    #  @param swigSrc          Additional source files to be compiled into SWIG modules, as a
    #                          dictionary; each key must be an entry in swigNames, and each
    #                          value a list of additional source files.
    #
    #  @return a tuple of (ccExamples, swigMods)
    ##
    @staticmethod
    def examples(ccExamples=None, swigNames=None, swigSrc=None):
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
        state.log.info("SWIG modules for examples: %s" % swigFiles)
        state.log.info("C++ examples: %s" % ccExamples)
        for ccExample in ccExamples:
            state.env.Program(ccExample, LIBS=state.env.getLibs("main"))
        swigMods = []
        for name, src in swigSrc.iteritems():
            swigMods.extend(
                state.env.SwigLoadableModule("_" + name, src, LIBS=state.env.getLibs("main python"))
                )
        result = ccExamples + swigMods
        state.targets["examples"].extend(result)
        return result

## @}
