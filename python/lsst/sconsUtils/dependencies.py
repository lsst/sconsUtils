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

"""Dependency configuration and definition."""

__all__ = ("Configuration", "ExternalConfiguration", "PackageTree", "configure")

import collections
import importlib
import os
import os.path
from sys import platform

import SCons.Script
from SCons.Script.SConscript import SConsEnvironment

from . import eupsForScons, installation, pkgconfig, state
from .utils import get_conda_prefix, use_conda_compilers


def configure(packageName, versionString=None, eupsProduct=None, eupsProductPath=None, noCfgFile=False):
    """Configure a package from its pkg-config template or ups/.cfg files.

    Aliased as `lsst.sconsUtils.configure`.

    Usually, LSST packages will call this function through
    `~lsst.sconsUtils.scripts.BasicSConstruct`.

    If the build root contains a pkg-config template
    ``lsst_<packageName>.pc.in``, ``lib/pkgconfig/lsst_<packageName>.pc`` is
    written from it and the package's dependencies are resolved through
    pkg-config; ``.cfg`` files are never consulted.  Otherwise the
    dependency tree is loaded recursively from ``.cfg`` files.  A package
    with both a template and a ``ups/<packageName>.cfg`` is an error.

    Parameters
    ----------
    packageName : `str`
        Name of the package being built; must correspond to a pkg-config
        template at the build root or a ``.cfg`` file in the ``ups``
        directory.
    versionString : `str`, optional
        Version-control system string to be parsed for version information
        (``$HeadURL$`` for SVN).
    eupsProduct : `str`, optional
        Name of the EUPS product being built.  Defaults to and is almost
        always the name of the package.
    eupsProductPath : `str`, optional
        An alternate directory where the package should be installed.
    noCfgFile : `bool`
        If True, this package has no ``.cfg`` file.  Ignored if the package
        has a pkg-config template.

    Returns
    -------
    env : `SCons.Environment`
        An SCons Environment object (which is also available as
        `lsst.sconsUtils.env`).
    """

    if not state.env.GetOption("no_progress"):
        state.log.info(f"Setting up environment to build package '{packageName}'.")
    if eupsProduct is None:
        eupsProduct = packageName
    if versionString is None:
        versionString = "git"
    state.env["eupsProduct"] = eupsProduct
    state.env["packageName"] = packageName
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
    state.env["prefix"] = prefix
    state.env["libDir"] = f"{prefix}/lib"
    state.env["pythonDir"] = f"{prefix}/python"
    #
    # Process dependencies
    #
    state.log.traceback = state.env.GetOption("traceback")
    state.log.verbose = state.env.GetOption("verbose")
    root = SCons.Script.Dir("#").abspath
    try:
        pkgconfig.check_single_format(root, packageName)
    except pkgconfig.PkgConfigError as err:
        state.log.fail(str(err))
    # A pkg-config template selects the pkg-config path, in which case no
    # .cfg file is ever consulted for this build.
    usePkgConfig = os.path.exists(pkgconfig.template_path(root, packageName))
    packages = None if usePkgConfig else PackageTree(packageName, noCfgFile=noCfgFile)
    state.log.flush()  # if we've already hit a fatal error, die now.
    state.env.libs = {"main": [], "python": [], "test": []}
    state.env.doxygen = {"tags": [], "includes": []}
    state.env["CPPPATH"] = []

    _conda_prefix = get_conda_prefix()
    # _conda_prefix is usually around, even if not using conda compilers
    if use_conda_compilers():
        # if using the conda-force conda compilers, they handle rpath for us
        _conda_lib = f"{_conda_prefix}/lib"
        state.env["LIBPATH"] = [_conda_lib]
        if platform == "darwin":
            state.env["_RPATH"] = f"-rpath {_conda_lib}"
        else:
            state.env.AppendUnique(RPATH=[_conda_lib])
    else:
        state.env["LIBPATH"] = []

    # XCPPPATH is a new variable defined by sconsUtils - it's like CPPPATH,
    # but the headers found there aren't treated as dependencies.  This can
    # make scons a lot faster.
    state.env["XCPPPATH"] = []

    if use_conda_compilers():
        state.env.Append(XCPPPATH=[f"{_conda_prefix}/include"])

    # XCPPPPREFIX is a replacement for SCons' built-in INCPREFIX. It is used
    # when compiling headers in XCPPPATH directories. Here, we set it to
    # `-isystem`, so that those are regarded as "system headers" and warnings
    # are suppressed.
    state.env["XCPPPREFIX"] = "-isystem "

    state.env["_CPPINCFLAGS"] = (
        "$( ${_concat(INCPREFIX, CPPPATH, INCSUFFIX, __env__, RDirs, TARGET, SOURCE)}"
        " ${_concat(XCPPPREFIX, XCPPPATH, INCSUFFIX, __env__, RDirs, TARGET, SOURCE)} $)"
    )

    if state.env.linkFarmDir:
        for d in [state.env.linkFarmDir, "#"]:
            state.env.Append(CPPPATH=os.path.join(d, "include"))
            state.env.Append(LIBPATH=os.path.join(d, "lib"))

    if usePkgConfig:
        state.env.dependencies = _configurePkgConfig(root, packageName)
    else:
        if not state.env.GetOption("clean") and not state.env.GetOption("help"):
            packages.configure(state.env)
        state.env.dependencies = packages
    if not state.env.GetOption("clean") and not state.env.GetOption("help"):
        for target in state.env.libs:
            state.log.info(f"Libraries in target '{target}': {state.env.libs[target]}")
    state.log.flush()


