
"""Dependency configuration and definition."""

__all__ = ("Configuration", "ExternalConfiguration", "PackageTree", "configure")

import os.path
import collections
import imp
import re
import subprocess
import SCons.Script
from . import eupsForScons
from SCons.Script.SConscript import SConsEnvironment
from sys import platform

from . import installation
from . import state


def configure(packageName, versionString=None, eupsProduct=None, eupsProductPath=None, noCfgFile=False):
    """Recursively configure a package using ups/.cfg files.

    Aliased as `lsst.sconsUtils.configure()`.

    Usually, LSST packages will call this function through
    `~lsst.sconsUtils.scripts.BasicSConstruct`.

    Parameters
    ----------
    packageName : `str`
        Name of the package being built; must correspond to a ``.cfg`` file
        in the ``ups`` directory.
    versionString : `str`, optional
        Version-control system string to be parsed for version information
        (``$HeadURL$`` for SVN).
    eupsProduct : `str`, optional
        Name of the EUPS product being built.  Defaults to and is almost
        always the name of the package.
    eupsProductPath : `str`, optional
        An alternate directory where the package should be installed.
    noCfgFile : `bool`
        If True, this package has no ``.cfg`` file.

    Returns
    -------
    env : `SCons.Environment`
        An SCons Environment object (which is also available as
        `lsst.sconsUtils.env`).
    """

    if not state.env.GetOption("no_progress"):
        state.log.info("Setting up environment to build package '%s'." % packageName)
    if eupsProduct is None:
        eupsProduct = packageName
    if versionString is None:
        versionString = "git"
    state.env['eupsProduct'] = eupsProduct
    state.env['packageName'] = packageName
    #
    # Setup installation directories and variables
    #
    SCons.Script.Help(state.opts.GenerateHelpText(state.env))
    state.env.installing = [t for t in SCons.Script.BUILD_TARGETS if t == "install"]
    state.env.declaring = [t for t in SCons.Script.BUILD_TARGETS if t == "declare" or t == "current"]
    state.env.linkFarmDir = state.env.GetOption("linkFarmDir")
    if state.env.linkFarmDir:
        state.env.linkFarmDir = os.path.abspath(os.path.expanduser(state.env.linkFarmDir))
    prefix = installation.setPrefix(state.env, versionString, eupsProductPath)
    state.env['prefix'] = prefix
    state.env["libDir"] = "%s/lib" % prefix
    state.env["pythonDir"] = "%s/python" % prefix
    #
    # Process dependencies
    #
    state.log.traceback = state.env.GetOption("traceback")
    state.log.verbose = state.env.GetOption("verbose")
    packages = PackageTree(packageName, noCfgFile=noCfgFile)
    state.log.flush()  # if we've already hit a fatal error, die now.
    state.env.libs = {"main": [], "python": [], "test": []}
    state.env.doxygen = {"tags": [], "includes": []}
    state.env['CPPPATH'] = []
    state.env['LIBPATH'] = []

    # XCPPPATH is a new variable defined by sconsUtils - it's like CPPPATH,
    # but the headers found there aren't treated as dependencies.  This can
    # make scons a lot faster.
    state.env['XCPPPATH'] = []

    # XCPPPPREFIX is a replacement for SCons' built-in INCPREFIX. It is used
    # when compiling headers in XCPPPATH directories. Here, we set it to
    # `-isystem`, so that those are regarded as "system headers" and warnings
    # are suppressed.
    state.env['XCPPPREFIX'] = "-isystem "

    state.env['_CPPINCFLAGS'] = \
        "$( ${_concat(INCPREFIX, CPPPATH, INCSUFFIX, __env__, RDirs, TARGET, SOURCE)}"\
        " ${_concat(XCPPPREFIX, XCPPPATH, INCSUFFIX, __env__, RDirs, TARGET, SOURCE)} $)"
    state.env['_SWIGINCFLAGS'] = state.env['_CPPINCFLAGS'] \
                                      .replace("CPPPATH", "SWIGPATH") \
                                      .replace("XCPPPREFIX", "SWIGINCPREFIX")

    if state.env.linkFarmDir:
        for d in [state.env.linkFarmDir, "#"]:
            state.env.Append(CPPPATH=os.path.join(d, "include"))
            state.env.Append(LIBPATH=os.path.join(d, "lib"))
        state.env['SWIGPATH'] = state.env['CPPPATH']

    if not state.env.GetOption("clean") and not state.env.GetOption("help"):
        packages.configure(state.env, check=state.env.GetOption("checkDependencies"))
        for target in state.env.libs:
            state.log.info("Libraries in target '%s': %s" % (target, state.env.libs[target]))
    state.env.dependencies = packages
    state.log.flush()


