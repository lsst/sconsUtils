##
#  @file dependencies.py
#
#  Dependency configuration and definition.
#
#  @defgroup sconsUtilsDependencies Dependencies and Configuration
#  @{
##

import os.path
import collections
import imp
import sys
import SCons.Script
import eups
from SCons.Script.SConscript import SConsEnvironment

from . import installation
from . import state

##
# @brief Recursively configure a package using ups/.cfg files.
#
# Aliased as lsst.sconsUtils.configure().
#
# Usually, LSST packages will call this function through scripts.BasicSConstruct.
#
# @param packageName       Name of the package being built; must correspond to a .cfg file in ups/.
# @param versionString     Version-control system string to be parsed for version information
#                          ($HeadURL$ for SVN).
# @param eupsProduct       Name of the EUPS product being built.  Defaults to and is almost always
#                          the name of the package.
# @param eupsProductPath   An alternate directory where the package should be installed.
#
# @return an SCons Environment object (which is also available as lsst.sconsUtils.env).
##
def configure(packageName, versionString=None, eupsProduct=None, eupsProductPath=None):
    if eupsProduct is None:
        eupsProduct = packageName
    state.env['eupsProduct'] = eupsProduct
    state.env['packageName'] = packageName
    #
    # Setup installation directories and variables
    #
    SCons.Script.Help(state.opts.GenerateHelpText(state.env))
    state.env.installing = filter(lambda t: t == "install", SCons.Script.BUILD_TARGETS) 
    state.env.declaring = filter(lambda t: t == "declare" or t == "current", SCons.Script.BUILD_TARGETS)
    prefix = installation.setPrefix(state.env, versionString, eupsProductPath)
    state.env['prefix'] = prefix
    state.env["libDir"] = "%s/lib" % prefix
    state.env["pythonDir"] = "%s/python" % prefix
    #
    # Process dependencies
    #
    state.log.traceback = state.env.GetOption("traceback")
    state.log.verbose = state.env.GetOption("verbose")
    packages = PackageTree(packageName)
    state.log.flush() # if we've already hit a fatal error, die now.
    state.env.libs = {"main":[], "python":[], "test":[]}
    state.env.doxygen = {"tags":[], "includes":[]}
    state.env['CPPPATH'] = []
    state.env['LIBPATH'] = []
    state.env['XCPPPATH'] = []
    state.env['_CPPINCFLAGS'] = \
        "$( ${_concat(INCPREFIX, CPPPATH, INCSUFFIX, __env__, RDirs, TARGET, SOURCE)}"\
        " ${_concat(INCPREFIX, XCPPPATH, INCSUFFIX, __env__, RDirs, TARGET, SOURCE)} $)"
    state.env['_SWIGINCFLAGS'] = state.env['_CPPINCFLAGS'].replace("CPPPATH", "SWIGPATH")
    if not state.env.GetOption("clean") and not state.env.GetOption("help"):
        packages.configure(state.env, check=state.env.GetOption("checkDependencies"))
        for target in state.env.libs:
            state.log.info("Libraries in target '%s': %s" % (target, state.env.libs[target]))
    state.env.dependencies = packages
    state.log.flush()

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

