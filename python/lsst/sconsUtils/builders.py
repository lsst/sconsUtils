"""Extra builders and methods to be injected into the SConsEnvironment class.
"""

__all__ = ("filesToTag", "DoxygenBuilder")

import csv
import fnmatch
import os
import re
import shlex
from stat import ST_MODE

import SCons.Script
from SCons.Script.SConscript import SConsEnvironment

from . import state
from .installation import determineVersion, getFingerprint
from .utils import memberOf, needShebangRewrite, whichPython


@memberOf(SConsEnvironment)
def SharedLibraryIncomplete(self, target, source, **keywords):
    """Like SharedLibrary, but don't insist that all symbols are resolved."""
    myenv = self.Clone()
    if myenv["PLATFORM"] == "darwin":
        myenv["SHLINKFLAGS"] += ["-undefined", "dynamic_lookup", "-headerpad_max_install_names"]
    return myenv.SharedLibrary(target, source, **keywords)


@memberOf(SConsEnvironment)
def Pybind11LoadableModule(self, target, source, **keywords):
    """Like LoadableModule, but don't insist that all symbols are resolved, and
    set some pybind11-specific flags.
    """
    myenv = self.Clone()
    myenv.Append(CCFLAGS=["-fvisibility=hidden"])
    if myenv["PLATFORM"] == "darwin":
        myenv.Append(LDMODULEFLAGS=["-undefined", "dynamic_lookup", "-headerpad_max_install_names"])
    return myenv.LoadableModule(target, source, **keywords)


@memberOf(SConsEnvironment)
def SourcesForSharedLibrary(self, files):
    """Prepare the list of files to be passed to a SharedLibrary constructor.

    Parameters
    ----------
    files :
        List of files to be processed.

    Returns
    -------
    objs : `list`
        Object files.

    Notes
    -----
    In particular, ensure that any files listed in ``env.NoOptFiles`` (set by
    the command line option ``noOptFile="file1 file2"``) are built without
    optimisation and files listed in ``env.optFiles`` are built with
    optimisation.

    The usage pattern in an SConscript file is:

    .. code-block:: python

        ccFiles = env.SourcesForSharedLibrary(Glob("../src/*/*.cc"))
        env.SharedLibrary('afw', ccFiles, LIBS=env.getLibs("self")))

    This is automatically used by
    `lsst.sconsUtils.scripts.BasicSConscript.lib()`.
    """

    files = [SCons.Script.File(file) for file in files]

    if not (self.get("optFiles") or self.get("noOptFiles")):
        objs = [self.SharedObject(ccFile) for ccFile in sorted(state.env.Flatten(files), key=str)]
        return objs

    if self.get("optFiles"):
        optFiles = self["optFiles"].replace(".", r"\.")  # it'll be used in an RE
        optFiles = SCons.Script.Split(optFiles.replace(",", " "))
        optFilesRe = "/(%s)$" % "|".join(optFiles)
    else:
        optFilesRe = None

    if self.get("noOptFiles"):
        noOptFiles = self["noOptFiles"].replace(".", r"\.")  # it'll be used in an RE
        noOptFiles = SCons.Script.Split(noOptFiles.replace(",", " "))
        noOptFilesRe = "/(%s)$" % "|".join(noOptFiles)
    else:
        noOptFilesRe = None

    if self.get("opt"):
        opt = int(self["opt"])
    else:
        opt = 0

    if opt == 0:
        opt = 3

    CCFLAGS_OPT = re.sub(r"-O(\d|s)\s*", f"-O{opt} ", " ".join(self["CCFLAGS"]))
    CCFLAGS_NOOPT = re.sub(r"-O(\d|s)\s*", "-O0 ", " ".join(self["CCFLAGS"]))  # remove -O flags from CCFLAGS

    objs = []
    for ccFile in files:
        if optFilesRe and re.search(optFilesRe, ccFile.abspath):
            obj = self.SharedObject(ccFile, CCFLAGS=CCFLAGS_OPT)
        elif noOptFilesRe and re.search(noOptFilesRe, ccFile.abspath):
            obj = self.SharedObject(ccFile, CCFLAGS=CCFLAGS_NOOPT)
        else:
            obj = self.SharedObject(ccFile)
        objs.append(obj)

    objs = sorted(state.env.Flatten(objs), key=str)
    return objs


