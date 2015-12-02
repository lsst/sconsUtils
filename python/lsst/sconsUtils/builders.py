#
#  @file builders.py
#
#  Extra builders and methods to be injected into the SConsEnvironment class.
##

from __future__ import absolute_import, division, print_function
import os
import re
import fnmatch

import SCons.Script
from SCons.Script.SConscript import SConsEnvironment

from .utils import memberOf
from .installation import determineVersion, getFingerprint
from . import state


## @brief Like SharedLibrary, but don't insist that all symbols are resolved
@memberOf(SConsEnvironment)
def SharedLibraryIncomplete(self, target, source, **keywords):
    myenv = self.Clone()
    if myenv['PLATFORM'] == 'darwin':
        myenv['SHLINKFLAGS'] += ["-undefined", "suppress", "-flat_namespace", "-headerpad_max_install_names"]
    return myenv.SharedLibrary(target, source, **keywords)


##  @brief Like LoadableModule, but don't insist that all symbols are resolved, and set
##         some SWIG-specific flags.
@memberOf(SConsEnvironment)
def SwigLoadableModule(self, target, source, **keywords):
    myenv = self.Clone()
    if myenv['PLATFORM'] == 'darwin':
        myenv.Append(LDMODULEFLAGS=["-undefined", "suppress",
                                    "-flat_namespace", "-headerpad_max_install_names"])
    #
    # Swig-generated .cc files cast pointers to long longs and back,
    # which is illegal.  This flag tells g++ about the sin
    #
    try:
        if myenv.whichCc == "gcc":
            myenv.Append(CCFLAGS=["-fno-strict-aliasing"])
    except AttributeError:
        pass
    return myenv.LoadableModule(target, source, **keywords)

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-


##
#  @brief Prepare the list of files to be passed to a SharedLibrary constructor
#
#  In particular, ensure that any files listed in env.NoOptFiles (set by the command line option
#  noOptFile="file1 file2") are built without optimisation and files listed in env.optFiles are
#  built with optimisation
#
#  The usage pattern in an SConscript file is:
#  ccFiles = env.SourcesForSharedLibrary(Glob("../src/*/*.cc"))
#  env.SharedLibrary('afw', ccFiles, LIBS=env.getLibs("self")))
#
#  This is automatically used by scripts.BasicSConscript.lib().
##
@memberOf(SConsEnvironment)
def SourcesForSharedLibrary(self, files):

    files = [SCons.Script.File(file) for file in files]

    if not (self.get("optFiles") or self.get("noOptFiles")):
        files.sort()
        return files

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

    CCFLAGS_OPT = re.sub(r"-O(\d|s)\s*", "-O%d " % opt, " ".join(self["CCFLAGS"]))
    CCFLAGS_NOOPT = re.sub(r"-O(\d|s)\s*", "-O0 ", " ".join(self["CCFLAGS"]))  # remove -O flags from CCFLAGS

    sources = []
    for ccFile in files:
        if optFilesRe and re.search(optFilesRe, ccFile.abspath):
            self.SharedObject(ccFile, CCFLAGS=CCFLAGS_OPT)
            ccFile = os.path.splitext(ccFile.abspath)[0] + self["SHOBJSUFFIX"]
        elif noOptFilesRe and re.search(noOptFilesRe, ccFile.abspath):
            self.SharedObject(ccFile, CCFLAGS=CCFLAGS_NOOPT)
            ccFile = os.path.splitext(ccFile.abspath)[0] + self["SHOBJSUFFIX"]

        sources.append(ccFile)

    sources.sort()
    return sources


#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

##
#  @brief Return a list of files that need to be scanned for tags, starting at directory root
#
#  These tags are for advanced Emacs users, and should not be confused with SVN tags or Doxygen tags.
#
#  Files are chosen if they match fileRegex; toplevel directories in list ignoreDirs are ignored
#  This routine won't do anything unless you specified a "TAGS" target
##
def filesToTag(root=None, fileRegex=None, ignoreDirs=None):
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
        # List of possible files to tag, but there's some cleanup required for machine-generated files
        #
        candidates = [f for f in filenames if re.search(fileRegex, f)]
        #
        # Remove files generated by swig
        #
        for swigFile in [f for f in filenames if re.search(r"\.i$", f)]:
            name = os.path.splitext(swigFile)[0]
            candidates = [f for f in candidates if not re.search(r"%s(_wrap\.cc?|\.py)$" % name, f)]

        files += [os.path.join(dirpath, f) for f in candidates]

    return files


