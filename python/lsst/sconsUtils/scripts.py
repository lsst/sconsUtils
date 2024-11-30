# This file is part of sconsUtils.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Convenience functions to do the work of standard LSST SConstruct/SConscript
files.
"""

import os.path
import re
import shlex
import shutil
import warnings
from stat import ST_MODE

from SCons.Script import BUILD_TARGETS, Dir, File, GetOption, Glob, SConscript

from . import dependencies, state, tests, utils

DEFAULT_TARGETS = ("lib", "python", "shebang", "tests", "examples", "doc")


def _getFileBase(node):
    name, ext = os.path.splitext(os.path.basename(str(node)))
    return name


class BasicSConstruct:
    """A scope-only class for SConstruct-replacement convenience functions.

    The boilerplate for a standard LSST SConstruct file is replaced by two
    static methods: ``initialize()`` and ``finish()``.  The former configures
    dependencies, sets up package-dependent environment variables, and calls
    any SConscript files found in subdirectories, while the latter sets up
    installation paths, default targets, and explicit dependencies.

    Calling ``BasicSConstruct`` as a function invokes its ``__new__`` method,
    which calls both `~lsst.sconsUtils.BasicSConstruct.initialize` and
    `~lsst.sconsUtils.BasicSConstruct.finish`, and should be used when the
    SConstruct file doesn't need to do anything other than what they provide.
    When called this way it returns the `~lsst.sconsUtils.env` Environment
    object rather than a `~lsst.sconsUtils.scripts.BasicSConstruct` instance
    (which would be useless).
    """

    _initializing = False

    def __new__(
        cls,
        packageName,
        versionString=None,
        eupsProduct=None,
        eupsProductPath=None,
        cleanExt=None,
        defaultTargets=DEFAULT_TARGETS,
        subDirList=None,
        ignoreRegex=None,
        versionModuleName="python/lsst/%s/version.py",
        noCfgFile=False,
        sconscriptOrder=None,
        disableCc=False,
    ):
        cls.initialize(
            packageName,
            versionString,
            eupsProduct,
            eupsProductPath,
            cleanExt,
            versionModuleName,
            noCfgFile=noCfgFile,
            sconscriptOrder=sconscriptOrder,
            disableCc=disableCc,
        )
        cls.finish(defaultTargets, subDirList, ignoreRegex)
        return state.env

    @classmethod
    def initialize(
        cls,
        packageName,
        versionString=None,
        eupsProduct=None,
        eupsProductPath=None,
        cleanExt=None,
        versionModuleName="python/lsst/%s/version.py",
        noCfgFile=False,
        sconscriptOrder=None,
        disableCc=False,
    ):
        """Convenience function to replace standard SConstruct boilerplate
        (step 1).

        This function:

        - Calls all SConscript files found in subdirectories.
        - Configures dependencies.
        - Sets how the ``--clean`` option works.

        Parameters
        ----------
        packageName : `str`
            Name of the package being built; must correspond to a .cfg
            file in ``ups/``.
        versionString : `str`, optional
            Version-control system string to be parsed for version information
            (``$HeadURL$`` for SVN).  Defaults to "git" if not set or `None`.
        eupsProduct : `str`, optional
            Name of the EUPS product being built.  Defaults to and is almost
            always the name of the package.
        eupsProductPath : `str`, optional
            An alternate directory where the package should be installed.
        cleanExt : `list`, optional
            Whitespace delimited sequence of globs for files to remove with
            ``--clean``.
        versionModuleName : `str`, optional
            If non-None, builds a ``version.py`` module as this file; ``'%s'``
            is replaced with the name of the package.
        noCfgFile : `bool`, optional
            If True, this package has no .cfg file
        sconscriptOrder : `list`, optional
            A sequence of directory names that set the order for processing
            SConscript files discovered in nested directories.  Full
            directories need not be specified, but paths must begin at the
            root.  For example, ``["lib", "python"]`` will ensure that
            ``lib/SConscript`` is run before both ``python/foo/SConscript``
            and ``python/bar/SConscript``.  The default order should work for
            most LSST SCons builds, as it provides the correct ordering for
            the ``lib``, ``python``, ``tests``, ``examples``, and ``doc``
            targets.  If this argument is provided, it must include the subset
            of that list that is valid for the package, in that order.
        disableCC : `bool`, optional
            Should the C++ compiler check be disabled? Disabling this checks
            allows a faster startup and permits building on systems that don't
            meet the requirements for the C++ compilter (e.g., for
            pure-python packages).

        Returns
        -------
        env : `lsst.sconsUtils.env`
            A SCons Environment object.
        """
        if not disableCc:
            state._configureCommon()
            state._saveState()
        if cls._initializing:
            state.log.fail("Recursion detected; an SConscript file should not call BasicSConstruct.")
        cls._initializing = True
        dependencies.configure(packageName, versionString, eupsProduct, eupsProductPath, noCfgFile)
        state.env.BuildETags()
        if cleanExt is None:
            cleanExt = r"*~ core core.[1-9]* *.so *.os *.o *.pyc *.pkgc"
        state.env.CleanTree(cleanExt, "__pycache__ .pytest_cache")
        if versionModuleName is not None:
            try:
                versionModuleName = versionModuleName % "/".join(packageName.split("_"))
            except TypeError:
                pass
            state.targets["version"] = state.env.VersionModule(versionModuleName)
        scripts = []
        for root, dirs, files in os.walk("."):
            if "SConstruct" in files and root != ".":
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            dirs.sort()  # os.walk order is not specified, but we want builds to be deterministic
            if "SConscript" in files:
                scripts.append(os.path.join(root, "SConscript"))
        if sconscriptOrder is None:
            sconscriptOrder = DEFAULT_TARGETS

        # directory for shebang target is bin.src
        sconscriptOrder = [t if t != "shebang" else "bin.src" for t in sconscriptOrder]

        def key(path):
            for i, item in enumerate(sconscriptOrder):
                if path.lstrip("./").startswith(item):
                    return i
            return len(sconscriptOrder)

        scripts.sort(key=key)
        for script in scripts:
            state.log.info(f"Using SConscript at {script}")
            SConscript(script)
        cls._initializing = False
        return state.env

    @staticmethod
    def finish(defaultTargets=DEFAULT_TARGETS, subDirList=None, ignoreRegex=None):
        """Convenience function to replace standard SConstruct boilerplate
        (step 2).

        This function:

        - Sets up installation paths.
        - Tells SCons to only do MD5 checks when timestamps have changed.
        - Sets the "include", "lib", "python", and "tests" targets as the
          defaults to be built when scons is run with no target arguments.

        Parameters
        ----------
        subDirList : `list`
            An explicit list of subdirectories that should be installed.
            By default, all non-hidden subdirectories will be installed.
        defaultTargets : `list`
            A sequence of targets (see `lsst.sconsUtils.state.targets`)
            that should be built when scons is run with no arguments.
        ignoreRegex : `str`
            Regular expression that matches files that should not be installed.

        Returns
        -------
        env : `lsst.sconsUtils.env`
            A SCons Environment.
        """
        if ignoreRegex is None:
            ignoreRegex = r"(~$|\.pyc$|^\.svn$|\.o|\.os$)"
        if subDirList is None:
            subDirList = []
            for path in os.listdir("."):
                if os.path.isdir(path) and not path.startswith("."):
                    subDirList.append(path)
        if "bin.src" in subDirList and "shebang" in state.targets and state.targets["shebang"]:
            # shebang makes a directory that should be installed
            subDirList += ["bin"]
        install = state.env.InstallLSST(state.env["prefix"], list(subDirList), ignoreRegex=ignoreRegex)
        for name, target in state.targets.items():
            state.env.Requires(install, target)
            state.env.Alias(name, target)
        state.env.Requires(state.targets["python"], state.targets["version"])
        declarer = state.env.Declare()
        state.env.Requires(declarer, install)  # Ensure declaration fires after installation available

        # shebang should be in the list if bin.src exists but the location
        # matters so we can not append it afterwards.
        state.env.Default(
            [t for t in defaultTargets if os.path.exists(t) or (t == "shebang" and os.path.exists("bin.src"))]
        )
        if "version" in state.targets:
            state.env.Default(state.targets["version"])
        state.env.Requires(state.targets["tests"], state.targets["version"])
        state.env.Decider("MD5-timestamp")  # if timestamps haven't changed, don't do MD5 checks
        #
        # Check if any of the tests failed by looking for *.failed files.
        # Perform this test just before scons exits
        #
        # N.b. the test is written in sh not python as then we can use @ to
        # suppress output
        #
        if "tests" in [str(t) for t in BUILD_TARGETS]:
            testsDir = shlex.quote(os.path.join(os.getcwd(), "tests", ".tests"))
            checkTestStatus_command = state.env.Command(
                "checkTestStatus",
                [],
                f"""
                @ if [ -d {testsDir} ]; then \
                      nfail=`find {testsDir} -name "*.failed" | wc -l | sed -e 's/ //g'`; \
                      if [ $$nfail -gt 0 ]; then \
                          echo "Failed test output:" >&2; \
                          for f in `find {testsDir} -name "*.failed"`; do \
                              case "$$f" in \
                              *.xml.failed) \
                                echo "Global pytest output is in $$f" >&2; \
                                ;; \
                              *.failed) \
                                cat $$f >&2; \
                                ;; \
                              esac; \
                          done; \
                          echo "The following tests failed:" >&2;\
                          find {testsDir} -name "*.failed" >&2; \
                          echo "$$nfail tests failed" >&2; exit 1; \
                      fi; \
                  fi; \
            """,
            )

            state.env.Depends(checkTestStatus_command, BUILD_TARGETS)  # this is why the check runs last
            BUILD_TARGETS.extend(checkTestStatus_command)
            state.env.AlwaysBuild(checkTestStatus_command)


class BasicSConscript:
    """A scope-only class for SConscript-replacement convenience functions.

    All methods of `~lsst.sconsUtils.scripts.BasicSConscript` are static.  All
    of these functions update the `~lsst.sconsUtils.state.targets` dictionary
    of targets used to set default targets and fix build dependencies; if you
    build anything without using BasicSConscript methods, be sure to manually
    add it to the `~lsst.sconsUtils.state.state.targets` `dict`.
    """

    @staticmethod
    def lib(libName=None, src=None, libs="self", noBuildList=None):
        """Convenience function to replace standard lib/SConscript boilerplate.

        With no arguments, this will build a shared library with the same name
        as the package.  This uses
        `lsst.sconsUtils.env.SourcesForSharedLibrary` to support the
        ``optFiles``/``noOptFiles`` command-line variables.

        Parameters
        ----------
        libName : `str`
            Name of the shared libray to be built (defaults to
            ``env["packageName"]``).
        src : `str` or `~SCons.Script.Glob`
            Source to compile into the library.  Defaults to a 4-directory
            deep glob of all ``*.cc`` files in ``#src``.
        libs : `str` or `list`
            Libraries to link against, either as a string argument to be
            passed to `lsst.sconsUtils.env.getLibs` or a sequence of actual
            libraries to pass in.
        noBuildList : `list`
            List of source files to exclude from building.

        Returns
        -------
        result : ???
            ???
        """
        if libName is None:
            libName = state.env["packageName"]
        if src is None:
            src = Glob("#src/*.cc") + Glob("#src/*/*.cc") + Glob("#src/*/*/*.cc") + Glob("#src/*/*/*/*.cc")
        if noBuildList is not None:
            src = [node for node in src if os.path.basename(str(node)) not in noBuildList]
        src = state.env.SourcesForSharedLibrary(src)
        if isinstance(libs, str):
            libs = state.env.getLibs(libs)
        elif libs is None:
            libs = []
        result = state.env.SharedLibrary(libName, src, LIBS=libs)
        state.targets["lib"].extend(result)
        return result

    @staticmethod
    def shebang(src=None):
        """Handles shebang rewriting.

        With no arguments looks in ``bin.src/`` and copies to ``bin/``
        If `~lsst.sconsUtils.utils.needShebangRewrite()` is `False` the
        shebang will not be modified.

        Only Python files requiring a shebang rewrite should be placed
        in ``bin.src/``.  Do not place executable binaries in this directory.

        Parameters
        ----------
        src : `str` or `~SCons.Script.Glob`, optional
            Glob to use to search for files.
        """
        # check if Python is called on the first line with this expression
        # This comes from distutils copy_scripts
        FIRST_LINE_RE = re.compile(r"^#!.*python[0-9.]*([ \t].*)?$")
        doRewrite = utils.needShebangRewrite()

        def rewrite_shebang(target, source, env):
            """Copy source to target, rewriting the shebang"""
            # Currently just use this python
            usepython = utils.whichPython()
            for targ, src in zip(target, source):
                with open(str(src)) as srcfd:
                    with open(str(targ), "w") as outfd:
                        first_line = srcfd.readline()
                        # Always match the first line so we can warn people
                        # if an attempt is being made to rewrite a file that
                        # should not be rewritten
                        match = FIRST_LINE_RE.match(first_line)
                        if match and doRewrite:
                            post_interp = match.group(1) or ""
                            # Paths can be long so ensure that flake8 won't
                            # complain
                            outfd.write(f"#!{usepython}{post_interp}  # noqa\n")
                        else:
                            if not match:
                                state.log.warn(
                                    f"Could not rewrite shebang of {src}. Please check"
                                    " file or move it to bin directory."
                                )
                            outfd.write(first_line)
                        for line in srcfd.readlines():
                            outfd.write(line)
                # Ensure the bin/ file is executable
                oldmode = os.stat(str(targ))[ST_MODE] & 0o7777
                newmode = (oldmode | 0o555) & 0o7777
                if newmode != oldmode:
                    state.log.info(f"changing mode of {str(targ)} from {oldmode} to {newmode}")
                    os.chmod(str(targ), newmode)

        if src is None:
            src = Glob("#bin.src/*")
        for s in src:
            filename = str(s)
            # Do not try to rewrite files starting with non-letters
            if filename != "SConscript" and re.match("[A-Za-z]", filename):
                result = state.env.Command(
                    target=os.path.join(Dir("#bin").abspath, filename), source=s, action=rewrite_shebang
                )
                state.targets["shebang"].extend(result)

    @staticmethod
    def python(module=None, src=None, extra=(), libs="main python"):
        """Convenience function to replace standard ``python/*/SConscript``
        boilerplate.

        With no arguments, this will build a pybind11 module with the name
        determined according to our current pseudo-convention: last part of
        ``env["packageName"]`` (split by underscores), with an underscore
        prepended.  All .cc files in the same directory will be linked into a
        single module.

        Parameters
        ----------
        module : `str`, optional
            Name of the module to build (does not include the file extension).
            Defaults to ``"_" + env["packageName"].split("_")[-1]``.
        src : `list`, optional
            A list of source files to build the module from; defaults to all
            .cc files in the directory.
        extra : `list`, optional
            A list of additional source files to add to ``src``; should only
            be used if ``src`` is defaulted.
        libs : `str` or `list`, optional
            Libraries to link against, either as a string argument to be
            passed to `lsst.sconsUtils.env.getLibs` or a sequence of actual
            libraries to pass in.

        Returns
        -------
        result : `lsst.sconsUtils.env.Pybind11LoadableModule`
            A Pybind11LoadableModule instance.
        """
        if module is None:
            module = "_" + state.env["packageName"].split("_")[-1]
        if src is None:
            src = state.env.Glob("*.cc")
        src.extend(extra)
        if isinstance(libs, str):
            libs = state.env.getLibs(libs)
        elif libs is None:
            libs = []
        result = state.env.Pybind11LoadableModule(module, src, LIBS=libs)
        state.targets["python"].append(result)
        return result

    @staticmethod
    def pybind11(nameList=[], libs="main python", extraSrc=None, addUnderscore=True):
        """Convenience function to replace standard ``python/*/SConscript``
        boilerplate.

        .. note:: Deprecated

            Use `lsst.sconsUtils.scripts.BasicSConscript.python` for new code
            with all source compiled into a single module.  Will be removed
            once all LSST code has been converted to use the new approach.

        Parameters
        ----------
        nameList : `list`, optional
            Sequence of pybind11 modules to be built (does not include the
            file extensions).
        libs : `str` or `list`, optional
            Libraries to link against, either as a string argument to be
            passed to `lsst.sconsUtils.env.getLibs` or a sequence of actual
            libraries to pass in.
        extraSrc : `dict`, optional
            A dictionary of additional source files that go into the modules.
            Each key should be an entry in nameList, and each value should be
            a list of additional C++ source files.
        addUnderscore : `bool`, optional
            Add an underscore to each library name (if the source file name
            does not already start with underscore)? If False the library name
            is always the same as the source file name
            **DEPRECATED**: always use `False` for new code.

        Returns
        -------
        result : `lsst.sconsUtils.env.Pybind11LoadableModule`
            A Pybind11LoadableModule instance.
        """
        warnings.warn(
            "sconsUtils.scripts.pybind11() is deprecated; please use scripts.python() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        srcList = extraSrc
        if srcList is None:
            srcList = {name: [] for name in nameList}
        for name in nameList:
            srcList[name].append(name + ".cc")
        if isinstance(libs, str):
            libs = state.env.getLibs(libs)
        elif libs is None:
            libs = []
        result = []
        for name in nameList:
            # TODO remove this block and the `addUnderscore` argument and
            # always use pyLibName = name;  but we can't do that until all our
            # pybind11 SConscript files have been converted
            if addUnderscore:
                if name.startswith("_"):
                    pyLibName = name
                else:
                    pyLibName = "_" + name
            else:
                pyLibName = name
            result.extend(state.env.Pybind11LoadableModule(pyLibName, srcList[name], LIBS=libs))
        state.targets["python"].extend(result)
        return result

    @staticmethod
    def doc(config="doxygen.conf.in", projectName=None, projectNumber=None, **kwargs):
        """Convenience function to replace standard doc/SConscript
        boilerplate.

        With no arguments, this will generate a Doxygen config file and run
        Doxygen with `lsst.sconsUtils.env.Doxygen`, using the projectName
        and projectNumber from ``env["packageName"]`` and ``env["version"]``,
        respectively.

        This essentially just forwards all arguments (which should be passed as
        keyword arguments) to `lsst.sconsUtils.env.Doxygen()``.

        Parameters
        ----------
        config : `str`, optional
            Configuration .in file to use.
        projectName : `str`, optional
            Project name.
        projectNumber : `str`, optional
            Project version number.
        kwargs

        Returns
        -------
        result : ???
            ???
        """
        if not shutil.which("doxygen"):
            state.log.warn("doxygen executable not found; skipping documentation build.")
            return []
        if projectName is None:
            projectName = ".".join(["lsst"] + state.env["packageName"].split("_"))
        if projectNumber is None:
            projectNumber = state.env["version"]
        result = state.env.Doxygen(
            config,
            projectName=projectName,
            projectNumber=projectNumber,
            includes=state.env.doxygen["includes"],
            useTags=state.env.doxygen["tags"],
            makeTag=(state.env["packageName"] + ".tag"),
            **kwargs,
        )
        state.targets["doc"].extend(result)
        return result

    @staticmethod
    def tests(
        pyList=None,
        ccList=None,
        swigNameList=None,
        swigSrc=None,
        ignoreList=None,
        noBuildList=None,
        pySingles=None,
        args=None,
    ):
        """Convenience function to replace standard tests/SConscript
        boilerplate.

        With no arguments, will attempt to figure out which files should be
        run as tests and which are support code (like SWIG modules).

        Python tests will be marked as dependent on the entire ``#python``
        directory and any SWIG modules built in the tests directory.  This
        should ensure tests are always run when their results might have
        changed, but may result in them being re-run more often
        than necessary.

        Parameters
        ----------
        pyList : `list`, optional
            A sequence of Python tests to run (including .py extensions).
            Defaults to a ``*.py`` glob of the tests directory, minus any
            files corresponding to the SWIG modules in swigFileList.
            An empty list will enable automated test discovery.
        ccList : `list`, optional
            A sequence of C++ unit tests to run (including .cc extensions).
            Defaults to a ``*.cc`` glob of the tests directory, minus any
            files that end with ``*_wrap.cc`` and files present in swigSrc.
        swigNameList : `list`, optional
            A sequence of SWIG modules to build (NOT including .i extensions).
        swigSrc : `dict`, optional
            Additional source files to be compiled into SWIG modules, as a
            dictionary; each key must be an entry in swigNameList, and each
            value a list of additional source files.
        ignoreList : `list`, optional
            List of ignored tests to be passed to
            `lsst.sconsUtils.tests.Control` (note that ignored tests will be
            built, but not run).
        noBuildList : `list`, optional
            List of tests that should not even be built.
        pySingles : `list`, optional
            A sequence of Python tests to run (including .py extensions)
            as independent single tests. By default this list is empty
            and all tests are run in a single pytest call.
            Items specified here will not appear in the default pyList
            and should not start with ``test_`` (such that they will not
            be auto-discoverable by pytest).
        args : `dict`, optional
            A dictionary of program arguments for tests, passed directly
            to `lsst.sconsUtils.tests.Control`.

        Returns
        -------
        result : ???
            ???
        """
        if GetOption("no_tests"):
            return []
        if noBuildList is None:
            noBuildList = []
        if pySingles is None:
            pySingles = []
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
            pyList = [
                node
                for node in Glob("*.py")
                if _getFileBase(node) not in swigNameList and os.path.basename(str(node)) not in noBuildList
            ]
            # if we got no matches, reset to None so we do not enabled
            # auto test detection in pytest
            if not pyList:
                pyList = None
        if ccList is None:
            ccList = [
                node
                for node in Glob("*.cc")
                if (not str(node).endswith("_wrap.cc"))
                and str(node) not in allSwigSrc
                and os.path.basename(str(node)) not in noBuildList
            ]
        if ignoreList is None:
            ignoreList = []

        def s(ll):
            if ll is None:
                return ["None"]
            return [str(i) for i in ll]

        state.log.info(f"SWIG modules for tests: {s(swigFileList)}")
        state.log.info(f"Python tests: {s(pyList)}")
        state.log.info(f"C++ tests: {s(ccList)}")
        state.log.info(f"Files that will not be built: {noBuildList}")
        state.log.info(f"Ignored tests: {ignoreList}")
        control = tests.Control(state.env, ignoreList=ignoreList, args=args, verbose=True)
        for ccTest in ccList:
            state.env.Program(ccTest, LIBS=state.env.getLibs("main test"))
        swigMods = []
        for name, src in swigSrc.items():
            swigMods.extend(
                state.env.SwigLoadableModule("_" + name, src, LIBS=state.env.getLibs("main python"))
            )

        # Warn about insisting that a test in pySingles starts with test_ and
        # therefore might be automatically discovered by pytest. These files
        # should not be discovered automatically.
        for node in pySingles:
            if str(node).startswith("test_"):
                state.log.warn(
                    f"Warning: {node} should be run independently but can be automatically discovered"
                )

        # Ensure that python tests listed in pySingles are not included in
        # pyList.
        if pyList is not None:
            pyList = [str(node) for node in pyList if str(node) not in pySingles]

        ccList = [control.run(str(node)) for node in ccList]
        pySingles = [control.run(str(node)) for node in pySingles]

        # If we tried to discover .py files and found none, do not then
        # try to use auto test discovery.
        if pyList is not None:
            pyList = [control.runPythonTests(pyList)]
        else:
            pyList = []
        pyList.extend(control.runPythonLinter())

        # Run all pySingles sequentially before other tests.  This ensures
        # that there are no race conditions collecting coverage databases.
        if pySingles:
            for i in range(len(pySingles) - 1):
                state.env.Depends(pySingles[i + 1], pySingles[i])
            for pyTest in pyList:
                state.env.Depends(pyTest, pySingles[-1])

        pyList.extend(pySingles)
        for pyTest in pyList:
            state.env.Depends(pyTest, ccList)
            state.env.Depends(pyTest, swigMods)
            state.env.Depends(pyTest, state.targets["python"])
            state.env.Depends(pyTest, state.targets["shebang"])
        result = ccList + pyList
        state.targets["tests"].extend(result)
        return result

    @staticmethod
    def examples(ccList=None, swigNameList=None, swigSrc=None):
        """Convenience function to replace standard examples/SConscript
        boilerplate.

        Parameters
        ----------
        ccList : `list`, optional
            A sequence of C++ examples to build (including .cc extensions).
            Defaults to a ``*.cc`` glob of the examples directory, minus any
            files that end with ``*_wrap.cc`` and files present in swigSrc.
        swigNameList : `list`, optional
            A sequence of SWIG modules to build (NOT including .i extensions).
        swigSrc : `list`, optional
            Additional source files to be compiled into SWIG modules, as a
            dictionary; each key must be an entry in swigNameList, and each
            value a list of additional source files.

        Returns
        -------
        result : ???
            ???
        """
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
            ccList = [
                node
                for node in Glob("*.cc")
                if (not str(node).endswith("_wrap.cc")) and str(node) not in allSwigSrc
            ]
        state.log.info(f"SWIG modules for examples: {swigFileList}")
        state.log.info(f"C++ examples: {ccList}")
        results = []
        for src in ccList:
            results.extend(state.env.Program(src, LIBS=state.env.getLibs("main")))
        for name, src in swigSrc.items():
            results.extend(
                state.env.SwigLoadableModule("_" + name, src, LIBS=state.env.getLibs("main python"))
            )
        for result in results:
            state.env.Depends(result, state.targets["lib"])
        state.targets["examples"].extend(results)
        return results