def filesToTag(root=None, fileRegex=None, ignoreDirs=None):
    """Return a list of files that need to be scanned for tags, starting at
    directory root.

    Parameters
    ----------
    root : `str`, optional
        Directory root to search.
    fileRegex : `str`, optional
        Matching regular expression for files.
    ignoreDirs : `list`
        List of directories to ignore when searching.

    Returns
    -------
    files : `list`
        List of matching files.

    Notes
    -----
    These tags are for advanced Emacs users, and should not be confused with
    SVN tags or Doxygen tags.

    Files are chosen if they match fileRegex; toplevel directories in list
    ignoreDirs are ignored.
    This routine won't do anything unless you specified a "TAGS" target.
    """

    if root is None:
        root = "."
    if fileRegex is None:
        fileRegex = r"^[a-zA-Z0-9_].*\.(cc|h(pp)?|py)$"
    if ignoreDirs is None:
        ignoreDirs = ["examples", "tests"]

    if "TAGS" not in SCons.Script.COMMAND_LINE_TARGETS:
        return []

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath == ".":
            dirnames[:] = [d for d in dirnames if not re.search(r"^(%s)$" % "|".join(ignoreDirs), d)]

        dirnames[:] = [d for d in dirnames if not re.search(r"^(\.svn)$", d)]  # ignore .svn tree
        #
        # List of possible files to tag, but there's some cleanup required
        # for machine-generated files
        #
        candidates = [f for f in filenames if re.search(fileRegex, f)]
        #
        # Remove files generated by swig
        #
        for swigFile in [f for f in filenames if f.endswith(".i")]:
            name = os.path.splitext(swigFile)[0]
            candidates = [f for f in candidates if not re.search(rf"{name}(_wrap\.cc?|\.py)$", f)]

        files += [os.path.join(dirpath, f) for f in candidates]

    return files


@memberOf(SConsEnvironment)
def BuildETags(env, root=None, fileRegex=None, ignoreDirs=None):
    """Build Emacs tags (see man etags for more information).

    Parameters
    ----------
    env : `SCons.Environment`
        Environment to use to run ``etags`` command.
    root : `str`, optional
        Directory to begin search.
    fileRegex : `str`
        Regular expression to match files.
    ignoreDirs : `list`
        List of directories to ignore.

    Notes
    -----
    Files are chosen if they match fileRegex; toplevel directories in list
    ignoreDirs are ignored.  This routine won't do anything unless you
    specified a "TAGS" target."""

    toTag = filesToTag(root, fileRegex, ignoreDirs)
    if toTag:
        return env.Command("TAGS", toTag, "etags -o $TARGET $SOURCES")


@memberOf(SConsEnvironment)
def CleanTree(self, filePatterns, dirPatterns="", directory=".", verbose=False):
    """Remove files matching the argument list starting at directory
    when scons is invoked with -c/--clean and no explicit targets are listed.

    Parameters
    ----------
    filePatterns : `str`
        Glob to match for files to be deleted.
    dirPatterns : `str`, optional
        Specification of directories to be removed.
    directory : `str`, optional
        Directory to clean.
    verbose : `bool`, optional
        If `True` print each filename after deleting it.

    Notes
    -----
    Can be run as:

    .. code-block:: python

        env.CleanTree(r"*~ core")
    """

    def genFindCommand(patterns, directory, verbose, filesOnly):
        # Generate find command to clean up (find-glob) patterns, either files
        # or directories.
        expr = ""
        for pattern in SCons.Script.Split(patterns):
            if expr != "":
                expr += " -o "
            # Quote unquoted * and [
            expr += "-name %s" % re.sub(r"(^|[^\\])([\[*])", r"\1\\\2", pattern)
            if filesOnly:
                expr += " -type f"
            else:
                expr += " -type d -prune"

        command = "find " + directory
        # Don't look into .svn or .git directories to save time.
        command += r" \( -name .svn -prune -o -name .git -prune -o -name \* \) "
        command += r" \( " + expr + r" \)"
        if filesOnly:
            command += r" -exec rm -f {} \;"
        else:
            command += r" -exec rm -rf {} \;"
        if verbose:
            command += " -print"
        return command

    action = genFindCommand(filePatterns, directory, verbose, filesOnly=True)

    # Clean up scons files --- users want to be able to say scons -c and get a
    # clean copy.
    # We can't delete .sconsign.dblite if we use "scons clean" instead of
    # "scons --clean", so the former is no longer supported.
    action += " ; rm -rf .sconf_temp .sconsign.dblite .sconsign.tmp config.log"

    if dirPatterns != "":
        action += " ; "
        action += genFindCommand(dirPatterns, directory, verbose, filesOnly=False)
    # Do we actually want to clean up?  We don't if the command is e.g.
    # "scons -c install"
    if "clean" in SCons.Script.COMMAND_LINE_TARGETS:
        state.log.fail("'scons clean' is no longer supported; please use 'scons --clean'.")
    elif not SCons.Script.COMMAND_LINE_TARGETS and self.GetOption("clean"):
        self.Execute(self.Action([action]))