##
# @brief Base class for defining how to configure an LSST sconsUtils package.
#
# Aliased as lsst.sconsUtils.Configuration.
#
# An ups/*.cfg file should contain an instance of this class called
# "config".  Most LSST packages will be able to use this class directly
# instead of subclassing it.
#
# The only important method is configure(), which modifies an SCons
# environment to use the package.  If a subclass overrides configure,
# it may not need to call the base class __init__(), whose only
# purpose is to define a number of instance variables used by configure().
##
class Configuration(object):

    ## @brief Parse the name of a .cfg file, returning the package name and root directory.
    @staticmethod
    def parseFilename(cfgFile):
        dir, file = os.path.split(cfgFile)
        name, ext = os.path.splitext(file)
        return name, os.path.abspath(os.path.join(dir, ".."))

    ##
    # @brief Initialize the configuration object.
    #
    # @param cfgFile             The name of the calling .cfg file, usually just passed in with the special
    #                            variable __file__.  This will be parsed to extract the package name and
    #                            root.
    # @param headers             A list of headers provided by the package, to be used in autoconf-style
    #                            tests.
    # @param libs                A list or dictionary of libraries provided by the package.  If a dictionary
    #                            is provided, libs["main"] should contain a list of regular libraries
    #                            provided
    #                            by the library.  Other keys are "python" and "test", which refer to
    #                            libraries that are only linked against compiled Python modules and unit
    #                            tests, respectively.  If a list is provided, the list is used as "main".
    #                            These are used both for autoconf-style tests and to support
    #                            env.getLibs(...), which recursively computes the libraries a package
    #                            must be linked with.
    # @param hasSwigFiles        If True, the package provides SWIG interface files in "<root>/python".
    # @param hasDoxygenInclude   If True, the package provides a Doxygen include file with the
    #                            name "<root>/doc/<name>.inc".
    # @param hasDoxygenTag       If True, the package generates a Doxygen TAG file.
    # @param eupsProduct         Name of the EUPS product for the package, if different from the name of the
    #                            .cfg file.
    ##
    def __init__(self, cfgFile, headers=(), libs=None, hasSwigFiles=True,
                 hasDoxygenInclude=False, hasDoxygenTag=True, eupsProduct=None):
        self.name, self.root = self.parseFilename(cfgFile)
        if eupsProduct is None:
            eupsProduct = self.name
        self.eupsProduct = eupsProduct
        productDir = eups.productDir(self.eupsProduct)
        if productDir is None:
            state.log.warn("Could not find EUPS product dir for '%s'; using %s." 
                           % (self.eupsProduct, self.root))
        else:
            self.root = productDir
        self.paths = {
            # Sequence of include path for headers provided by this package
            "CPPPATH": [os.path.join(self.root, "include")],
            # Sequence of library path for libraries provided by this package
            "LIBPATH": [os.path.join(self.root, "lib")],
            # Sequence of SWIG include paths for .i files provided by this package
            "SWIGPATH": ([os.path.join(self.root, "python")]
                         if hasSwigFiles else [])
            }
        self.doxygen = {
            # Doxygen tag files generated by this package
            "tags": ([os.path.join(self.root, "doc", "%s.tag" % self.name)]
                     if hasDoxygenTag else []),
            # Doxygen include files to include in the configuration of dependent products
            "includes": ([os.path.join(self.root, "doc", "%s.inc" % self.name)]
                         if hasDoxygenInclude else [])
            }
        if libs is None:
            self.libs = {
                # Normal libraries provided by this package
                "main": [self.name],
                # Libraries provided that should only be linked with Python modules
                "python":[],
                # Libraries provided that should only be linked with unit test code
                "test":[],
                }
        elif "main" in libs:
            self.libs = libs
        else:
            self.libs = {"main": libs, "python": [], "test": []}
        self.provides = {
            "headers": tuple(headers),
            "libs": tuple(self.libs["main"])
            }

    ##
    # @brief Add custom SCons configuration tests to the Configure Context passed to the
    #        configure() method.
    #
    # This needs to be done up-front so we can pass in a dictionary of custom tests when
    # calling env.Configure(), and use the same configure context for all packages.
    #
    # @param tests     A dictionary to add custom tests to.  This will be passed as the
    #                  custom_tests argument to env.Configure().
    ##
    def addCustomTests(self, tests):
        pass
        
    ##
    # @brief Update an SCons environment to make use of the package.
    #
    # @param conf      An SCons Configure context.  The SCons Environment conf.env should be updated
    #                  by the configure function.
    # @param packages  A dictionary containing the configuration modules of all dependencies (or None if
    #                  the dependency was optional and was not found).  The <module>.config.configure(...)
    #                  method will have already been called on all dependencies.
    # @param check     If True, perform autoconf-style tests to verify that key components are in
    #                  fact in place.
    # @param build     If True, this is the package currently being built, and packages in
    #                  "buildRequired" and "buildOptional" dependencies will also be present in
    #                  the packages dict.
    ##
    def configure(self, conf, packages, check=False, build=True):
        assert(not (check and build))
        conf.env.PrependUnique(**self.paths)
        state.log.info("Configuring package '%s'." % self.name)
        conf.env.doxygen["includes"].extend(self.doxygen["includes"])
        if not build:
            conf.env.doxygen["tags"].extend(self.doxygen["tags"])
        for target in self.libs:
            if target not in conf.env.libs:
                conf.env.libs[target] = lib[target].copy()
                state.log.info("Adding '%s' libraries to target '%s'." % (self.libs[target], target))
            else:
                for lib in self.libs[target]:
                    if lib not in conf.env.libs[target]:
                        conf.env.libs[target].append(lib)
                        state.log.info("Adding '%s' library to target '%s'." % (lib, target))
        if check:
            for header in self.provides["headers"]:
                if not conf.CheckCXXHeader(header): return False
            for lib in self.libs["main"]:
                if not conf.CheckLib(lib, autoadd=False, language="C++"): return False
        return True

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

##
# @brief A Configuration subclass for external (third-party) packages.
#
# Aliased as lsst.sconsUtils.ExternalConfiguration.
#
# ExternalConfiguration doesn't assume the package uses SWIG or Doxygen,
# and tells SCons not to consider header files this package provides as dependencies.
#
# This means things SCons won't waste time looking for changes in it every time you build.
##
class ExternalConfiguration(Configuration):

    ##
    # @brief Initialize the configuration object.
    #
    # @param cfgFile  The name of the calling .cfg file, usually just passed in with the special
    #                 variable __file__.  This will be parsed to extract the package name and root.
    # @param headers  A list of headers provided by the package, to be used in autoconf-style tests.
    # @param libs     A list or dictionary of libraries provided by the package.  If a dictionary
    #                 is provided, libs["main"] should contain a list of regular libraries provided
    #                 by the library.  Other keys are "python" and "test", which refer to libraries
    #                 that are only linked against compiled Python modules and unit tests, respectively.
    #                 If a list is provided, the list is used as "main".  These are used both for
    #                 autoconf-style tests and to support env.getLibs(...), which recursively computes
    #                 the libraries a package must be linked with.
    ##
    def __init__(self, cfgFile, headers=(), libs=None):
        Configuration.__init__(self, cfgFile, headers, libs, hasSwigFiles=False,
                               hasDoxygenTag=False, hasDoxygenInclude=False)
        self.paths["XCPPPATH"] = self.paths["CPPPATH"]
        del self.paths["CPPPATH"]

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