##
#  @brief Build Emacs tags (see man etags for more information).
#
#  Files are chosen if they match fileRegex; toplevel directories in list ignoreDirs are ignored
#  This routine won't do anything unless you specified a "TAGS" target
##
@memberOf(SConsEnvironment)
def BuildETags(env, root=None, fileRegex=None, ignoreDirs=None):
    toTag = filesToTag(root, fileRegex, ignoreDirs)
    if toTag:
        return env.Command("TAGS", toTag, "etags -o $TARGET $SOURCES")


#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

##
#  @brief Remove files matching the argument list starting at dir
#         when scons is invoked with -c/--clean and no explicit targets are listed
#
#   E.g. CleanTree(r"*~ core")
#
#   If recurse is True, recursively descend the file system; if
#   verbose is True, print each filename after deleting it
##
@memberOf(SConsEnvironment)
def CleanTree(self, files, dir=".", recurse=True, verbose=False):
    #
    # Generate command that we may want to execute
    #
    files_expr = ""
    for file in SCons.Script.Split(files):
        if files_expr:
            files_expr += " -o "

        files_expr += "-name %s" % re.sub(r"(^|[^\\])([[*])", r"\1\\\2", file)  # quote unquoted * and []
    #
    # don't use xargs --- who knows what needs quoting?
    #
    action = "find %s" % dir
    action += r" \( -name .svn -prune -o -name \* \) "
    if not recurse:
        action += " ! -name . -prune"

    file_action = "rm -f"

    action += r" \( %s \) -exec %s {} \;" % \
        (files_expr, file_action)

    if verbose:
        action += " -print"
    #
    # Clean up scons files --- users want to be able to say scons -c and get a clean copy
    # We can't delete .sconsign.dblite if we use "scons clean" instead of "scons --clean",
    # so the former is no longer supported.
    #
    action += " ; rm -rf .sconf_temp .sconsign.dblite .sconsign.tmp config.log"
    #
    # Do we actually want to clean up?  We don't if the command is e.g. "scons -c install"
    #
    if "clean" in SCons.Script.COMMAND_LINE_TARGETS:
        state.log.fail("'scons clean' is no longer supported; please use 'scons --clean'.")
    elif not SCons.Script.COMMAND_LINE_TARGETS and self.GetOption("clean"):
        self.Execute(self.Action([action]))
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=


## @brief Return a product's PRODUCT_DIR, or None
@memberOf(SConsEnvironment)
def ProductDir(env, product):
    from . import eupsForScons
    global _productDirs
    try:
        _productDirs
    except:
        try:
            _productDirs = eupsForScons.productDir(eupsenv=eupsForScons.getEups())
        except TypeError:               # old version of eups (pre r18588)
            _productDirs = None
    if _productDirs:
        pdir = _productDirs.get(product)
    else:
        pdir = eupsForScons.productDir(product)
    if pdir == "none":
        pdir = None
    return pdir


#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

