##
# @file scripts.py
#
# Convenience functions to do the work of standard LSST SConstruct/SConscript files.
#
# @defgroup sconsUtilsScripts Convenience functions for SConstruct/SConscript files
# @{
##
from __future__ import absolute_import, division, print_function
import os.path
import re
import sys
from stat import ST_MODE
from SCons.Script import *
from distutils.spawn import find_executable

from . import dependencies
from . import builders
from . import installation
from . import state
from . import tests
from . import utils

DEFAULT_TARGETS = ("lib", "python", "tests", "examples", "doc", "shebang")


def _getFileBase(node):
    name, ext = os.path.splitext(os.path.basename(str(node)))
    return name

##
# @brief A scope-only class for SConstruct-replacement convenience functions.
#
# The boilerplate for a standard LSST SConstruct file is replaced by two static methods:
# initialize() and finish().  The former configures dependencies, sets up package-dependent
# environment variables, and calls any SConscript files found in subdirectories, while the
# latter sets up installation paths, default targets, and explicit dependencies.
#
# Calling BasicSConstruct as a function invokes its __new__ method, which calls both
# initialize() and finish(), and should be used when the SConstruct file doesn't need to
# do anything other than what they provide.
##
class BasicSConstruct(object):

    _initializing = False

    ##
    # @brief Convenience function to replace standard SConstruct boilerplate.
    #
    # This is a shortcut for
    # @code
    # BasicSConstruct.initialize(...)
    # BasicSConstruct.finalize(...)
    # @endcode
    #
    # This returns the sconsUtils.env Environment object rather than
    # a BasicSConstruct instance (which would be useless).
    ##
    def __new__(cls, packageName, versionString=None, eupsProduct=None, eupsProductPath=None, cleanExt=None,
                defaultTargets=DEFAULT_TARGETS,
                subDirList=None, ignoreRegex=None,
                versionModuleName="python/lsst/%s/version.py", noCfgFile=False):
        cls.initialize(packageName, versionString, eupsProduct, eupsProductPath, cleanExt,
                       versionModuleName, noCfgFile=noCfgFile)
        cls.finish(defaultTargets, subDirList, ignoreRegex)
        return state.env

    ##
    # @brief Convenience function to replace standard SConstruct boilerplate (step 1).
    #
    # This function:
    #  - Calls all SConscript files found in subdirectories.
    #  - Configures dependencies.
    #  - Sets how the --clean option works.
    #
    #  @param packageName          Name of the package being built; must correspond to a .cfg file in ups/.
    #  @param versionString        Version-control system string to be parsed for version information
    #                              ($HeadURL$ for SVN).  Defaults to "git" if not set or None.
    #  @param eupsProduct          Name of the EUPS product being built.  Defaults to and is almost always
    #                              the name of the package.
    #  @param eupsProductPath      An alternate directory where the package should be installed.
    #  @param cleanExt             Whitespace delimited sequence of globs for files to remove with --clean.
    #  @param versionModuleName    If non-None, builds a version.py module as this file; '%s' is replaced with
    #                              the name of the package.
    # @param noCfgFile             If True, this package has no .cfg file
    #
    #  @returns an SCons Environment object (which is also available as lsst.sconsUtils.env).
    ##
    @classmethod
    def initialize(cls, packageName, versionString=None, eupsProduct=None, eupsProductPath=None,
                   cleanExt=None, versionModuleName="python/lsst/%s/version.py", noCfgFile=False):
        if cls._initializing:
            state.log.fail("Recursion detected; an SConscript file should not call BasicSConstruct.")
        cls._initializing = True
        if cleanExt is None:
            cleanExt = r"*~ core *.so *.os *.o *.pyc *.pkgc"
        dependencies.configure(packageName, versionString, eupsProduct, eupsProductPath, noCfgFile)
        state.env.BuildETags()
        state.env.CleanTree(cleanExt)
        if versionModuleName is not None:
            try:
                versionModuleName = versionModuleName % "/".join(packageName.split("_"))
            except TypeError:
                pass
            state.targets["version"] = state.env.VersionModule(versionModuleName)
        for root, dirs, files in os.walk("."):
            if "SConstruct" in files and root != ".":
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if (not d.startswith('.'))]
            dirs.sort() # happy coincidence that include < libs < python < tests
            if "SConscript" in files:
                state.log.info("Using Sconscript at %s/SConscript" % root)
                SCons.Script.SConscript(os.path.join(root, "SConscript"))
        cls._initializing = False
        return state.env

    ##
    # @brief Convenience function to replace standard SConstruct boilerplate (step 2).
    #
    # This function:
    #  - Sets up installation paths.
    #  - Tells SCons to only do MD5 checks when timestamps have changed.
    #  - Sets the "include", "lib", "python", and "tests" targets as the defaults
    #    to be built when scons is run with no target arguments.
    #
    #  @param subDirList           An explicit list of subdirectories that should be installed.  By default,
    #                              all non-hidden subdirectories will be installed.
    #  @param defaultTargets       A sequence of targets (see state.targets) that should be built when
    #                              scons is run with no arguments.
    #  @param ignoreRegex          Regular expression that matches files that should not be installed.
    #
    #  @returns an SCons Environment object (which is also available as lsst.sconsUtils.env).
    ##
    @staticmethod
    def finish(defaultTargets=DEFAULT_TARGETS,
               subDirList=None, ignoreRegex=None):
        if ignoreRegex is None:
            ignoreRegex = r"(~$|\.pyc$|^\.svn$|\.o|\.os$)"
        if subDirList is None:
            subDirList = []
            for path in os.listdir("."):
                if os.path.isdir(path) and not path.startswith("."):
                    subDirList.append(path)
        install = state.env.InstallLSST(state.env["prefix"],
                                        [subDir for subDir in subDirList],
                                        ignoreRegex=ignoreRegex)
        for name, target in state.targets.items():
            state.env.Requires(install, target)
            state.env.Alias(name, target)
        state.env.Requires(state.targets["python"], state.targets["version"])
        declarer = state.env.Declare()
        state.env.Requires(declarer, install) # Ensure declaration fires after installation available
        state.env.Default([t for t in defaultTargets if os.path.exists(t)])
        # shebang target is not named same as relevant directory so we must be explicit
        if "shebang" in defaultTargets and os.path.exists("bin.src"):
            state.env.Default("shebang")
        if "version" in state.targets:
            state.env.Default(state.targets["version"])
        state.env.Requires(state.targets["tests"], state.targets["version"])
        state.env.Decider("MD5-timestamp") # if timestamps haven't changed, don't do MD5 checks
        #
        # Check if any of the tests failed by looking for *.failed files.
        # Perform this test just before scons exits
        #
        # N.b. the test is written in sh not python as then we can use @ to suppress output
        #
        if "tests" in [str(t) for t in BUILD_TARGETS]:
            testsDir = os.path.join(os.getcwd(), "tests", ".tests")
            checkTestStatus_command = state.env.Command('checkTestStatus', [], """
                @ if [ -d %s ]; then \
                      nfail=`find %s -name \*.failed | wc -l | sed -e 's/ //g'`; \
                      if [ $$nfail -gt 0 ]; then \
                          echo "$$nfail tests failed" >&2; exit 1; \
                      fi; \
                  fi; \
            """ % (testsDir, testsDir))

            state.env.Depends(checkTestStatus_command, BUILD_TARGETS) # this is why the check runs last
            BUILD_TARGETS.extend(checkTestStatus_command)
            state.env.AlwaysBuild(checkTestStatus_command)