class Configuration:
    """Base class for defining how to configure an LSST sconsUtils package.

    Aliased as `lsst.sconsUtils.Configuration`.

    An ``ups/*.cfg`` file should contain an instance of this class called
    "config".  Most LSST packages will be able to use this class directly
    instead of subclassing it.

    The only important method is configure(), which modifies an SCons
    environment to use the package.  If a subclass overrides configure,
    it may not need to call the base class ``__init__()``, whose only
    purpose is to define a number of instance variables used by configure().

    Parameters
    ----------
    cfgFile : `str`
        The name of the calling .cfg file, usually just passed in with the
        special variable ``__file__``.  This will be parsed to extract the
        package name and root.
    headers : `list` of `str`, optional
        A list of headers provided by the package, to be used in autoconf-style
        tests.
    libs : `list` or `dict`, optional
        A list or dictionary of libraries provided by the package.  If a
        dictionary is provided, ``libs["main"]`` should contain a list of
        regular libraries provided by the library.  Other keys are "python"
        and "test", which refer to libraries that are only linked against
        compiled Python modules and unit tests, respectively.  If a list is
        provided, the list is used as "main".  These are used both for
        autoconf-style tests and to support ``env.getLibs(...)``, which
        recursively computes the libraries a package must be linked with.
    hasSwigFiles : `bool`, optional
        If True, the package provides SWIG interface files in
        ``<root>/python``.
    hasDoxygenInclude : `bool`, optional
        If True, the package provides a Doxygen include file with the
        name ``<root>/doc/<name>.inc``.
    hasDoxygenTag : `bool`, optional
        If True, the package generates a Doxygen TAG file.
    includeFileDirs : `list`, optional
        List of directories that should be searched for include files.
    libFileDirs : `list`, optional
        List of directories that should be searched for libraries.
    eupsProduct : `str`
        Name of the EUPS product for the package, if different from the name
        of the ``.cfg`` file.
    """

    @staticmethod
    def parseFilename(cfgFile):
        """Parse the name of a .cfg file and return package name and root.

        Parameters
        ----------
        cfgFile : `str`
            Name of a ``.cfg`` file.

        Returns
        -------
        name : `str`
            Package name
        root : `str`
            Root directory.
        """
        dir, file = os.path.split(cfgFile)
        name, ext = os.path.splitext(file)
        return name, os.path.abspath(os.path.join(dir, ".."))

    @staticmethod
    def getEupsData(eupsProduct):
        """Get EUPS version and product directory for named product.

        Parameters
        ----------
        eupsProduct : `str`
            EUPS product name.

        Returns
        -------
        version : `str`
            EUPS product version.
        productDir : `str`
            EUPS product root directory.
        """
        version, eupsPathDir, productDir, table, flavor = eupsForScons.getEups().findSetupVersion(eupsProduct)
        if productDir is None:
            productDir = eupsForScons.productDir(eupsProduct)
        return version, productDir

    def __init__(self, cfgFile, headers=(), libs=None, hasSwigFiles=True,
                 includeFileDirs=["include"], libFileDirs=["lib"],
                 hasDoxygenInclude=False, hasDoxygenTag=True, eupsProduct=None):
        self.name, self.root = self.parseFilename(cfgFile)
        if eupsProduct is None:
            eupsProduct = self.name
        self.eupsProduct = eupsProduct
        version, productDir = self.getEupsData(self.eupsProduct)
        if version is not None:
            self.version = version
        if productDir is None:
            try:
                python3rdinclude = self._get_config_var("CONFINCLUDEPY")
                includeDir, pyFolder = os.path.split(python3rdinclude)
                if os.path.exists(includeDir):
                    self.root = os.path.realpath(includeDir)
                else:
                    state.log.warn("Could not find Lib package dir for '%s'; using %s."
                                   % (self.eupsProduct, self.root))
            except Exception as e:
                state.log.warn("Could not find EUPS/lib package dir for '%s'; using %s."
                               % (self.eupsProduct, self.root))
                state.log.warn(e)
        else:
            self.root = os.path.realpath(productDir)
        self.doxygen = {
            # Doxygen tag files generated by this package
            "tags": ([os.path.join(self.root, "doc", "%s.tag" % self.name)]
                     if hasDoxygenTag else []),
            # Doxygen include files to include in the configuration of
            # dependent products
            "includes": ([os.path.join(self.root, "doc", "%s.inc" % self.name)]
                         if hasDoxygenInclude else [])
        }
        if libs is None:
            self.libs = {
                # Normal libraries provided by this package
                "main": [self.name],
                # Libraries provided that should only be linked with Python
                # modules
                "python": [],
                # Libraries provided that should only be linked with unit
                # test code
                "test": [],
            }
        elif "main" in libs:
            self.libs = libs
        else:
            self.libs = {"main": libs, "python": [], "test": []}
        self.paths = {}
        if hasSwigFiles:
            self.paths["SWIGPATH"] = [os.path.join(self.root, "python")]
        else:
            self.paths["SWIGPATH"] = []

        for pathName, subDirs in [("CPPPATH", includeFileDirs),
                                  ("LIBPATH", libFileDirs)]:
            self.paths[pathName] = []

            if state.env.linkFarmDir:
                continue

            for subDir in subDirs:
                pathDir = os.path.join(self.root, subDir)
                if os.path.isdir(pathDir):
                    self.paths[pathName].append(pathDir)

        self.provides = {
            "headers": tuple(headers),
            "libs": tuple(self.libs["main"])
        }

    def addCustomTests(self, tests):
        """Add custom SCons configuration tests to the Configure Context
        passed to the configure() method.

        This needs to be done up-front so we can pass in a dictionary of
        custom tests when calling ``env.Configure()``, and use the same
        configure context for all packages.

        Parameters
        ----------
        tests : `dict`
            A dictionary to add custom tests to.  This will be passed as the
            custom_tests argument to ``env.Configure()``.
        """
        pass

    def configure(self, conf, packages, check=False, build=True):
        """Update an SCons environment to make use of the package.

        Parameters
        ----------
        conf : `SCons.Configure`
            An SCons Configure context.  The SCons Environment conf.env
            should be updated by the configure function.
        packages : `dict`
            A dictionary containing the configuration modules of all
            dependencies (or `None` if the dependency was optional and was not
            found).  The ``<module>.config.configure(...)`` method will have
            already been called on all dependencies.
        check : `bool`, optional
            If True, perform autoconf-style tests to verify that key
            components are in fact in place.
        build : `bool`, optional
            If True, this is the package currently being built, and packages in
            "buildRequired" and "buildOptional" dependencies will also be
            present in the packages dict.
        """
        assert(not (check and build))
        self.configurePython(conf, packages, check, build)
        conf.env.PrependUnique(**self.paths)
        state.log.info("Configuring package '%s'." % self.name)
        conf.env.doxygen["includes"].extend(self.doxygen["includes"])
        if not build:
            conf.env.doxygen["tags"].extend(self.doxygen["tags"])
        for target in self.libs:
            if target not in conf.env.libs:
                conf.env.libs[target] = self.libs[target].copy()
                state.log.info("Adding '%s' libraries to target '%s'." % (self.libs[target], target))
            else:
                for lib in self.libs[target]:
                    if lib not in conf.env.libs[target]:
                        conf.env.libs[target].append(lib)
                        state.log.info("Adding '%s' library to target '%s'." % (lib, target))
        if check:
            for header in self.provides["headers"]:
                if not conf.CheckCXXHeader(header):
                    return False
            for lib in self.libs["main"]:
                if not conf.CheckLib(lib, autoadd=False, language="C++"):
                    return False
        return True

    @staticmethod
    def _get_config_var(name):
        """The relevant Python is not guaranteed to be the Python
        that we are using to run SCons so we must shell out to the
        PATH python."""
        pycmd = 'import distutils.sysconfig as s; print(s.get_config_var("{}"))'.format(name)
        result = subprocess.check_output(["python", "-c", pycmd]).decode().strip()
        # Be consistent with native interface
        if result == "None":
            result = None
        return result

    def configurePython(self, conf, packages, check=False, build=True):
        state.log.info("Configuring package '%s'." % self.name)
        python3rdinclude = self._get_config_var("CONFINCLUDEPY")
        conf.env.AppendUnique(XCPPPATH=python3rdinclude)
        conf.env.AppendUnique(XCPPPATH=python3rdinclude + "/..")
        conf.env.AppendUnique(XCPPPATH=python3rdinclude + "/../eigen3")
        usedC = state.env['CXX']
        coutput = subprocess.run('which ' + usedC, shell=True, stdout=subprocess.PIPE)
        full_path = coutput.stdout.decode('UTF-8')
        cpath, fcfile = os.path.split(full_path)
        conf.env.AppendUnique(LIBPATH=[cpath + "/../lib"])
        libDir = self._get_config_var("LIBPL")
        conf.env.AppendUnique(LIBPATH=[libDir])
        conf.env.AppendUnique(LIBPATH=[libDir+'/../..'])
        if platform == "darwin":
            conf.env["_RPATH"] = '-rpath ' + python3rdinclude + '/../../lib'
        else:
            conf.env.AppendUnique(RPATH=[python3rdinclude + '/../../lib'])
        pylibrary = self._get_config_var("LIBRARY")
        mat = re.search(r"(python.*)\.(a|so|dylib)$", pylibrary)
        if mat:
            conf.env.libs["python"].append(mat.group(1))
            state.log.info("Adding '%s' to target 'python'." % mat.group(1))
        for w in (" ".join([self._get_config_var("MODLIBS"),
                            self._get_config_var("SHLIBS")])).split():
            mat = re.search(r"^-([Ll])(.*)", w)
            if mat:
                lL = mat.group(1)
                arg = mat.group(2)
                if lL == "l":
                    if arg not in conf.env.libs:
                        conf.env.libs["python"].append(arg)
                        state.log.info("Adding '%s' to target 'python'." % arg)
                else:
                    if os.path.isdir(arg):
                        conf.env.AppendUnique(LIBPATH=[arg])
                        state.log.info("Adding '%s' to link path." % arg)
        if conf.env['PLATFORM'] == 'darwin':
            frameworkDir = libDir           # search up the libDir tree for the proper home for frameworks
            while frameworkDir and not re.match("^//*$", frameworkDir):
                frameworkDir, d2 = os.path.split(frameworkDir)
                if d2 == "Python.framework":
                    if "Python" not in os.listdir(os.path.join(frameworkDir, d2)):
                        state.log.warn(
                            "Expected to find Python in framework directory %s, but it isn't there"
                            % frameworkDir
                        )
                        return False
                    break
            opt = "-F%s" % frameworkDir
            if opt not in conf.env["LDMODULEFLAGS"]:
                conf.env.Append(LDMODULEFLAGS=[opt, ])
        return True