##
#  @brief A callable to be used as an SCons Action to run Doxygen.
#
#  This should only be used by the env.Doxygen pseudo-builder method.
#
class DoxygenBuilder(object):

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.results = []
        self.sources = []
        self.targets = []
        self.useTags = list(SCons.Script.File(item).abspath for item in self.useTags)
        self.inputs = list(SCons.Script.Entry(item).abspath for item in self.inputs)
        self.excludes = list(SCons.Script.Entry(item).abspath for item in self.excludes)
        self.outputPaths = list(SCons.Script.Dir(item) for item in self.outputs)

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
        config = env.Command(target=outConfigNode, source=inConfigNode if os.path.exists(config) else None,
                             action=self.buildConfig)
        env.AlwaysBuild(config)
        doc = env.Command(target=self.targets, source=self.sources,
                          action="doxygen %s" % outConfigNode.abspath)
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
        for tagPath in self.useTags:
            docDir, tagFile = os.path.split(tagPath)
            htmlDir = os.path.join(docDir, "html")
            outConfigFile.write('TAGFILES += "%s=%s"\n' % (tagPath, htmlDir))
            self.sources.append(SCons.Script.Dir(docDir))
        docPaths = []
        incFiles = []
        for incPath in self.includes:
            docDir, incFile = os.path.split(incPath)
            docPaths.append('"%s"' % docDir)
            incFiles.append('"%s"' % incFile)
            self.sources.append(SCons.Script.File(incPath))
        if docPaths:
            outConfigFile.write('@INCLUDE_PATH = %s\n' % " ".join(docPaths))
        for incFile in incFiles:
            outConfigFile.write('@INCLUDE = %s\n' % incFile)
        if self.projectName is not None:
            outConfigFile.write("PROJECT_NAME = %s\n" % self.projectName)
        if self.projectNumber is not None:
            outConfigFile.write("PROJECT_NUMBER = %s\n" % self.projectNumber)
        outConfigFile.write("INPUT = %s\n" % " ".join(self.inputs))
        outConfigFile.write("EXCLUDE = %s\n" % " ".join(self.excludes))
        outConfigFile.write("FILE_PATTERNS = %s\n" % " ".join(self.patterns))
        outConfigFile.write("RECURSIVE = YES\n" if self.recursive else "RECURSIVE = NO\n")
        allOutputs = set(("html", "latex", "man", "rtf", "xml"))
        for output, path in zip(self.outputs, self.outputPaths):
            try:
                allOutputs.remove(output.lower())
            except:
                state.log.fail("Unknown Doxygen output format '%s'." % output)
                state.log.finish()
            outConfigFile.write("GENERATE_%s = YES\n" % output.upper())
            outConfigFile.write("%s_OUTPUT = %s\n" % (output.upper(), path.abspath))
        for output in allOutputs:
            outConfigFile.write("GENERATE_%s = NO\n" % output.upper())
        if self.makeTag is not None:
            outConfigFile.write("GENERATE_TAGFILE = %s\n" % self.makeTag)
        #
        # Append the local overrides (usually doxygen.conf.in)
        #
        if len(source) > 0:
            with open(source[0].abspath, "r") as inConfigFile:
                outConfigFile.write(inConfigFile.read())

        outConfigFile.close()


##
#  @brief Generate a Doxygen config file and run Doxygen on it.
#
#  Rather than parse a complete Doxygen config file for SCons sources
#  and targets, this Doxygen builder builds a Doxygen config file,
#  adding INPUT, FILE_PATTERNS, RECUSRIVE, EXCLUDE, XX_OUTPUT and
#  GENERATE_XX options (and possibly others) to an existing
#  proto-config file.  Generated settings will override those in
#  the proto-config file.
#
#  @param config        A Doxygen config file, usually with the
#                       extension .conf.in; a new file with the .in
#                       removed will be generated and passed to
#                       Doxygen.  Settings in the original config
#                       file will be overridden by those generated
#                       by this method.
#  @param inputs        A sequence of folders or files to be passed
#                       as the INPUT setting for Doxygen.  This list
#                       will be turned into absolute paths by SCons,
#                       so the "#folder" syntax will work.
#                       Otherwise, the list is passed in as-is, but
#                       the builder will also examine those
#                       directories to find which source files the
#                       Doxygen output actually depends on.
#  @param patterns      A sequence of glob patterns for the
#                       FILE_PATTERNS Doxygen setting.  This will be
#                       passed directly to Doxygen, but it is also
#                       used to determine which source files should
#                       be considered dependencies.
#  @param recursive     Whether the inputs should be searched
#                       recursively (used for the Doxygen RECURSIVE
#                       setting).
#  @param outputs       A sequence of output formats which will also
#                       be used as output directories.
#  @param exclude       A sequence of folders or files (not globs)
#                       to be ignored by Doxygen (the Doxygen
#                       EXCLUDE setting).  Hidden directories are
#                       automatically ignored.
#  @param includes      A sequence of Doxygen config files to
#                       include.  These will automatically be
#                       separated into paths and files to fill in
#                       the \@INCLUDE_PATH and \@INCLUDE settings.
#  @param useTags       A sequence of Doxygen tag files to use.  It
#                       will be assumed that the html directory for
#                       each tag file is in an "html" subdirectory
#                       in the same directory as the tag file.
#  @param makeTag       A string indicating the name of a tag file
#                       to be generated.
#  @param projectName   Sets the Doxygen PROJECT_NAME setting.
#  @param projectNumber Sets the Doxygen PROJECT_NUMBER setting.
#  @param excludeSwig   If True (default), looks for SWIG .i files
#                       in the input directories and adds Python
#                       and C++ files generated by SWIG to the
#                       list of files to exclude.  For this to work,
#                       the SWIG-generated filenames must be the
#                       default ones ("module.i" generates "module.py"
#                       and "moduleLib_wrap.cc").
#
# @note When building documentation from a clean source tree,
#       generated source files (like headers generated with M4)
#       will not be included among the dependencies, because
#       they aren't present when we walk the input folders.
#       The workaround is just to build the docs after building
#       the source.
##
@memberOf(SConsEnvironment)
def Doxygen(self, config, **kw):
    inputs = [d for d in ["#doc", "#include", "#python", "#src"]
              if os.path.exists(SCons.Script.Entry(d).abspath)]
    defaults = {
        "inputs": inputs,
        "recursive": True,
        "patterns": ["*.h", "*.cc", "*.py", "*.dox"],
        "outputs": ["html"],
        "excludes": [],
        "includes": [],
        "useTags": [],
        "makeTag": None,
        "projectName": None,
        "projectNumber": None,
        "excludeSwig": True
        }
    for k in defaults:
        if kw.get(k) is None:
            kw[k] = defaults[k]
    builder = DoxygenBuilder(**kw)
    return builder(self, config)