##
# @brief A scope-only class for SConscript-replacement convenience functions.
#
# All methods of BasicSConscript are static.  All of these functions update the state.targets
# dictionary of targets used to set default targets and fix build dependencies; if you build anything
# without using BasicSConscript methods, be sure to manually it to the state.targets dict.
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
    #  @brief   Handles shebang rewriting
    #
    #  With no arguments looks in bin.src/ and copies to bin/
    #  If utils.needShebangRewrite() is False the shebang will
    #  not be modified.
    #
    #  Only Python files requiring a shebang rewrite should be placed
    #  in bin.src/  Do not place executable binaries in this directory.
    #
    #  @param src  Override the source list
    ##
    @staticmethod
    def shebang(src=None):
        # check if Python is called on the first line with this expression
        # This comes from distutils copy_scripts
        FIRST_LINE_RE = re.compile(r'^#!.*python[0-9.]*([ \t].*)?$')
        doRewrite = utils.needShebangRewrite()
        def rewrite_shebang(target, source, env):
            """Copy source to target, rewriting the shebang"""
            # Currently just use this python
            usepython = sys.executable
            for targ, src in zip(target, source):
                with open(str(src), "r") as srcfd:
                    with open(str(targ), "w") as outfd:
                        first_line = srcfd.readline()
                        # Always match the first line so we can warn people
                        # if an attempt is being made to rewrite a file that should
                        # not be rewritten
                        match = FIRST_LINE_RE.match(first_line)
                        if match and doRewrite:
                            post_interp = match.group(1) or ''
                            outfd.write("#!{}{}\n".format(usepython, post_interp))
                        else:
                            if not match:
                                state.log.warn("Could not rewrite shebang of {}. Please check"
                                               " file or move it to bin directory.".format(str(src)))
                            outfd.write(first_line)
                        for line in srcfd.readlines():
                            outfd.write(line)
                # Ensure the bin/ file is executable
                oldmode = os.stat(str(targ))[ST_MODE] & 0o7777
                newmode = (oldmode | 0o555) & 0o7777
                if newmode != oldmode:
                    state.log.info("changing mode of {} from {} to {}".format(
                                   str(targ), oldmode, newmode))
                    os.chmod(str(targ), newmode)


        if src is None:
            src = Glob("#bin.src/*")
        for s in src:
            if str(s) != "SConscript":
                result = state.env.Command(target=os.path.join(Dir("#bin").abspath, str(s)),
                                           source=s, action=rewrite_shebang)
                state.targets["shebang"].extend(result)

    ##
    #  @brief Convenience function to replace standard python/*/SConscript boilerplate.
    #
    #  With no arguments, this will build a SWIG module with the name determined according
    #  to our current pseudo-convention: last part of env["packageName"], split by underscores,
    #  with "Lib" appended to the end.
    #
    #  @param swigNameList    Sequence of SWIG modules to be built (does not include the file extensions).
    #  @param libs         Libraries to link against, either as a string argument to be passed to
    #                      env.getLibs() or a sequence of actual libraries to pass in.
    #  @param swigSrc      A dictionary of additional source files that go into the modules.  Each
    #                      key should be an entry in swigNameList, and each value should be a list
    #                      of additional C++ source files not generated by SWIG.
    ##
    @staticmethod
    def python(swigNameList=None, libs="main python", swigSrc=None):
        if swigNameList is None:
            swigNameList = [state.env["packageName"].split("_")[-1] + "Lib"]
        swigFileList = [File(name + ".i") for name in swigNameList]
        if swigSrc is None:
            swigSrc = {}
        for name, node in zip(swigNameList, swigFileList):
            swigSrc.setdefault(name, []).append(node)
        if isinstance(libs, basestring):
            libs = state.env.getLibs(libs)
        elif libs is None:
            libs = []
        result = []
        for name, src in swigSrc.items():
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
        if not find_executable("doxygen"):
            state.log.warn("doxygen executable not found; skipping documentation build.")
            return []
        if projectName is None:
            projectName = ".".join(["lsst"] + state.env["packageName"].split("_"))
        if projectNumber is None:
            projectNumber = state.env["version"]
        result = state.env.Doxygen(
            config, projectName=projectName, projectNumber=projectNumber,
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
    #  @param pyList           A sequence of Python tests to run (including .py extensions).
    #                          Defaults to a *.py glob of the tests directory, minus any
    #                          files corresponding to the SWIG modules in swigFileList.
    #  @param ccList           A sequence of C++ unit tests to run (including .cc extensions).
    #                          Defaults to a *.cc glob of the tests directory, minus any
    #                          files that end with *_wrap.cc and files present in swigSrc.
    #  @param swigNameList     A sequence of SWIG modules to build (NOT including .i extensions).
    #  @param swigSrc          Additional source files to be compiled into SWIG modules, as a
    #                          dictionary; each key must be an entry in swigNameList, and each
    #                          value a list of additional source files.
    #  @param ignoreList       List of ignored tests to be passed to tests.Control (note that
    #                          ignored tests will be built, but not run).
    #  @param nobuildList      List of tests that should not even be built.
    #  @param args             A dictionary of program arguments for tests, passed directly
    #                          to tests.Control.
    ##
    @staticmethod
    def tests(pyList=None, ccList=None, swigNameList=None, swigSrc=None,
              ignoreList=None, noBuildList=None,
              args=None):
        if noBuildList is None:
            noBuildList = []
        if swigNameList is None:
            swigFileList = Glob("*.i")
            swigNameList = [_getFileBase(node) for node in swigFileList]
        else:
            swigFileList = [File(name + ".i") for name in swigNameList]
        if swigSrc is None:
            swigSrc = {}
        allSwigSrc = set()
        for name, node in zip(swigNameList, swigFileList):
            src = swigSrc.setdefault(name, [])
            allSwigSrc.update(str(element) for element in src)
            src.append(node)
        if pyList is None:
            pyList = [node for node in Glob("*.py")
                      if _getFileBase(node) not in swigNameList
                      and os.path.basename(str(node)) not in noBuildList]
        if ccList is None:
            ccList = [node for node in Glob("*.cc")
                      if (not str(node).endswith("_wrap.cc")) and str(node) not in allSwigSrc
                      and os.path.basename(str(node)) not in noBuildList]
        if ignoreList is None:
            ignoreList = []
        s = lambda l: [str(i) for i in l]
        state.log.info("SWIG modules for tests: %s" % s(swigFileList))
        state.log.info("Python tests: %s" % s(pyList))
        state.log.info("C++ tests: %s" % s(ccList))
        state.log.info("Files that will not be built: %s" % noBuildList)
        state.log.info("Ignored tests: %s" % ignoreList)
        control = tests.Control(state.env, ignoreList=ignoreList, args=args, verbose=True)
        for ccTest in ccList:
            state.env.Program(ccTest, LIBS=state.env.getLibs("main test"))
        swigMods = []
        for name, src in swigSrc.items():
            swigMods.extend(
                state.env.SwigLoadableModule("_" + name, src, LIBS=state.env.getLibs("main python"))
            )
        ccList = [control.run(str(node)) for node in ccList]
        pyList = [control.run(str(node)) for node in pyList]
        for pyTest in pyList:
            state.env.Depends(pyTest, swigMods)
            state.env.Depends(pyTest, state.targets["python"])
        result = ccList + pyList
        state.targets["tests"].extend(result)
        return result

    ##
    #  @brief Convenience function to replace standard examples/SConscript boilerplate.
    #
    #  @param ccList           A sequence of C++ examples to build (including .cc extensions).
    #                          Defaults to a *.cc glob of the examples directory, minus any
    #                          files that end with *_wrap.cc and files present in swigSrc.
    #  @param swigNameList     A sequence of SWIG modules to build (NOT including .i extensions).
    #  @param swigSrc          Additional source files to be compiled into SWIG modules, as a
    #                          dictionary; each key must be an entry in swigNameList, and each
    #                          value a list of additional source files.
    ##
    @staticmethod
    def examples(ccList=None, swigNameList=None, swigSrc=None):
        if swigNameList is None:
            swigFileList = Glob("*.i")
            swigNameList = [_getFileBase(node) for node in swigFileList]
        else:
            swigFileList = [File(name) for name in swigNameList]
        if swigSrc is None:
            swigSrc = {}
        allSwigSrc = set()
        for name, node in zip(swigNameList, swigFileList):
            src = swigSrc.setdefault(name, [])
            allSwigSrc.update(str(element) for element in src)
            src.append(node)
        if ccList is None:
            ccList = [node for node in Glob("*.cc")
                          if (not str(node).endswith("_wrap.cc")) and str(node) not in allSwigSrc]
        state.log.info("SWIG modules for examples: %s" % swigFileList)
        state.log.info("C++ examples: %s" % ccList)
        results = []
        for src in ccList:
            results.extend(state.env.Program(src, LIBS=state.env.getLibs("main")))
        swigMods = []
        for name, src in swigSrc.items():
            results.extend(
                state.env.SwigLoadableModule("_" + name, src, LIBS=state.env.getLibs("main python"))
                )
        for result in results:
            state.env.Depends(result, state.targets["lib"])
        state.targets["examples"].extend(results)
        return results

## @}