class ExternalConfiguration(Configuration):
    """A Configuration subclass for external (third-party) packages.

    Aliased as `lsst.sconsUtils.ExternalConfiguration`.

    ExternalConfiguration doesn't assume the package uses SWIG or Doxygen,
    and tells SCons not to consider header files this package provides as
    dependencies (by setting XCPPPATH instead of CPPPATH).  This means things
    SCons won't waste time looking for changes in it every time you build.
    Header files in external packages are treated as "system headers": that
    is, most warnings generated when they are being compiled are suppressed.

    Parameters
    ----------
    cfgFile : `str`
        The name of the calling ``.cfg`` file, usually just passed in with the
        special variable ``__file__``.  This will be parsed to extract the
        package name and root.
    headers : `list`, optional
        A list of headers provided by the package, to be used in
        autoconf-style tests.
    libs : `list` or `dict`, optional
        A list or dictionary of libraries provided by the package.  If a
        dictionary is provided, ``libs["main"]`` should contain a list of
        regular libraries provided by the library.  Other keys are "python"
        and "test", which refer to libraries that are only linked against
        compiled Python modules and unit tests, respectively.  If a list is
        provided, the list is used as "main".  These are used both for
        autoconf-style tests and to support env.getLibs(...), which
        recursively computes the libraries a package must be linked with.
    eupsProduct : `str`, optional
        The EUPS product being built.
    """
    def __init__(self, cfgFile, headers=(), libs=None, eupsProduct=None):
        Configuration.__init__(self, cfgFile, headers, libs, eupsProduct=eupsProduct, hasSwigFiles=False,
                               hasDoxygenTag=False, hasDoxygenInclude=False)
        self.paths["XCPPPATH"] = self.paths["CPPPATH"]
        del self.paths["CPPPATH"]