@memberOf(SConsEnvironment)
def VersionModule(self, filename, versionString=None):
    if versionString is None:
        for n in ("git", "hg", "svn",):
            if os.path.isdir(".%s" % n):
                versionString = n

        if not versionString:
            versionString = "git"

    def calcMd5(filename):
        try:
            import hashlib
            md5 = hashlib.md5("\n".join(open(filename).readlines())).hexdigest()
        except IOError:
            md5 = None

        return md5

    oldMd5 = calcMd5(filename)

    def makeVersionModule(target, source, env):
        try:
            version = determineVersion(state.env, versionString)
        except RuntimeError:
            version = "unknown"
        parts = version.split("+")

        names = []
        with open(target[0].abspath, "w") as outFile:
            outFile.write("#--------- This file is automatically generated by LSST's sconsUtils ---------#\n")

            what = "__version__"
            outFile.write("%s = '%s'\n" % (what, version))
            names.append(what)

            what = "__repo_version__"
            outFile.write("%s = '%s'\n" % (what, parts[0]))
            names.append(what)

            what = "__repo_version__"
            outFile.write("%s = '%s'\n" % (what, parts[0]))
            names.append(what)

            what = "__fingerprint__"
            outFile.write("%s = '%s'\n" % (what, getFingerprint(versionString)))
            names.append(what)

            try:
                info = tuple(int(v) for v in parts[0].split("."))
                what = "__version_info__"
                names.append(what)
                outFile.write("%s = %r\n" % (what, info))
            except ValueError:
                pass

            if len(parts) > 1:
                try:
                    what = "__rebuild_version__"
                    outFile.write("%s = %s\n" % (what, int(parts[1])))
                    names.append(what)
                except ValueError:
                    pass

            what = "__dependency_versions__"
            names.append(what)
            outFile.write("%s = {\n" % (what))
            for name, mod in env.dependencies.packages.items():
                if mod is None:
                    outFile.write("    '%s': None,\n" % name)
                elif hasattr(mod.config, "version"):
                    outFile.write("    '%s': '%s',\n" % (name, mod.config.version))
                else:
                    outFile.write("    '%s': 'unknown',\n" % name)
            outFile.write("}\n")

            outFile.write("__all__ = %r\n" % (tuple(names),))

        if calcMd5(target[0].abspath) != oldMd5:  # only print if something's changed
            state.log.info("makeVersionModule([\"%s\"], [])" % str(target[0]))

    result = self.Command(filename, [], self.Action(makeVersionModule, strfunction=lambda *args: None))

    self.AlwaysBuild(result)
    return result