def _configurePkgConfig(root, packageName):
    """Configure the package being built through pkg-config.

    Parameters
    ----------
    root : `str`
        Absolute path to the build root, holding the package's pkg-config
        template.
    packageName : `str`
        Name of the package being built.

    Returns
    -------
    dependencies : `~lsst.sconsUtils.pkgconfig.PkgConfigDependencies`
        The resolved dependencies, to be stored as ``env.dependencies``.
        With ``--clean`` or ``--help`` pkg-config is not run at all and the
        result is empty; with ``--clean`` and no explicit targets the
        generated ``.pc`` file is removed instead.
    """
    if state.env.GetOption("clean") or state.env.GetOption("help"):
        # Mirror the condition CleanTree uses, so that e.g.
        # "scons --clean install" does not remove the file.
        if state.env.GetOption("clean") and not SCons.Script.COMMAND_LINE_TARGETS:
            if pkgconfig.remove_generated_pc(root, packageName):
                state.log.info(f"Removed {pkgconfig.output_path(root, packageName)}.")
        empty = pkgconfig.ResolvedDependencies(
            modules=[],
            cpppath=[],
            xcpppath=[],
            ccflags=[],
            libpath=[],
            linkflags=[],
            libs={"main": [], "python": [], "test": []},
            doxygen={"tags": [], "includes": []},
            versions={},
        )
        return pkgconfig.PkgConfigDependencies(packageName, empty)

    try:
        _writeShims(root)
        template = pkgconfig.template_path(root, packageName)
        output = pkgconfig.output_path(root, packageName)
        if pkgconfig.write_pc_from_template(template, output, state.env["version"]):
            state.log.info(f"Wrote {output} from {template}.")
        condaPrefix = get_conda_prefix()
        runner = pkgconfig.PkgConfig(pkgconfig.build_search_path(root, os.environ), condaPrefix)
        state.log.info(f"Using pkg-config at '{runner.executable}'.")
        resolved = pkgconfig.resolve(packageName, runner, condaPrefix)
    except (pkgconfig.PkgConfigError, OSError) as err:
        state.log.fail(str(err))
    state.log.info(f"Configuring package '{packageName}' through pkg-config modules {resolved.modules}.")
    state.log.info(f"CPPPATH from pkg-config: {resolved.cpppath}")
    state.log.info(f"XCPPPATH from pkg-config: {resolved.xcpppath}")
    pkgconfig.apply_to_env(state.env, resolved)
    return pkgconfig.PkgConfigDependencies(packageName, resolved)