def CustomCFlagCheck(context, flag, append=True):
    """A configuration test that checks whether a C compiler supports
    a particular flag.

    Parameters
    ----------
    context :
        Configuration context.
    flag : `str`
        Flag to test, e.g., ``-fvisibility-inlines-hidden``.
    append : `bool`, optional
        Automatically append the flag to ``context.env["CCFLAGS"]``
        if the compiler supports it?

    Returns
    -------
    result : `bool`
        Did the flag work?
    """
    context.Message("Checking if C compiler supports " + flag + " flag ")
    ccflags = context.env["CCFLAGS"]
    context.env.Append(CCFLAGS=flag)
    result = context.TryCompile("int main(int argc, char **argv) { return 0; }", ".c")
    context.Result(result)
    if not append or not result:
        context.env.Replace(CCFLAGS=ccflags)
    return result


def CustomCppFlagCheck(context, flag, append=True):
    """A configuration test that checks whether a C++ compiler supports
    a particular flag.

    Parameters
    ----------
    context :
        Configuration context.
    flag : `str`
        Flag to test, e.g., ``-fvisibility-inlines-hidden``.
    append : `bool`, optional
        Automatically append the flag to ``context.env["CXXFLAGS"]``
        if the compiler supports it?

    Returns
    -------
    result : `bool`
        Did the flag work?
    """
    context.Message("Checking if C++ compiler supports " + flag + " flag ")
    cxxflags = context.env["CXXFLAGS"]
    context.env.Append(CXXFLAGS=flag)
    result = context.TryCompile("int main(int argc, char **argv) { return 0; }", ".cc")
    context.Result(result)
    if not append or not result:
        context.env.Replace(CXXFLAGS=cxxflags)
    return result