@memberOf(SConsEnvironment)
def ProductDir(env, product):
    """Return the product directory.

    Parameters
    ----------
    product : `str`
        The EUPS product name.

    Returns
    -------
    dir : `str`
        The product directory. `None` if the product is not known.
    """
    from . import eupsForScons

    global _productDirs
    try:
        _productDirs
    except Exception:
        try:
            _productDirs = eupsForScons.productDir(eupsenv=eupsForScons.getEups())
        except TypeError:  # old version of eups (pre r18588)
            _productDirs = None
    if _productDirs:
        pdir = _productDirs.get(product)
    else:
        pdir = eupsForScons.productDir(product)
    if pdir == "none":
        pdir = None
    return pdir


class DoxygenBuilder:
    """A callable to be used as an SCons Action to run Doxygen.

    This should only be used by the env.Doxygen pseudo-builder method.
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.results = []
        self.sources = []
        self.targets = []
        self.useTags = [SCons.Script.File(item).abspath for item in self.useTags]
        self.inputs = [SCons.Script.Entry(item).abspath for item in self.inputs]
        self.excludes = [SCons.Script.Entry(item).abspath for item in self.excludes]
        self.outputPaths = [SCons.Script.Dir(item) for item in self.outputs]

    def __call__(self, env, config):
        self.findSources()
        self.findTargets()
        inConfigNode = SCons.Script.File(config)
        outConfigName, ext = os.path.splitext(inConfigNode.abspath)
        outConfigNode = SCons.Script.File(outConfigName)
        if self.makeTag:
            tagNode = SCons.Script.File(self.makeTag)
            self.makeTag = tagNode.abspath
            self.targets.append(tagNode)
        config = env.Command(
            target=outConfigNode,
            source=inConfigNode if os.path.exists(config) else None,
            action=self.buildConfig,
        )
        env.AlwaysBuild(config)
        doc = env.Command(
            target=self.targets, source=self.sources, action=f"doxygen {shlex.quote(outConfigNode.abspath)}"
        )
        for path in self.outputPaths:
            env.Clean(doc, path)
        env.Depends(doc, config)
        self.results.extend(config)
        self.results.extend(doc)
        return self.results

    def findSources(self):
        for path in self.inputs:
            if os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    if os.path.abspath(root) in self.excludes:
                        dirs[:] = []
                        continue
                    if not self.recursive:
                        dirs[:] = []
                    else:
                        toKeep = []
                        for relDir in dirs:
                            if relDir.startswith("."):
                                continue
                            absDir = os.path.abspath(os.path.join(root, relDir))
                            if absDir not in self.excludes:
                                toKeep.append(relDir)
                        dirs[:] = toKeep
                    if self.excludeSwig:
                        for relFile in files:
                            base, ext = os.path.splitext(relFile)
                            if ext == ".i":
                                self.excludes.append(os.path.join(root, base + ".py"))
                                self.excludes.append(os.path.join(root, base + "_wrap.cc"))
                    for relFile in files:
                        absFile = os.path.abspath(os.path.join(root, relFile))
                        if absFile in self.excludes:
                            continue
                        for pattern in self.patterns:
                            if fnmatch.fnmatch(relFile, pattern):
                                self.sources.append(SCons.Script.File(absFile))
                                break
            elif os.path.isfile(path):
                self.sources.append(SCons.Script.File(path))

    def findTargets(self):
        for item in self.outputs:
            self.targets.append(SCons.Script.Dir(item))

    def buildConfig(self, target, source, env):
        outConfigFile = open(target[0].abspath, "w")

        # Need a routine to quote paths that contain spaces
        # but can not use shlex.quote because it has to be
        # a double quote for doxygen.conf
        # Do not quote a string if it is already quoted
        # Also have a version that quotes each item in a sequence and generates
        # the final quoted entry.
        def _quote_path(path):
            if " " in path and not path.startswith('"') and not path.endswith('"'):
                return f'"{path}"'
            return path

        def _quote_paths(pathList):
            return " ".join(_quote_path(p) for p in pathList)

        docPaths = []
        incFiles = []
        for incPath in self.includes:
            docDir, incFile = os.path.split(incPath)
            docPaths.append(f'"{docDir}"')
            incFiles.append(f'"{incFile}"')
            self.sources.append(SCons.Script.File(incPath))
        if docPaths:
            outConfigFile.write(f"@INCLUDE_PATH = {_quote_paths(docPaths)}\n")
        for incFile in incFiles:
            outConfigFile.write(f"@INCLUDE = {_quote_path(incFile)}\n")

        for tagPath in self.useTags:
            docDir, tagFile = os.path.split(tagPath)
            htmlDir = os.path.join(docDir, "html")
            outConfigFile.write(f'TAGFILES += "{tagPath}={htmlDir}"\n')
            self.sources.append(SCons.Script.Dir(docDir))
        if self.projectName is not None:
            outConfigFile.write(f"PROJECT_NAME = {self.projectName}\n")
        if self.projectNumber is not None:
            outConfigFile.write(f"PROJECT_NUMBER = {self.projectNumber}\n")
        outConfigFile.write(f"INPUT = {_quote_paths(self.inputs)}\n")
        outConfigFile.write(f"EXCLUDE = {_quote_paths(self.excludes)}\n")
        outConfigFile.write(f"FILE_PATTERNS = {' '.join(self.patterns)}\n")
        outConfigFile.write("RECURSIVE = YES\n" if self.recursive else "RECURSIVE = NO\n")
        allOutputs = {"html", "latex", "man", "rtf", "xml"}
        for output, path in zip(self.outputs, self.outputPaths):
            try:
                allOutputs.remove(output.lower())
            except Exception:
                state.log.fail(f"Unknown Doxygen output format '{output}'.")
                state.log.finish()
            outConfigFile.write(f"GENERATE_{output.upper()} = YES\n")
            outConfigFile.write(f"{output.upper()}_OUTPUT = {_quote_path(path.abspath)}\n")
        for output in allOutputs:
            outConfigFile.write(f"GENERATE_{output.upper()} = NO\n")
        if self.makeTag is not None:
            outConfigFile.write(f"GENERATE_TAGFILE = {_quote_path(self.makeTag)}\n")
        #
        # Append the local overrides (usually doxygen.conf.in)
        #
        if len(source) > 0:
            with open(source[0].abspath) as inConfigFile:
                outConfigFile.write(inConfigFile.read())

        outConfigFile.close()


@memberOf(SConsEnvironment)
def Doxygen(self, config, **kwargs):
    """Generate a Doxygen config file and run Doxygen on it.

    Rather than parse a complete Doxygen config file for SCons sources
    and targets, this Doxygen builder builds a Doxygen config file,
    adding INPUT, FILE_PATTERNS, RECURSIVE, EXCLUDE, XX_OUTPUT and
    GENERATE_XX options (and possibly others) to an existing
    proto-config file.  Generated settings will override those in
    the proto-config file.

    Parameters
    ----------
    config : `str`
        A Doxygen config file, usually with the extension .conf.in; a new file
        with the ``.in`` removed will be generated and passed to Doxygen.
        Settings in the original config file will be overridden by those
        generated by this method.
    **kwargs
        Keyword arguments.

        - ``inputs`` :     A sequence of folders or files to be passed
                           as the INPUT setting for Doxygen.  This list
                           will be turned into absolute paths by SCons,
                           so the ``#folder`` syntax will work.
                           Otherwise, the list is passed in as-is, but
                           the builder will also examine those
                           directories to find which source files the
                           Doxygen output actually depends on.
        - ``patterns`` :   A sequence of glob patterns for the
                           FILE_PATTERNS Doxygen setting.  This will be
                           passed directly to Doxygen, but it is also
                           used to determine which source files should
                           be considered dependencies.
        - ``recursive`` :  Whether the inputs should be searched
                           recursively (used for the Doxygen RECURSIVE
                           setting).
        - ``outputs`` :    A sequence of output formats which will also
                           be used as output directories.
        - ``exclude`` :    A sequence of folders or files (not globs)
                           to be ignored by Doxygen (the Doxygen
                           EXCLUDE setting).  Hidden directories are
                           automatically ignored.
        - ``includes`` :   A sequence of Doxygen config files to
                           include.  These will automatically be
                           separated into paths and files to fill in
                           the ``@INCLUDE_PATH`` and ``@INCLUDE`` settings.
        - ``useTags`` :    A sequence of Doxygen tag files to use.  It
                           will be assumed that the html directory for
                           each tag file is in an "html" subdirectory
                           in the same directory as the tag file.
        - ``makeTag``      A string indicating the name of a tag file
                           to be generated.
        - ``projectName`` : Sets the Doxygen PROJECT_NAME setting.
        - ``projectNumber`` : Sets the Doxygen PROJECT_NUMBER setting.
        - ``excludeSwig`` : If True (default), looks for SWIG .i files
                            in the input directories and adds Python
                            and C++ files generated by SWIG to the
                            list of files to exclude.  For this to work,
                            the SWIG-generated filenames must be the
                            default ones ("module.i" generates "module.py"
                            and "moduleLib_wrap.cc").

    Notes
    -----
    When building documentation from a clean source tree, generated source
    files (like headers generated with M4) will not be included among the
    dependencies, because they aren't present when we walk the input folders.
    The workaround is just to build the docs after building the source.
    """

    inputs = [
        d for d in ["#doc", "#include", "#python", "#src"] if os.path.exists(SCons.Script.Entry(d).abspath)
    ]
    defaults = {
        "inputs": inputs,
        "recursive": True,
        "patterns": ["*.h", "*.cc", "*.py", "*.dox"],
        "outputs": ["html", "xml"],
        "excludes": [],
        "includes": [],
        "useTags": [],
        "makeTag": None,
        "projectName": None,
        "projectNumber": None,
        "excludeSwig": True,
    }
    for k in defaults:
        if kwargs.get(k) is None:
            kwargs[k] = defaults[k]
    builder = DoxygenBuilder(**kwargs)
    return builder(self, config)


def _get_version_string(versionString):
    if versionString is None:
        for n in ("git", "hg", "svn"):
            if os.path.isdir(f".{n}"):
                versionString = n

        if not versionString:
            versionString = "git"
    return versionString


def _calcMd5(filename):
    try:
        import hashlib

        md5 = hashlib.md5(open(filename, "rb").read()).hexdigest()
    except OSError:
        md5 = None

    return md5


@memberOf(SConsEnvironment)
def VersionModule(self, filename, versionString=None):
    versionString = _get_version_string(versionString)
    oldMd5 = _calcMd5(filename)

    def makeVersionModule(target, source, env):
        try:
            version = determineVersion(state.env, versionString)
        except RuntimeError:
            version = "unknown"
        parts = version.split("+")

        names = []
        with open(target[0].abspath, "w") as outFile:
            outFile.write("# -------- This file is automatically generated by LSST's sconsUtils -------- #\n")

            version_info = None
            try:
                info = tuple(int(v) for v in parts[0].split("."))
                what = "__version_info__"
                names.append(what)
                version_info = f"{what}: tuple[int, ...] = {info!r}\n"
            except ValueError:
                pass

            what = "__version__"
            outFile.write(f'{what}: str = "{version}"\n')
            names.append(what)

            what = "__repo_version__"
            outFile.write(f'{what}: str = "{parts[0]}"\n')
            names.append(what)

            what = "__fingerprint__"
            outFile.write(f'{what}: str = "{getFingerprint(versionString)}"\n')
            names.append(what)

            if version_info is not None:
                outFile.write(version_info)

            if len(parts) > 1:
                try:
                    what = "__rebuild_version__"
                    outFile.write(f"{what}: int = {int(parts[1])}\n")
                    names.append(what)
                except ValueError:
                    pass

            what = "__dependency_versions__"
            names.append(what)
            outFile.write(f"{what}: dict[str, str | None] = {{")
            if env.dependencies.packages:
                outFile.write("\n")
                for name, mod in env.dependencies.packages.items():
                    if mod is None:
                        outFile.write(f'    "{name}": None,\n')
                    elif hasattr(mod.config, "version"):
                        outFile.write(f'    "{name}": "{mod.config.version}",\n')
                    else:
                        outFile.write(f'    "{name}": "unknown",\n')
            outFile.write("}\n")

            # Write out an entry per line as there can be many names
            outFile.write("__all__ = (\n")
            for n in names:
                outFile.write(f'    "{n}",\n')
            outFile.write(")\n")

        if _calcMd5(target[0].abspath) != oldMd5:  # only print if something's changed
            state.log.info(f'makeVersionModule(["{target[0]}"], [])')

    result = self.Command(filename, [], self.Action(makeVersionModule, strfunction=lambda *args: None))

    self.AlwaysBuild(result)
    return result


@memberOf(SConsEnvironment)
def PackageInfo(self, pythonDir, versionString=None):
    versionString = _get_version_string(versionString)

    if not os.path.exists(pythonDir):
        return []

    # Some information can come from the pyproject file.
    toml_metadata = {}
    if os.path.exists("pyproject.toml"):
        import tomllib

        with open("pyproject.toml", "rb") as fd:
            toml_metadata = tomllib.load(fd)

    toml_project = toml_metadata.get("project", {})
    pythonPackageName = ""
    if "name" in toml_project:
        pythonPackageName = toml_project["name"]
    else:
        if os.path.exists(os.path.join(pythonDir, "lsst")):
            pythonPackageName = "lsst_" + state.env["packageName"]
        else:
            pythonPackageName = state.env["packageName"]
        pythonPackageName = pythonPackageName.replace("_", "-")
    # The directory name is required to use "_" instead of "-"
    distDir = os.path.join(pythonDir, f"{pythonPackageName.replace('-', '_')}.dist-info")
    filename = os.path.join(distDir, "METADATA")
    oldMd5 = _calcMd5(filename)

    def makePackageMetadata(target, source, env):
        # Create the metadata file.
        try:
            version = determineVersion(state.env, versionString)
        except RuntimeError:
            version = "unknown"

        os.makedirs(os.path.dirname(target[0].abspath), exist_ok=True)
        with open(target[0].abspath, "w") as outFile:
            print("Metadata-Version: 1.0", file=outFile)
            print(f"Name: {pythonPackageName}", file=outFile)
            print(f"Version: {version}", file=outFile)

        if _calcMd5(target[0].abspath) != oldMd5:  # only print if something's changed
            state.log.info(f'PackageInfo(["{target[0]}"], [])')

    results = []
    results.append(
        self.Command(filename, [], self.Action(makePackageMetadata, strfunction=lambda *args: None))
    )

    def makeInstallerFile(target, source, env):
        # Write the INSTALLER file. This is purely something to potentially
        # tell the end user the tooling that was used to install the files.
        with open(target[0].abspath, "w") as outFile:
            print("sconsUtils", file=outFile)

    filename = os.path.join(distDir, "INSTALLER")
    results.append(self.Command(filename, [], self.Action(makeInstallerFile, strfunction=lambda *args: None)))

    # Create the entry points file if defined in the pyproject.toml file.
    entryPoints = toml_project.get("entry-points", {})
    if entryPoints:
        filename = os.path.join(distDir, "entry_points.txt")
        oldMd5 = _calcMd5(filename)

    def makeEntryPoints(target, source, env):
        # Make the entry points file as necessary.
        if not entryPoints:
            return
        os.makedirs(os.path.dirname(target[0].abspath), exist_ok=True)

        # Structure of entry points dict is something like:
        # "entry-points": {
        #   "butler.cli": {
        #     "pipe_base": "lsst.pipe.base.cli:get_cli_subcommands"
        #   }
        # }
        # Which becomes a file with:
        # [butler.cli]
        # pipe_base = lsst.pipe.base.cli:get_cli_subcommands
        with open(target[0].abspath, "w") as fd:
            for entryGroup in entryPoints:
                print(f"[{entryGroup}]", file=fd)
                for entryPoint, entryValue in entryPoints[entryGroup].items():
                    print(f"{entryPoint} = {entryValue}", file=fd)

        if _calcMd5(target[0].abspath) != oldMd5:  # only print if something's changed
            state.log.info(f'PackageInfo(["{target[0]}"], [])')

    if entryPoints:
        results.append(
            self.Command(filename, [], self.Action(makeEntryPoints, strfunction=lambda *args: None))
        )

    def makeRecordFile(target, source, env):
        # Write the RECORD file containing every python file in the package.
        # Do not attempt to write hashes and file sizes since these can
        # change if the package is not really installed into an EUPS tree.
        all_files = set()
        for root, dirs, files in os.walk(pythonDir):
            root = root.removeprefix(pythonDir)
            root = root.removeprefix("/")
            all_files.update({os.path.join(root, f) for f in files})
        # Ensure that RECORD itself is included in the list.
        record_path = target[0].abspath
        record_path = record_path.removeprefix(os.path.abspath(pythonDir)).removeprefix("/")
        all_files.add(record_path)

        # Also force the other metadata files we are writing into the
        # file in case the order cannot be guaranteed.
        meta_files = ["INSTALLER", "METADATA"]
        if entryPoints:
            meta_files.append("entry_points.txt")
        dist_path, _ = os.path.split(record_path)
        for f in meta_files:
            all_files.add(os.path.join(dist_path, f))

        # The RECORD file is nominally a CSV file.
        # Do not record file sizes or hashes.
        rows = [(f, "", "") for f in sorted(all_files)]
        with open(target[0].abspath, "w") as outFile:
            csv_writer = csv.writer(outFile)
            csv_writer.writerows(rows)

    filename = os.path.join(distDir, "RECORD")
    # This action really needs to run after the previous pkginfo actions
    # so that INSTALLER, entry_points.txt and METADATA files are created.
    # Additionally, the RECORD target needs to run after "python" so that
    # shared libraries are created -- this is configured elsewhere.
    results.append(self.Command(filename, [], self.Action(makeRecordFile, strfunction=lambda *args: None)))

    self.AlwaysBuild(results)
    return results


@memberOf(SConsEnvironment)
def PythonScripts(self):
    # Scripts are defined in the pyproject.toml file.
    toml_metadata = {}
    if os.path.exists("pyproject.toml"):
        import tomllib

        with open("pyproject.toml", "rb") as fd:
            toml_metadata = tomllib.load(fd)

    if not toml_metadata:
        return []

    scripts = {}
    if "project" in toml_metadata and "scripts" in toml_metadata["project"]:
        scripts = toml_metadata["project"]["scripts"]

    def makePythonScript(target, source, env):
        cmdfile = target[0].abspath
        command = os.path.basename(cmdfile)
        if command not in scripts:
            return
        os.makedirs(os.path.dirname(cmdfile), exist_ok=True)
        package, func = scripts[command].split(":", maxsplit=1)
        python_exe = whichPython()
        if needShebangRewrite():
            shebang = python_exe
        else:
            # Linux has very small shebang limit so always use env.
            shebang = f"/usr/bin/env {os.path.basename(python_exe)}"
        with open(cmdfile, "w") as fd:
            # Follow setuptools convention and always change the shebang.
            # Can not add noqa on Linux for long paths so do not add anywhere.
            print(
                rf"""#!{shebang}
import sys
from {package} import {func}
if __name__ == '__main__':
    sys.exit({func}())
""",
                file=fd,
            )

        # Ensure the bin/ file is executable
        oldmode = os.stat(cmdfile)[ST_MODE] & 0o7777
        newmode = (oldmode | 0o555) & 0o7777
        if newmode != oldmode:
            state.log.info(f"Changing mode of {cmdfile} from {oldmode} to {newmode}")
            os.chmod(cmdfile, newmode)

    results = []
    for cmd, code in scripts.items():
        filename = f"bin/{cmd}"

        # Do not do anything if there is an equivalent target in bin.src
        # that shebang would trigger.
        if os.path.exists(f"bin.src/{cmd}"):
            continue

        results.append(
            self.Command(filename, [], self.Action(makePythonScript, strfunction=lambda *args: None))
        )

    return results