##
# @brief A class for loading and managing the dependency tree of a package, as defined by its
#        configuration module (.cfg) file.
#
# This tree isn't actually stored as a tree; it's flattened into an ordered dictionary
# as it is recursively loaded.
#
# The main SCons produced by configure() and available as sconsUtils.env will contain
# an instance of this class as env.dependencies.
#
# Its can be used like a read-only dictionary to check whether an optional package has been
# configured; a package that was not found will have a value of None, while a configured
# package's value will be its imported .cfg module.
##
class PackageTree(object):
    
    ##
    # @brief Recursively load *.cfg files for packageName and all its dependencies.
    #
    # @param primaryName      The name of the primary package being built.
    #
    # After __init__, self.primary will be set to the configuration module for the primary package,
    # and self.packages will be an OrderedDict of dependencies (excluding self.primary), ordered
    # such that configuration can proceed in iteration order.
    ##
    def __init__(self, primaryName):
        self.upsDirs = state.env.upsDirs
        self.packages = collections.OrderedDict()
        self.customTests = {}
        self.primary = self._tryImport(primaryName)
        if self.primary is None: state.log.fail("Failed to load primary package configuration.")
        for dependency in self.primary.dependencies.get("required", ()):
            if not self._recurse(dependency): state.log.fail("Failed to load required dependencies.")
        for dependency in self.primary.dependencies.get("buildRequired", ()):
            if not self._recurse(dependency): state.log.fail("Failed to load required build dependencies.")
        for dependency in self.primary.dependencies.get("optional", ()):
            self._recurse(dependency)
        for dependency in self.primary.dependencies.get("buildOptional", ()):
            self._recurse(dependency)

    name = property(lambda self: self.primary.config.name)

    ## @brief Configure the entire dependency tree in order. and return an updated environment."""
    def configure(self, env, check=False):
        conf = env.Configure(custom_tests=self.customTests)
        for name, module in self.packages.iteritems():
            if module is None:
                state.log.info("Skipping missing optional package %s." % name)
                continue
            if not module.config.configure(conf, packages=self.packages, check=check, build=False):
                state.log.fail("%s was found but did not pass configuration checks." % name)
        self.primary.config.configure(conf, packages=self.packages, check=False, build=True)
        env.AppendUnique(SWIGPATH=env["CPPPATH"])
        env.AppendUnique(XSWIGPATH=env["XCPPPATH"])
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
        k = self.packages.keys()
        k.append(self.name)
        return k

    def _tryImport(self, name):
        """Search for and import an individual configuration module from file."""
        for path in self.upsDirs:
            filename = os.path.join(path, name + ".cfg")
            if os.path.exists(filename):
                state.log.info("Using configuration for package '%s' at '%s'." % (name, filename))
                module = imp.load_source(name + "_cfg", filename)
                if not hasattr(module, "dependencies") or not isinstance(module.dependencies, dict):
                    state.log.warn("Configuration module for package '%s' lacks a dependencies dict." % name)
                    return
                if not hasattr(module, "config") or not isinstance(module.config, Configuration):
                    state.log.warn("Configuration module for package '%s' lacks a config object." % name)
                    return
                else:
                    module.config.addCustomTests(self.customTests)
                return module
        state.log.warn("Failed to import configuration for package '%s'." % name)

    def _recurse(self, name):
        """Recursively load a dependency."""
        if name in self.packages:
            return self.packages[name] is not None
        module = self._tryImport(name)
        if module is None:
            self.packages[name] = None
            return False
        for dependency in module.dependencies.get("required", ()):
            if not self._recurse(dependency):
                # We can't configure this package because a required dependency wasn't found.
                # But this package might itself be optional, so we don't die yet.
                self.packages[name] = None
                state.log.warn("Could not load all dependencies for package '%s'." % name)
                return False
        for dependency in module.dependencies.get("optional", ()):
            self._recurse(dependency)
        # This comes last to ensure the ordering puts all dependencies first.
        self.packages[name] = module
        return True

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

##
# @brief Get the libraries the package should be linked with.
#
# @param categories   A string containing whitespace-delimited categories.  Standard
#                     categories are "main", "python", and "test".  Default is "main".
#                     A special virtual category "self" can be provided, returning
#                     the results of targets="main" with the env["packageName"] removed.
#
# Typically, main libraries will be linked with LIBS=getLibs("self"),
# Python modules will be linked with LIBS=getLibs("main python") and
# C++-coded test programs will be linked with LIBS=getLibs("main test").
# """
def getLibs(env, categories="main"):
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

## @}