def CustomCompileCheck(context, message, source, extension=".cc"):
    """A configuration test that checks whether the given source code
    compiles.

    Parameters
    ----------
    context :
        Configuration context.
    message : `str`
        Message displayed on console prior to running the test.
    source : `str`
        Source code to compile.
    extension : `str`, optional
        Identifies the language of the source code. Use ".c" for C, and ".cc"
        for C++ (the default).

    Returns
    -------
    result : `bool`
        Did the code compile?
    """
    context.Message(message)

    env = context.env
    if (env.GetOption("clean") or env.GetOption("help") or env.GetOption("no_exec")):
        result = True
    else:
        result = context.TryCompile(source, extension)

    context.Result(result)

    return result


def CustomLinkCheck(context, message, source, extension=".cc"):
    """A configuration test that checks whether the given source code
    compiles and links.

    Parameters
    ----------
    context :
        Configuration context.
    message : `str`
        Message displayed on console prior to running the test.
    source : `str`
        Source code to compile.
    extension : `str`, optional
        Identifies the language of the source code. Use ".c" for C, and ".cc"
        for C++ (the default).

    Returns
    -------
    result : `bool`
        Did the code compile and link?
    """
    context.Message(message)
    result = context.TryLink(source, extension)
    context.Result(result)
    return result