def _writeShims(root):
    """Write the configure-time pkg-config shims for a build.

    Parameters
    ----------
    root : `str`
        Absolute path to the build root; the shims are written into its
        ``.sconf_temp/pkgconfig`` directory.

    Notes
    -----
    A generated shim that cannot be written, e.g. ``numpy.pc`` when
    ``numpy`` is not importable, is reported through ``state.log.info``
    rather than treated as an error.  `OSError` from writing a file is
    propagated.
    """
    skipped = []
    pkgconfig.write_shims(os.path.join(root, pkgconfig.GENERATED_SHIM_SUBDIR), skipped=skipped)
    for message in skipped:
        state.log.info(f"{message}.")


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
        Accepted for backwards compatibility and ignored; SWIG support has
        been removed from sconsUtils.
    hasDoxygenInclude : `bool`, optional
        If True, the package provides a Doxygen include file with the
        name ``<root>/doc/<name>.inc``.
    hasDoxygenTag : `bool`, optional
        If True, the package generates a Doxygen TAG file.
    includeFileDirs : `collections.abc.Sequence`, optional
        List of directories that should be searched for include files.
    libFileDirs : `collections.abc.Sequence`, optional
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

    def __init__(
        self,
        cfgFile,
        headers=(),
        libs=None,
        hasSwigFiles=True,
        includeFileDirs=("include",),
        libFileDirs=("lib",),
        hasDoxygenInclude=False,
        hasDoxygenTag=True,
        eupsProduct=None,
    ):
        self.name, self.root = self.parseFilename(cfgFile)
        if eupsProduct is None:
            eupsProduct = self.name
        self.eupsProduct = eupsProduct
        version, productDir = self.getEupsData(self.eupsProduct)
        if version is not None:
            self.version = version
        if productDir is None:
            state.log.info(f"Could not find EUPS product dir for '{self.eupsProduct}'; using {self.root}.")
        else:
            self.root = os.path.realpath(productDir)
        self.doxygen = {
            # Doxygen tag files generated by this package
            "tags": ([os.path.join(self.root, "doc", f"{self.name}.tag")] if hasDoxygenTag else []),
            # Doxygen include files to include in the configuration of
            # dependent products
            "includes": ([os.path.join(self.root, "doc", f"{self.name}.inc")] if hasDoxygenInclude else []),
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

        for pathName, subDirs in [("CPPPATH", includeFileDirs), ("LIBPATH", libFileDirs)]:
            self.paths[pathName] = []

            if state.env.linkFarmDir:
                continue

            for subDir in subDirs:
                pathDir = os.path.join(self.root, subDir)
                if os.path.isdir(pathDir):
                    self.paths[pathName].append(pathDir)

        self.provides = {"headers": tuple(headers), "libs": tuple(self.libs["main"])}

    def configure(self, conf, packages, build=True):
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
        build : `bool`, optional
            If True, this is the package currently being built, and packages in
            "buildRequired" and "buildOptional" dependencies will also be
            present in the packages dict.
        """
        conf.env.PrependUnique(**self.paths)
        state.log.info(f"Configuring package '{self.name}'.")
        conf.env.doxygen["includes"].extend(self.doxygen["includes"])
        if not build:
            conf.env.doxygen["tags"].extend(self.doxygen["tags"])
        for target in self.libs:
            if target not in conf.env.libs:
                conf.env.libs[target] = self.libs[target].copy()
                state.log.info(f"Adding '{self.libs[target]}' libraries to target '{target}'.")
            else:
                for lib in self.libs[target]:
                    if lib not in conf.env.libs[target]:
                        conf.env.libs[target].append(lib)
                        state.log.info(f"Adding '{lib}' library to target '{target}'.")
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
        Configuration.__init__(
            self,
            cfgFile,
            headers,
            libs,
            eupsProduct=eupsProduct,
            hasSwigFiles=False,
            hasDoxygenTag=False,
            hasDoxygenInclude=False,
        )
        self.paths["XCPPPATH"] = self.paths["CPPPATH"]
        del self.paths["CPPPATH"]


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
        self._current = {primaryName}
        # The pkg-config runner used to synthesize configurations for
        # dependencies without a .cfg file; built on first use by
        # _pkgconfig(), which sets _pkgconfigFailed if that is impossible.
        self._pkgconfigInstance = None
        self._pkgconfigFailed = False
        if noCfgFile:
            self.primary = None
            return

        self.primary = self._tryImport(primaryName)
        if self.primary is None:
            state.log.fail(f"Failed to load primary package configuration for {primaryName}.")

        missingDeps = []
        for dependency in self.primary.dependencies.get("required", ()):
            if not self._recurse(dependency):
                missingDeps.append(dependency)
        if missingDeps:
            state.log.fail('Failed to load required dependencies: "%s"' % '", "'.join(missingDeps))

        missingDeps = []
        for dependency in self.primary.dependencies.get("buildRequired", ()):
            if not self._recurse(dependency):
                missingDeps.append(dependency)
        if missingDeps:
            state.log.fail('Failed to load required build dependencies: "%s"' % '", "'.join(missingDeps))

        for dependency in self.primary.dependencies.get("optional", ()):
            self._recurse(dependency)

        for dependency in self.primary.dependencies.get("buildOptional", ()):
            self._recurse(dependency)

    name = property(lambda self: self.primary.config.name)

    @property
    def versions(self):
        """Version of every dependency, keyed by package name
        (`dict` [`str`, `str` or `None`]).

        A dependency that was not found has a version of `None`, and one
        whose configuration does not record a version has ``"unknown"``.
        """
        return {
            name: (getattr(mod.config, "version", "unknown") if mod is not None else None)
            for name, mod in self.packages.items()
        }

    def configure(self, env):
        """Configure the entire dependency tree in order. and return an
        updated environment."""
        conf = env.Configure()
        for name, module in self.packages.items():
            if module is None:
                state.log.info(f"Skipping missing optional package {name}.")
                continue
            if not module.config.configure(conf, packages=self.packages, build=False):
                state.log.fail(f"{name} was found but did not pass configuration checks.")
        if self.primary:
            self.primary.config.configure(conf, packages=self.packages, build=True)
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

    def _pkgconfig(self):
        """Return the pkg-config runner used for dependencies without a
        .cfg file, constructing it on first use.

        Returns
        -------
        pkgconfig : `~lsst.sconsUtils.pkgconfig.PkgConfig` or `None`
            The runner, or `None` if it cannot be constructed (no conda
            prefix or no ``pkg-config`` executable).  The reason is logged
            once, and construction is not retried.

        Notes
        -----
        The configure-time shims are written into
        ``<build root>/.sconf_temp/pkgconfig`` before the runner is
        constructed, as on the pkg-config path, so that a converted
        dependency requiring e.g. ``numpy`` can be resolved.
        """
        if self._pkgconfigInstance is None and not self._pkgconfigFailed:
            root = SCons.Script.Dir("#").abspath
            try:
                _writeShims(root)
            except OSError as err:
                state.log.fail(str(err))
            searchPath = pkgconfig.build_search_path(root, os.environ)
            try:
                self._pkgconfigInstance = pkgconfig.PkgConfig(searchPath, get_conda_prefix())
            except pkgconfig.PkgConfigError as err:
                state.log.info(f"Not looking for pkg-config modules: {err}.")
                self._pkgconfigFailed = True
            else:
                state.log.info(f"Using pkg-config at '{self._pkgconfigInstance.executable}'.")
        return self._pkgconfigInstance

    def _tryImport(self, name):
        """Search for and import an individual configuration module from
        file.

        If no ``<name>.cfg`` file is found on the configuration path but
        pkg-config can find a ``lsst_<name>`` module, a configuration
        module is synthesized from pkg-config instead; see
        `~lsst.sconsUtils.pkgconfig.synthesize_cfg_module`.
        """
        for path in self.cfgPath:
            filename = os.path.join(path, name + ".cfg")
            if os.path.exists(filename):
                try:
                    # https://docs.python.org/3/library/importlib.html#importing-a-source-file-directly
                    # Need to specify SourceFileLoader since the files do not
                    # have a .py extension.
                    module_name = f"{name}_cfg"
                    loader = importlib.machinery.SourceFileLoader(module_name, filename)
                    spec = importlib.util.spec_from_file_location(
                        module_name, filename, submodule_search_locations=None, loader=loader
                    )
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                except Exception as e:
                    state.log.warn(f"Error loading configuration {filename} ({e})")
                    continue
                state.log.info(f"Using configuration for package '{name}' at '{filename}'.")
                if not hasattr(module, "dependencies") or not isinstance(module.dependencies, dict):
                    state.log.warn(f"Configuration module for package '{name}' lacks a dependencies dict.")
                    return None
                if not hasattr(module, "config") or not isinstance(module.config, Configuration):
                    state.log.warn(f"Configuration module for package '{name}' lacks a config object.")
                    return None
                return module
        runner = self._pkgconfig()
        moduleName = pkgconfig.module_name(name)
        # present() rather than exists(): a module whose Requires cannot be
        # satisfied is broken, not missing, and must not be skipped as an
        # absent optional dependency.
        if runner is not None and runner.present(moduleName):
            state.log.info(f"Using pkg-config module '{moduleName}' for package '{name}'.")
            try:
                return pkgconfig.synthesize_cfg_module(name, runner, get_conda_prefix())
            except pkgconfig.PkgConfigError as err:
                state.log.fail(str(err))
        state.log.info(f"Failed to import configuration for optional package '{name}'.")

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
            state.log.fail(f"Detected recursive dependency involving package '{name}'")
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
                state.log.warn(
                    f"Could not load all dependencies for package '{name}' (missing {dependency})."
                )
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