class PackageTree:
    """A class for loading and managing the dependency tree of a package,
    as defined by its configuration module (.cfg) file.

    This tree isn't actually stored as a tree; it's flattened into an ordered
    dictionary as it is recursively loaded.

    The main SCons produced by configure() and available as
    `lsst.sconsUtils.env` will contain an instance of this class as
    ``env.dependencies``.

    Its can be used like a read-only dictionary to check whether an optional
    package has been configured; a package that was not found will have a
    value of None, while a configured package's value will be its imported
    .cfg module.

    Parameters
    ----------
    primaryName : `str`
        The name of the primary package being built.
    noCfgFile : `bool`, optional
        If True, this package has no .cfg file

    Notes
    -----
    After ``__init__``, ``self.primary`` will be set to the configuration
    module for the primary package, and ``self.packages`` will be an
    `OrderedDict` of dependencies (excluding ``self.primary``), ordered
    such that configuration can proceed in iteration order.
    """
    def __init__(self, primaryName, noCfgFile=False):
        self.cfgPath = state.env.cfgPath
        self.packages = collections.OrderedDict()
        self.customTests = {
            "CustomCFlagCheck": CustomCFlagCheck,
            "CustomCppFlagCheck": CustomCppFlagCheck,
            "CustomCompileCheck": CustomCompileCheck,
            "CustomLinkCheck": CustomLinkCheck,
        }
        self._current = set([primaryName])
        if noCfgFile:
            self.primary = None
            return

        self.primary = self._tryImport(primaryName)
        if self.primary is None:
            state.log.fail("Failed to load primary package configuration for %s." % primaryName)

        missingDeps = []
        for dependency in self.primary.dependencies.get("required", ()):
            if not self._recurse(dependency):
                missingDeps.append(dependency)
        if missingDeps:
            state.log.fail("Failed to load required dependencies: \"%s\"" % '", "'.join(missingDeps))

        missingDeps = []
        for dependency in self.primary.dependencies.get("buildRequired", ()):
            if not self._recurse(dependency):
                missingDeps.append(dependency)
        if missingDeps:
            state.log.fail("Failed to load required build dependencies: \"%s\"" % '", "'.join(missingDeps))

        for dependency in self.primary.dependencies.get("optional", ()):
            self._recurse(dependency)

        for dependency in self.primary.dependencies.get("buildOptional", ()):
            self._recurse(dependency)

    name = property(lambda self: self.primary.config.name)

    def configure(self, env, check=False):
        """Configure the entire dependency tree in order. and return an
        updated environment."""
        conf = env.Configure(custom_tests=self.customTests)
        for name, module in self.packages.items():
            if module is None:
                state.log.info("Skipping missing optional package %s." % name)
                continue
            if not module.config.configure(conf, packages=self.packages, check=check, build=False):
                state.log.fail("%s was found but did not pass configuration checks." % name)
        if self.primary:
            self.primary.config.configure(conf, packages=self.packages, check=False, build=True)
        env.AppendUnique(SWIGPATH=env["CPPPATH"])
        env.AppendUnique(XSWIGPATH=env["XCPPPATH"])
        # reverse the order of libraries in env.libs, so libraries that
        # fulfill a dependency of another appear after it. required by the
        # linker to successfully resolve symbols in static libraries.
        for target in env.libs:
            env.libs[target].reverse()
        env = conf.Finish()
        return env

    def __contains__(self, name):
        return name == self.name or name in self.packages

    has_key = __contains__

    def __getitem__(self, name):
        if name == self.name:
            return self.primary
        else:
            return self.packages[name]

    def get(self, name, default=None):
        if name == self.name:
            return self.primary
        else:
            return self.packages.get(name)

    def keys(self):
        k = list(self.packages.keys())
        k.append(self.name)
        return k

    def _tryImport(self, name):
        """Search for and import an individual configuration module from
        file."""
        for path in self.cfgPath:
            filename = os.path.join(path, name + ".cfg")
            if os.path.exists(filename):
                try:
                    module = imp.load_source(name + "_cfg", filename)
                except Exception as e:
                    state.log.warn("Error loading configuration %s (%s)" % (filename, e))
                    continue
                state.log.info("Using configuration for package '%s' at '%s'." % (name, filename))
                if not hasattr(module, "dependencies") or not isinstance(module.dependencies, dict):
                    state.log.warn("Configuration module for package '%s' lacks a dependencies dict." % name)
                    return None
                if not hasattr(module, "config") or not isinstance(module.config, Configuration):
                    state.log.warn("Configuration module for package '%s' lacks a config object." % name)
                    return None
                else:
                    module.config.addCustomTests(self.customTests)
                return module
        state.log.info("Failed to import configuration for optional package '%s'." % name)

    def _recurse(self, name):
        """Recursively load a dependency.

        Parameters
        ----------
        name : `str`
            Name of dependent package.

        Returns
        -------
        loaded : `bool`
            Was the dependency loaded?
        """
        if name in self._current:
            state.log.fail("Detected recursive dependency involving package '%s'" % name)
        else:
            self._current.add(name)
        if name in self.packages:
            self._current.remove(name)
            return self.packages[name] is not None
        module = self._tryImport(name)
        if module is None:
            self.packages[name] = None
            self._current.remove(name)
            return False
        for dependency in module.dependencies.get("required", ()):
            if not self._recurse(dependency):
                # We can't configure this package because a required
                # dependency wasn't found.  But this package might itself be
                # optional, so we don't die yet.
                self.packages[name] = None
                self._current.remove(name)
                state.log.warn("Could not load all dependencies for package '%s' (missing %s)." %
                               (name, dependency))
                return False
        for dependency in module.dependencies.get("optional", ()):
            self._recurse(dependency)
        # This comes last to ensure the ordering puts all dependencies first.
        self.packages[name] = module
        self._current.remove(name)
        return True


def getLibs(env, categories="main"):
    """Get the libraries the package should be linked with.

    Parameters
    ----------
    categories : `str`
        A string containing whitespace-delimited categories.  Standard
        categories are "main", "python", and "test".  Default is "main".
        A special virtual category "self" can be provided, returning
        the results of targets="main" with the ``env["packageName"]`` removed.

    Returns
    -------
    libs : `list`
        Libraries to use.

    Notes
    -----
    Typically, main libraries will be linked with ``LIBS=getLibs("self")``,
    Python modules will be linked with ``LIBS=getLibs("main python")`` and
    C++-coded test programs will be linked with ``LIBS=getLibs("main test")``.
    """
    libs = []
    removeSelf = False
    for category in categories.split():
        if category == "self":
            category = "main"
            removeSelf = True
        for lib in env.libs[category]:
            if lib not in libs:
                libs.append(lib)
    if removeSelf:
        try:
            libs.remove(env["packageName"])
        except ValueError:
            pass
    return libs


SConsEnvironment.getLibs = getLibs
