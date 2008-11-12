#
# Note that this file is called SConsUtils.py not SCons.py so as to allow us to import SCons
#
import glob
import os
import re
import shutil
from SCons.Script import *              # So that this file has the same namespace as SConstruct/SConscript
from SCons.Script.SConscript import SConsEnvironment
SCons.progress_display = SCons.Script.Main.progress_display
import stat
import sys
from types import *
import lsst.svn as svn

try:
    import eups
except ImportError:
    pass    

def MakeEnv(eups_product, versionString=None, dependencies=[],
            eups_product_path=None, options=None, traceback=False):
    """
    Setup a standard SCons environment, add our dependencies, and fix some
    os/x problems
    
    This function should be called early in a SConstruct file to initialize
    the build environment for the product being built.

    Identifying the Product

    The eups_product, versionString, and eups_product_path arguments are
    used to identify the product being built.  eups_product is the name that
    EUPS will know the product as; that is, this is the name one would provide
    to the EUPS setup command to load the product into the user's environment.
    Certain assumptions are made about the product based on this name and
    LSST conventions.  In particular,
    - if the product builds a linkable library, that library will be
      named after the product name.  For example, if eups_product='foo',
      the static library will be called libfoo.a.
    - Unless the eups_product_path is specified, it will be assumed that
      the default location for installing the product will be
      root/flavor/eups_product/version where root is the first directory 
      listed in $EUPS_PATH, flavor is the platform flavor name (e.g. Linux), 
      and version is the actual version of the product release (see below).

    This function will attempt to determine the version of the product being
    built from the value of the versionString.  This is a string that is
    generated automatically by the code repository/revisioning system; 
    currently supported systems are CVS and Subversion (SVN).  When the 
    SConstruct file is first created by the product developer, the 
    versionString argument is set to r'$HeadURL$' (for SVN) or r'$Name$' (for 
    CVS).  When the SConstruct file is subsequently checked out, the code
    repository system converts this into a value that encodes the release
    version of the product.  This function will automatically decode the
    versionString into a real version number.

    The eups_product_path argument is the path to the default directory for
    installing the product relative.  The value can be parameterized with
    with printf-like directives.  For example, when eups_product_path is
    not set, the install path is equivalent to:
    @verbatim
        "%P/%f/%p/%v"
    @endverbatim
    where the %-sequences are replaced as follows:
    @verbatim
        %P     the first directory in the EUPS_PATH environment variable
        %f     the platform flavor (e.g. Linux, Darwin, etc.)
        %p     the product name (e.g. fw, mwi)
        %v     the product version
        %c     the current working directory
    @endverbatim
    Of course, the path can be explicitly specified without using any
    %-sequences.  The most common use, however is to insert additional
    directories into the path; for example:
    @verbatim
        "%P/%f/deploy/%p/%v"
    @endverbatim
    
    Describing Dependencies

    The dependencies argument allows you to describe how this product depends
    on other products.  Our SCons scripts will use this information to actually
    check that the required components are visible to the build process before
    actually proceeding with the build.  The dependencies argument is a list
    of lists.  That is, it is a list in which each element describes a
    dependency on another product; that dependency is described with a list of
    up to 4 elements:

    @verbatim
      0.  the EUPS name of the dependent product.  It is assumed that the
          user has already loaded the product into the environment via the
          EUPS setup command (i.e. "setup product") so that there is an
          environment variable, product_DIR, that provides the directory where
          the product is installed. 
      
      1.  the name of one or more required include files, the last of which
          being one that the product should provide.
          If more than one file is given, they can be provided either as a 
          Python list or a space-delimited string.  As part of its verification,
          SCons will attempt use the last include file listed in a test
          compilation.  The preceding include files in the list are assumed
          to be required to successfully compile the last one.  If file
          successfully compiles, it is assumed that all other include files
          needed from the product will also be available.
          
      2.  the name of one or more required libraries, the last of which being
          one that the product should provide.
          If more than one file is given, they can be provided either as a 
          Python list or a space-delimited string.  As part of its verification,
          SCons will attempt to link against the last library in a test
          compilation.  Sometimes it is necessary to indicate the language
          support required; if so, the last library should by appended with
          ':lang' where lang is the language (e.g. C++, C); the default
          language is C.  

      3.  the name of a symbol (e.g. a function name) from the required library
          given in the element 2.  The test compilation and link will test to
          make sure that this symbol can be found during the linking stage.  If
          this is successful, it is assumed that all other symbols from all
          required libraries from the product will be available.
    @endverbatim

    The latter elements of a dependency description are optional.  If less
    information is provided, less is done in terms of verification.  Generally,
    a symbol will need to be provided to verify that a required library is
    usable.  Note, however, that for certain special products, specific checks
    are carried out to ensure that the product is in a useable state; thus,
    providing a library name without a symbol is often still useful. 
    
    @param eups_product   the name of this product (as it is to be known as
                             by EUPS) that is being built.  See "Identifying
                             the Product" above for a discussion of how this
                             is used.  
    @param versionString  a string provided by the code repository identifying
                             the version of the product being built.  When 
                             using Subversion (SVN), this is initially set to
                             r"$HeadURL$"; when the SConstruct file is checked
                             out of SVN, this value will be changed to a string
                             encoding the release version of the product.  If
                             not provided, the release version will be set to
                             unknown.  See "Identifying the Product" above for 
                             more details.
    @param dependencies   a description of dependencies on other products
                             needed to build this product that should be
                             verified.  The value is a list with each element 
                             describing the dependency on another product.
                             Each dependency is described with a list of up to
                             four elements.  See "Describing Dependencies"
                             above for an explanation of the dependency
                             description.
    @param eups_product_path  the relative path to the default installation
                             directory as format string.  Use this if the
                             product should be installed in a subdirectory
                             relative to $EUPS_PATH.  See "Identifying the
                             Product" above for more details.
    @param options        an Options object to use to define command-line
                             options custom to the current build script.
                             If provided, this should have been created with
                             LsstOptions()
    @param traceback      a boolean switch indicating whether any uncaught 
                             Python exceptions raised during the build process
                             should result in a standard Python traceback
                             message to be displayed.  The default, False,
                             causes tracebacks not to be printed; only the
                             error message will be printed.
    """
    #
    # We don't usually want a traceback at the interactive prompt
    # XXX This hook appears to be ignored by scons. Why?
    #
    if not traceback:
        def my_excepthook(type, value, tb):
            print >> sys.stderr, "Error:", value
            sys.exit(1)
        sys.excepthook = my_excepthook
    #
    # Argument handling
    #
    opts = options
    if opts is None:
        opts = LsstOptions()
        
    opts.AddOptions(
        BoolOption('debug', 'Set to enable debugging flags', True),
        ('eupsdb', 'Specify which element of EUPS_PATH should be used', None),
        ('flavor', 'Set the build flavor', None),
        BoolOption('force', 'Set to force possibly dangerous behaviours', False),
        ('optfile', 'Specify a file to read default options from', None),
        ('prefix', 'Specify the install destination', None),
        EnumOption('opt', 'Set the optimisation level', 0, allowed_values=('0', '1', '2', '3')),
        EnumOption('profile', 'Compile/link for profiler', 0, allowed_values=('0', '1', 'pg')),
        BoolOption('setenv', 'Treat arguments such as Foo=bar as defining construction variables', False),
        ('version', 'Specify the current version', None),
        )

    products = []
    for productProps in dependencies:
        products += [productProps[0]]
    products.sort()

    for p in products:
        dir = ProductDir(p)
        opts.AddOptions(
            PathOption(p, "Specify the location of %s" % p, dir),
            PathOption(p + "Include", "Specify the location of %s's include files" % p,
                       dir and os.path.isdir(dir + "/include") and dir + "/include" or None),
            PathOption(p + "Lib", "Specify the location of %s's libraries" % p,
                       dir and os.path.isdir(dir + "/lib") and dir + "/lib" or None),
            )

    toolpath = []
    if os.path.exists("python/lsst/SConsUtils.py"): # boostrapping sconsUtils
        toolpath += ["python/lsst"]
    elif os.environ.has_key('SCONSUTILS_DIR'):
        toolpath += ["%s/python/lsst" % os.environ['SCONSUTILS_DIR']]

    if os.environ.has_key('LD_LIBRARY_PATH'):
        LD_LIBRARY_PATH = os.environ['LD_LIBRARY_PATH']
    else:
        LD_LIBRARY_PATH = None
        
    if os.environ.has_key('DYLD_LIBRARY_PATH'):
        DYLD_LIBRARY_PATH = os.environ['DYLD_LIBRARY_PATH']
    else:
        DYLD_LIBRARY_PATH = None

    if os.environ.has_key('SHELL'):     # needed by eups
        SHELL = os.environ['SHELL']
    else:
        SHELL = None
        
    ourEnv = {'EUPS_DIR' : os.environ['EUPS_DIR'],
              'EUPS_PATH' : os.environ['EUPS_PATH'],
              'PATH' : os.environ['PATH'],
              'DYLD_LIBRARY_PATH' : DYLD_LIBRARY_PATH,
              'LD_LIBRARY_PATH' : LD_LIBRARY_PATH,
              'SHELL' : SHELL,
              }
    # Add all EUPS directories
    for k in filter(lambda x: re.search(r"_DIR$", x), os.environ.keys()):
        p = re.search(r"^(.*)_DIR$", k).groups()[0]
        varname = eups.Product(None, p, noInit=True).envarSetupName()
        if os.environ.has_key(varname):
            ourEnv[varname] = os.environ[varname]
            ourEnv[k] = os.environ[k]

    env = Environment(ENV = ourEnv, options = opts,
		      tools = ["default", "doxygen"],
		      toolpath = toolpath
		      )
    env['eups_product'] = eups_product
    Help(opts.GenerateHelpText(env))

    env.libs = {}
    env.libs[eups_product] = [eups_product]; # Assume that this product has a library of the same name
    #
    # SCons gets confused about shareable/static objects if
    # you specify libraries as e.g. "#libwcs.a", but it's OK
    # if you say LIBS = ["wcs"].
    #
    if False:
        env['STATIC_AND_SHARED_OBJECTS_ARE_THE_SAME'] = True
    #
    # We don't want "lib" inserted at the beginning of loadable module names;
    # we'll import them under their given names.
    #
    env['LDMODULEPREFIX'] = ""

    if env['PLATFORM'] == 'darwin':
        env['LDMODULESUFFIX'] = ".so"

        if not re.search(r"-install_name", str(env['SHLINKFLAGS'])):
            env.Append(SHLINKFLAGS = "-Wl,-install_name -Wl,${TARGET.file}")
        
    #
    # Remove valid options from the arguments
    #
    for opt in opts.keys():
        try:
            del ARGUMENTS[opt]
        except KeyError:
            pass
    #
    # Process those arguments
    #
    if env['debug']:
        env.Append(CCFLAGS = '-g')

    eups_path = None
    try:
        db = env['eupsdb']
        if not os.environ.has_key('EUPS_PATH'):
            msg = "You can't use eupsdb=XXX without an EUPS_PATH set"
            if traceback:
                raise RuntimeError, msg
            else:
                sys.excepthook(RuntimeError, msg, None)

        eups_path = None
        for d in os.environ['EUPS_PATH'].split(':'):
            if re.search(r"/%s$|^%s/|/%s/" % (db, db, db), d):
                eups_path = d
                break

        if not eups_path:
            msg = "I cannot find DB \"%s\" in $EUPS_PATH" % db
            if traceback:
                raise RuntimeError, msg
            else:
                sys.excepthook(RuntimeError, msg, None)
    except KeyError:
        if os.environ.has_key('EUPS_PATH'):
            eups_path = os.environ['EUPS_PATH'].split(':')[0]

    env['eups_path'] = eups_path

    try:
        env['PLATFORM'] = env['flavor']
        del env['flavor']
    except KeyError:
        pass
    #
    # Check arguments
    #
    errors = []
    errorStr = ""
    #
    # Process otherwise unknown arguments.  If setenv is true,
    # set construction variables; otherwise generate an error
    #
    if env['setenv']:
        for key in ARGUMENTS.keys():
            env[key] = ARGUMENTS[key]
    else:
        for key in ARGUMENTS.keys():
            errorStr += " %s=%s" % (key, ARGUMENTS[key])
        if errorStr:
            errors += ["Unprocessed arguments:%s" % errorStr]
    #
    # We need a binary name, not just "Posix"
    #
    try:
        env['eups_flavor'] = eups.flavor()
    except:
        print >> sys.stderr, "Unable to import eups; guessing flavor"
        if env['PLATFORM'] == "posix":
            env['eups_flavor'] = os.uname()[0].title()
        else:
            env['eups_flavor'] = env['PLATFORM'].title()

    #
    # Where to install
    #
    env.installing = filter(lambda t: t == "install", BUILD_TARGETS)# are we installing?

    prefix = setPrefix(env, versionString, eups_product_path)
    env['prefix'] = prefix
    
    env["libDir"] = "%s/lib" % prefix
    env["pythonDir"] = "%s/python" % prefix

    if env.installing:
        SCons.progress_display("Installing into %s" % (prefix))
    #
    # Is the C compiler really gcc/g++?
    #
    def IsGcc(context):
        context.Message("Checking if  CC is really gcc...")
        result = context.TryAction(["%s --help | grep gcc" % env['CC']])[0]
        context.Result(result)
        return result

    if env.GetOption("clean"):
        isGcc = False                   # who cares? We're cleaning, not building
    else:
        conf = Configure(env, custom_tests = {'IsGcc' : IsGcc})
        isGcc = conf.IsGcc()
        conf.Finish()
    #
    # Compiler flags; CCFLAGS => C and C++
    #
    if isGcc:
        env.Append(CCFLAGS = '-Wall')
    if env['opt']:
        env.Append(CCFLAGS = '-O%d' % int(env['opt']))
    if env['profile'] == '1' or env['profile'] == "pg":
        env.Append(CCFLAGS = '-pg')
        env.Append(LINKFLAGS = '-pg')
    #
    # scons 0.97 doesn't support these. Sigh
    #
    try:
        env.GetOption("silent")
    except SCons.Errors.UserError:      # 0.97
        SCons.Script.Main.ssoptions.settable["no_exec"] = SCons.Script.Main.options.noexec
        SCons.Script.Main.ssoptions.settable["help"] = SCons.Script.Main.options.help_msg
        SCons.Script.Main.ssoptions.settable["silent"] = SCons.Script.Main.options.no_progress
    #
    # Is C++'s TR1 available?  If not, use e.g. #include "lsst/tr1/foo.h"
    #
    if not env.GetOption("clean"):
        if not env.GetOption("no_exec"):
            conf = env.Configure()
            env.Append(CCFLAGS = '-DLSST_HAVE_TR1=%d' % int(conf.CheckHeader("tr1/unordered_map", language="C++")))
            conf.Finish()
    #
    # Byte order
    #
    import socket
    if socket.htons(1) != 1:
        env.Append(CCFLAGS = '-DLSST_LITTLE_ENDIAN=1')
    #
    # Check for dependencies in swig input files
    #
    env.SwigDependencies();
    #
    # If we're linking to libraries that themselves linked to
    # shareable libraries we need to do something special.
    if (re.search(r"^(Linux|Linux64)$", env["eups_flavor"]) and 
        os.environ.has_key("LD_LIBRARY_PATH")):
        env.Append(LINKFLAGS = "-Wl,-rpath-link -Wl,%s" % \
                   os.environ["LD_LIBRARY_PATH"])
    #
    # Process dependencies
    #
    if dependencies:
        for productProps in dependencies:
            product = productProps[0]
            if not env.libs.has_key(product):
                env.libs[product] = []

    env['CPPPATH'] = []
    env['LIBPATH'] = []
    if not env.GetOption("clean") and not env.GetOption("help") and dependencies:
        for productProps in dependencies:
            while len(productProps) < 4:     # allow the user to omit values
                productProps += [""]
            if len(productProps) > 4:
                print >> sys.stderr, "Ignoring extra values while configuring %s: %s" % \
                      (productProps[0], " ".join(productProps[4:]))

            (product, incfiles, libs, symbol) = productProps[0:4]
            #
            # Special case python itself
            #
            if product == "python":
                env.CheckPython()
            #
            # Did they specify a directory on the command line? We accept:
            #   product{,Lib,Include}=DIR
            #
            (topdir, incdir, libdir) = searchEnvForDirs(env, product)
            #
            # See if pkgconfig knows about us.  ParseConfig sets values in env for us
            #
            if not ProductDir(product): # don't override EUPS
                try:
                    env.PkgConfigEUPS(product)
                    pkgConfig = True
                except OSError:
                    pkgConfig = False
            #
            # Get things from the arguments (now pushed into env by Environment(..., opts=...));
            # the default values came from EUPS if available
            #
            if topdir:
                success = True          # they said they knew what was going on.  If they didn't
                                        # specify incfiles/libs, we'll have to trust them
                if product == "pycore":
                    import numpy
                    incdir = numpy.get_include()

                if incfiles:
                    try:
                        if env.CheckHeaderGuessLanguage(incdir, incfiles) and incdir:
                            env.Replace(CPPPATH = env['CPPPATH'] + [incdir])
                    except RuntimeError, msg:
                        errors += [str(msg)]
                        success = False
                        
                if not env.GetOption("no_exec") and libs:
                    conf = env.Clone(LIBPATH = env['LIBPATH'] + [libdir]).Configure()
                    try:
                        libs, lang = libs.split(":")
                    except ValueError:
                        lang = "C"

                    libs = Split(libs)
                    for lib in libs[:-1]:
                        # Allow for boost messing with library names. Sigh.
                        lib = mangleLibraryName(env, libdir, lib)
                        
                        if conf.CheckLib(lib, language=lang):
                            env.libs[product] += [lib]
                        else:
                            errors += ["Failed to find/use %s library" % (lib)]
                            success = False

                    lib = mangleLibraryName(env, libdir, libs[-1])
                        
                    if conf.CheckLib(lib, symbol, language=lang):
                        if libdir not in env['LIBPATH']:
                            env.Replace(LIBPATH = env['LIBPATH'] + [libdir])
                            Repository(libdir)                        
                    else:
                        errors += ["Failed to find/use %s library in %s" % (lib, libdir)]
                        success = False
                    conf.Finish()

                    env.libs[product] += [lib]

                if success:
                    continue
            elif incfiles or libs:       # Not specified; see if we got lucky in the environment
                success = True
                
                if incfiles:
                    try:
                        if incdir and env.CheckHeaderGuessLanguage(incdir, incfiles):
                            env.Replace(CPPPATH = env['CPPPATH'] + [incdir])
                    except RuntimeError, msg:
                        errors += [str(msg)]
                        success = False

                if libs:
                    conf = env.Configure()
                    for lib in Split(libs):
                        try:
                            lib, lang = lib.split(":")
                        except ValueError:
                            lang = "C"

                        lib = mangleLibraryName(env, libdir, lib)

                        if conf.CheckLib(lib, symbol, language=lang):
                            env.libs[product] += [lib]
                        else:
                            success = False
                    conf.Finish()

                if success:
                    continue
            elif pkgConfig:
                continue                # We'll trust them here too; they did provide a pkg-config script
            else:
                pass                    # what can we do? No PRODUCT_DIR, no product-config,
                                        # no include file to find

            if topdir:
                errors += ["Failed to find a valid version of %s --- check config.log" % (product)]
            else:
                errors += ["Failed to find a valid %s --- do you need to setup %s or specify %s=DIR?" % \
                           (product, product, product)]
        
    if errors:
        msg = "\n".join(errors)
        if traceback:
            raise RuntimeError, msg
        else:
            sys.excepthook(RuntimeError, msg, None)
    #
    # Include TOPLEVEL/include while searching for .h files;
    # include TOPLEVEL/lib while searching for libraries
    #
    for d in ["include"]:
        if os.path.isdir(d):
            env.Append(CPPPATH = Dir(d))
    if os.path.isdir("lib"):
	env.Append(LIBPATH = Dir("lib"))
    #
    Export('env')
    #
    # env.Glob is an scons >= 0.98 way of asking if a target (will) exist
    #
    try:
        env.Glob                        # >= 0.98
    except AttributeError, e:
        def _Glob(*args):
            return ["dummy"]
        env.Glob = _Glob

    return env

makeEnv = MakeEnv                       # backwards compatibility

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def LsstOptions(files=None):
    """@brief Create an Options object using LSST conventions.

    The SCons Options object is used in the LSST build system to define
    variables that can be used on the command line or loaded in from a file.
    These variables given as "name=value" arguments on the scons command line or
    listed, one per line, in a separate file.  An options file can be specified
    on the scons command line with the "optfile" variable (e.g.
    "optfile=myoptions.py").  If optfile is not specified, scons will look for
    a file called "buildOpts.py" by default.  (You can specify additional
    option files to load via the "files" argument to this constructor.)  If the
    user provides any command-line variable options that has not been defined
    via an Options instance, scons will exit with an error, complaining about
    an unused argument.  

    To define your custom variable options, you should create an Options object
    with this constructor function \e prior to the use of scons.makeEnv.
    Then you can use the standard Options member functions (Add() or 
    AddOptions()) to define your variable options (see the
    @link http://www.scons.org/doc/0.97/HTML/scons-man.html the SCons Man
    page for details).  For example,
    @code
       opts = scons.LsstOptions()
       opts.Add('pkgsurl', 'the base url for the software server',
                'http://dev.lsstcorp.org/pkgs')
    @endcode
    In this example, we defined a new options called "pkgsurl" with a default
    value of "http://dev.lsstcorp.org/pkgs".  The second argument is a help
    string.

    To actually use these options, you must load them into the environment
    by passing it to the scons.makeEnv() function via its options argument:
    @code
       env = scons.makeEnv("mypackage", "$HeadURL$", options=opts)
    @endcode
    scons.makeEnv() will automatically look for these options on the command
    line as well as any option files.  The values found their will be loaded
    into the environment's dictionary (i.e. accessible via evn[optionname]).

    Note that makeEnv() will internally add additional options to the Options
    object you pass it, overriding your definitions where you have used the
    same name.  These standard options include:
    @verbatim
        debug     Set to > 1 to enable debugging flag (default: 0)
        eupsdb    Specify which element of EUPS_PATH should be used (default:
                    the value of $EUPS_PATH)
        flavor    the desired build flavor (default is auto-detected)
        optfile   a file to read default options from (default:
                    buildOpts.py)
        prefix    the install destination directory (default is auto-detected
                    from the EUPS environment).
        opt       the optimization level, an integer between 0 and 3, inclusive
                    (default: 0)
        version   Specify the current version (default is auto-detected)
    @endverbatim    
    
    This constructor should be preferred over the standard SCons Options
    constructor because it defines various LSST conventions.  In particular,
    it defines the default name an options file to look for.  It will also
    print a warning message if any specified options file (other than the
    default) cannot be found.

    @param files    one or more names of option files to look for.  Multiple
                       names must be given as a python list.
    """
    if files is None:
        files = []
    elif type(files) is not ListType:
        files = [files]

    if ARGUMENTS.has_key("optfile"):
        configfile = ARGUMENTS["optfile"]
        if configfile not in files:
            files.append(configfile)

    for file in files:
        if not os.path.isfile(file):
            print >> sys.stderr, \
                     "Warning: Will ignore non-existent options file, %s" \
                     % file

    if not ARGUMENTS.has_key("optfile"):
        files.append("buildOpts.py")

    return Options(files)
    

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def CheckHeaderGuessLanguage(self, incdir, incfiles):
    """Like CheckHeader, but guess the proper language"""

    incfiles = Split(incfiles)
    
    if re.search(r"\.h$", incfiles[-1]):
	# put C++ first; if the first language fails then the scons
	# cache seems to have trouble.  Besides, most C++ will compile as C
        languages = ["C++", "C"]
    elif re.search(r"\.hpp$", incfiles[-1]):
        languages = ["C++"]
    else:
        raise RuntimeError, "Unknown header file suffix for file %s" % (incfiles[-1])

    if self.GetOption("no_exec"):
        return False
    
    for lang in languages:
        conf = self.Clone(CPPPATH = self['CPPPATH'] + [incdir]).Configure()
        foundHeader = conf.CheckHeader(incfiles, language=lang)
        conf.Finish()

        if foundHeader:
            if incdir in self['CPPPATH']:
                return False            # no need for another copy
            else:
                return True

    if os.path.isfile(os.path.join(incdir, incfiles[-1])):
        raise RuntimeError, "Failed to compile test program using %s" % os.path.join(incdir, incfiles[-1])
    else:
        raise RuntimeError, "Failed to find %s in %s" % (incfiles[-1], incdir)

SConsEnvironment.CheckHeaderGuessLanguage = CheckHeaderGuessLanguage

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def getlibs(env, *products):
    """Return a list of all the libraries needed by products named in the list;
    each element may be a string on names ("aa bb cc"). If the name isn't recognised
    it's taken to be a library name"""
    
    libs = []
    for lib in products:
        for l in Split(lib):
            if env.libs.has_key(l):
                libs += env.libs[l]
            else:
                libs += [l]

    if True:                            # make each library apply only once
        _libdict = {}
        _libs = libs
        libs = []
        for l in _libs:
            if not _libdict.has_key(l):
                _libdict[l] = 1
                libs += [l]

    return libs

SConsEnvironment.getlibs = getlibs

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

class ParseBoostLibrary(object):
    def __init__(self, shlibprefix, library, shlibsuffix, blib):
        """Parse a boost library name, given the prefix (often "lib"),
        the library name (e.g. "boost_regexp"), the suffix (e.g. "so")
        and the actual name of the library

        Taken from libboost-doc/HTML/more/getting_started.html
        """

        self.toolset, threading, runtime = None, None, None # parts of boost library name
        self.libversion = None

        mat = re.search(r"^%s%s-?(.+)%s" % (shlibprefix, library, shlibsuffix), blib)
        self.libname = library
        if mat:
            self.libname += "-" + mat.groups()[0]

            opts = mat.groups()[0].split("-")
            opts, self.libversion = opts[0:-1], opts[-1]

            if opts:
                if len(opts) == 2:
                    if opts[0] == "mt":
                        threading = opts[0]
                    else:
                        self.toolset = opts[0]

                    opts = opts[1:]
                elif len(opts) == 3:
                    threading = opts[0]
                    self.toolset = opts[1]

                    opts = opts[2:]

                runtime = opts[0]

        self.threaded = threading and threading == "mt"

        self.static_runtime =     runtime and re.search("s", runtime)
        self.debug_runtime =      runtime and re.search("g", runtime)
        self.debug_python =       runtime and re.search("y", runtime)
        self.debug_code =         runtime and re.search("d", runtime)
        self.stlport_runtime =    runtime and re.search("p", runtime)
        self.stlport_io_runtime = runtime and re.search("n", runtime)

        return

def mangleLibraryName(env, libdir, lib):
    """If lib's a boost library, choose the right one; there may be a number to choose from"""

    if not libdir:       # we don't know libdir, so we can't poke around
        return lib

    if not re.search(r"^boost", lib):
        return lib
    
    shlibprefix = env['SHLIBPREFIX']
    if re.search(r"^\$", shlibprefix) and env.has_key(shlibprefix[1:]):
        shlibprefix = env[shlibprefix[1:]]
    shlibsuffix = env['SHLIBSUFFIX']

    libs = glob.glob(os.path.join(libdir, shlibprefix + lib + "*" + shlibsuffix))

    blibs = {}
    for blib in libs:
        blibs[blib] = ParseBoostLibrary(shlibprefix, lib, shlibsuffix,
                                        os.path.basename(blib))

    if len(blibs) == 0: # nothing clever to do
        return lib
    elif len(blibs) == 1: # only one choice
        lib = blibs.values()[0].libname
    else:           # more than one choice
        if env['debug']:
            for blib in blibs:
                if not blibs[blib].debug_code:
                    del blibs[blib]
                    break

        if len(blibs) == 1:             # only one choice
            lib = blibs.values()[0].libname
        else:                           # How do we choose? Take the shortest
            lib = None
            for blib in blibs.values():
                if not lib or len(blib.libname) < lmin:
                    lib = blib.libname
                    lmin = len(lib)

    return lib            

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def searchArgumentsForDirs(ARGUMENTS, product):
    """If product, productInclude, or productLib is set in ARGUMENTS,
    return a triple of all three values, and delete the ARGUMENTS"""
    product_include = product + "Include"
    product_lib = product + "Lib"
    #
    # Set ARGUMENTS[product] if either of product-{include,lib} is set
    #
    if ARGUMENTS.has_key(product):
        topdir = ARGUMENTS[product]
        del ARGUMENTS[product]          # it's a legal argument
    elif ARGUMENTS.has_key(product_include) or ARGUMENTS.has_key(product_lib):
        if ARGUMENTS.has_key(product_include):
            topdir = os.path.split(re.sub("/$", "", ARGUMENTS[product_include]))[0]
            if ARGUMENTS.has_key(product_lib):
                topdir2 = os.path.split(re.sub("/$", "", ARGUMENTS[product_lib]))[0]
                if topdir != topdir2:
                    print >> sys.stderr, ("Warning: Ignoring second guess for %s directory: " +
                                          "%s, %s") % (product, topdir, topdir2)
        elif ARGUMENTS.has_key(product_lib):
            topdir = os.path.split(re.sub("/$", "", ARGUMENTS[product_lib]))[0]
    else:
        return (None, None, None)
    #
    # Now make sure that all three variables are set
    #
    if ARGUMENTS.has_key(product_include):
        incdir = "%s" % ARGUMENTS[product_include]
        del ARGUMENTS[product_include] # it's a legal argument
    else:
        incdir = "%s/include" % topdir

    if ARGUMENTS.has_key(product_lib):
        libdir = "%s" % ARGUMENTS[product_lib]
        del ARGUMENTS[product_lib] # it's a legal argument
    else:
        libdir = "%s/lib" % topdir

    return (topdir, incdir, libdir)

def searchEnvForDirs(env, product):
    """If product, productInclude, or productLib is set in env,
    return a triple of all three values"""
    product_include = product + "Include"
    product_lib = product + "Lib"
    #
    ARGUMENTS = {}
    for k in [product, product_include, product_lib]:
        try:
            ARGUMENTS[k] = env[k]
        except KeyError:
            pass

    return searchArgumentsForDirs(ARGUMENTS, product)

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def SharedLibraryIncomplete(self, target, source, **keywords):
    """Like SharedLibrary, but don't insist that all symbols are resolved"""

    myenv = self.Clone()

    if myenv['PLATFORM'] == 'darwin':
        myenv['SHLINKFLAGS'] += " -undefined suppress -flat_namespace"

    return myenv.SharedLibrary(target, source, **keywords)

SConsEnvironment.SharedLibraryIncomplete = SharedLibraryIncomplete


def LoadableModuleIncomplete(self, target, source, **keywords):
    """Like LoadableModule, but don't insist that all symbols are resolved"""

    myenv = self.Clone()
    if myenv['PLATFORM'] == 'darwin':
        myenv['LDMODULEFLAGS'] += " -undefined suppress -flat_namespace"

    return myenv.LoadableModule(target, source, **keywords)

SConsEnvironment.LoadableModuleIncomplete = LoadableModuleIncomplete

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
#
# My reimplementation of installFunc that accepts a regexp of files to ignore
#
def copytree(src, dst, symlinks=False, ignore = None):
    """Recursively copy a directory tree using copy2().

    The destination directory must not already exist.
    If exception(s) occur, an Error is raised with a list of reasons.

    If the optional symlinks flag is true, symbolic links in the
    source tree result in symbolic links in the destination tree; if
    it is false, the contents of the files pointed to by symbolic
    links are copied.

    If the optional ignore option is present, treat it as a
    regular expression and do NOT copy files that match the pattern

    XXX Consider this example code rather than the ultimate tool.

    """

    last_component = os.path.split(src)[-1]
    if ignore and re.search(ignore, last_component):
        #print "Ignoring", last_component
        return

    names = os.listdir(src)
    os.mkdir(dst)
    errors = []
    for name in names:
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)

        if ignore and re.search(ignore, srcname):
            #print "Ignoring", srcname
            continue

        try:
            if symlinks and os.path.islink(srcname):
                linkto = os.readlink(srcname)
                os.symlink(linkto, dstname)
            elif os.path.isdir(srcname):
                copytree(srcname, dstname, symlinks, ignore)
            else:
                shutil.copy2(srcname, dstname)
            # XXX What about devices, sockets etc.?
        except (IOError, os.error), why:
            errors.append((srcname, dstname, why))
    if errors:
        raise Error, errors

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def ProductDir(product):
    """Return a product's PRODUCT_DIR, or None"""
    product_dir = product.upper() + "_DIR"

    if os.environ.has_key(product_dir):
        return os.environ[product_dir]
    else:
        return None

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def _ProductDir(self, product):
    return ProductDir(product)

SConsEnvironment.ProductDir = _ProductDir
    
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def makeProductPath(pathFormat, env):
    """return a path to use as the installation directory for a product
    @param pathFormat     the format string to process 
    @param env            the scons environment
    @param versionString  the versionString passed to MakeEnv
    """
    pathFormat = re.sub(r"%(\w)", r"%(\1)s", pathFormat)
    
    eups_path = os.environ['PWD']
    if env.has_key('eups_product') and env['eups_path']:
        eups_path = env['eups_path']

    return pathFormat % { "P": eups_path,
                          "f": env['eups_flavor'],
                          "p": env['eups_product'],
                          "v": env['version'],
                          "c": os.environ['PWD'] }
    
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def getVersion(env, versionString):
    """Set a version ID from env, or
    a cvs or svn ID string (dollar name dollar or dollar HeadURL dollar)"""

    version = "unknown"

    if env.has_key('version'):
        version = env['version']
    elif not versionString:
        version = "unknown"
    elif re.search(r"^[$]Name:\s+", versionString):
        # CVS.  Extract the tagname
        version = re.search(r"^[$]Name:\s+([^ $]*)", versionString).group(1)
        if version == "":
            version = "cvs"
    elif re.search(r"^[$]HeadURL:\s+", versionString):
        # SVN.  Guess the tagname from the last part of the directory
        HeadURL = re.search(r"^[$]HeadURL:\s+(.*)", versionString).group(1)
        HeadURL = os.path.split(HeadURL)[0]
        if env.installing:
            try:
                version = svn.guessVersionName(HeadURL)
            except RuntimeError, e:
                if env['force']:
                    version = "unknown"
                else:
                    print >> sys.stderr, \
                          "%s\nFound problem with svn revision number; update or specify force=True to proceed" %e
                    sys.exit(1)

    env["version"] = version
    return version

def setPrefix(env, versionString, eups_product_path=None):
    """Set a prefix based on the EUPS_PATH, the product name, and a versionString from cvs or svn"""

    if eups_product_path:
        getVersion(env, versionString)
        eups_prefix = makeProductPath(eups_product_path, env)
        
    elif env.has_key('eups_path') and env['eups_path']:
        eups_prefix = env['eups_path']
	flavor = env['eups_flavor']
	if not re.search("/" + flavor + "$", eups_prefix):
	    eups_prefix = os.path.join(eups_prefix, flavor)

        prodpath = env['eups_product']
        if env.has_key('eups_product_path') and env['eups_product_path']:
            prodpath = env['eups_product_path']

        eups_prefix = os.path.join(eups_prefix, prodpath,
				   getVersion(env, versionString))
    else:
        eups_prefix = None

    if env.has_key('prefix'):
        if eups_prefix:
            print >> sys.stderr, "Ignoring prefix %s from EUPS_PATH" % eups_prefix

        return env['prefix']
    elif env.has_key('eups_path') and env['eups_path']:
        prefix = eups_prefix
    else:
        prefix = "/usr/local"

    return prefix

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=
#
# Don't use these in new code --- they date from before RHL learnt about GetOption()
#
def CleanFlagIsSet(self):
    """Return True iff they're running "scons --clean" """

    return self.GetOption("clean")

SConsEnvironment.CleanFlagIsSet = CleanFlagIsSet

def HelpFlagIsSet(self):
    """Return True iff they're running "scons --help" """

    return self.GetOption("help")

SConsEnvironment.HelpFlagIsSet = HelpFlagIsSet

def NoexecFlagIsSet(self):
    """Return True iff they're running "scons -n" """

    return self.GetOption("no_exec")

SConsEnvironment.NoexecFlagIsSet = NoexecFlagIsSet

def QuietFlagIsSet(self):
    """Return True iff they're running "scons -Q" """

    return self.GetOption("silent")
    
SConsEnvironment.QuietFlagIsSet = QuietFlagIsSet

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def Declare(self, products=None):
    """Create current and declare targets for products.  products
    may be a list of (product, version) tuples.  If product is None
    it's taken to be self['eups_product']; if version is None it's
    taken to be self['version'].
    
    We'll add Declare to class Environment"""

    if "undeclare" in COMMAND_LINE_TARGETS and not self.GetOption("silent"):
        print >> sys.stderr, "'scons undeclare' is deprecated; please use 'scons declare -c' instead"

    if \
           "declare" in COMMAND_LINE_TARGETS or \
           "undeclare" in COMMAND_LINE_TARGETS or \
           ("install" in COMMAND_LINE_TARGETS and self.GetOption("clean")) or \
           "current" in COMMAND_LINE_TARGETS:
        current = []; declare = []; undeclare = []

        if not products:
            products = [None]

        for prod in products:
            if not prod or isinstance(prod, str):   # i.e. no version
                product = prod

                if self.has_key('version'):
                    version = self['version']
                else:
                    version = None
            else:
                product, version = prod

            if not product:
                product = self['eups_product']

            if "EUPS_DIR" in os.environ.keys():
                self['ENV']['PATH'] += os.pathsep + "%s/bin" % (os.environ["EUPS_DIR"])

                if "undeclare" in COMMAND_LINE_TARGETS or self.GetOption("clean"):
                    if version:
                        command = "eups undeclare --flavor %s %s %s" % \
                                  (self['eups_flavor'], product, version)
                        if "current" in COMMAND_LINE_TARGETS and not "declare" in COMMAND_LINE_TARGETS:
                            command += " --current"
                            
                        if self.GetOption("clean"):
                            self.Execute(command)
                        else:
                            undeclare += [command]
                    else:
                        print >> sys.stderr, "I don't know your version; not undeclaring to eups"
                else:
                    command = "eups declare --force --flavor %s --root %s" % \
                              (self['eups_flavor'], self['prefix'])

                    if self.has_key('eups_path'):
                        command += " -Z %s" % self['eups_path']
                        
                    if version:
                        command += " %s %s" % (product, version)

                    current += [command + " --current"]
                    declare += [command]

        if current:
            self.Command("current", "", action=current)
        if declare:
            if "current" in COMMAND_LINE_TARGETS:
                self.Command("declare", "", action="") # current will declare it for us
            else:
                self.Command("declare", "", action=declare)
        if undeclare:
            self.Command("undeclare", "", action=undeclare)
                
SConsEnvironment.Declare = Declare

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def CleanTree(files, dir=".", recurse=True, verbose=False):
    """Remove files matching the argument list starting at dir
    when scons is invoked with -c/--clean and no explicit targets are listed
    
    E.g. CleanTree(r"*~ core")

    If recurse is True, recursively descend the file system; if
    verbose is True, print each filename after deleting it
    """
    #
    # Generate command that we may want to execute
    #
    files_expr = ""
    for file in Split(files):
        if files_expr:
            files_expr += " -o "

        files_expr += "-name %s" % re.sub(r"(^|[^\\])([[*])", r"\1\\\2",file) # quote unquoted * and []
    #
    # don't use xargs --- who knows what needs quoting?
    #
    action = "find %s" % dir
    action += r" \( -name .sconf_temp -prune -o -name .svn -prune -o -name \* \) "
    if not recurse:
        action += " ! -name . -prune"

    file_action = "rm -f"

    action += r" \( %s \) -exec %s {} \;" % \
        (files_expr, file_action)

    if verbose:
        action += " -print"
    #
    # Do we actually want to clean up?  We don't if the command is e.g. "scons -c install"
    #
    if "clean" in COMMAND_LINE_TARGETS:
        Command("clean", "", action=action)
    elif not COMMAND_LINE_TARGETS and GetOption("clean"):
        Execute(Action([action]))

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def InstallEups(env, dest, files=[], presetup=""):
    """Install a ups directory, setting absolute versions as appropriate
    (unless you're installing from the trunk, in which case no versions
    are expanded).  Any build/table files present in "./ups" are automatically
    added to files.
    
    If presetup is provided, it's expected to be a dictionary with keys
    product names and values the version that should be installed into
    the table files, overriding eups expandtable's usual behaviour. E.g.
env.InstallEups(os.path.join(env['prefix'], "ups"), presetup={"sconsUtils" : env['version']})
    """

    if not env.installing:
        return

    if env.GetOption("clean"):
        print >> sys.stderr, "Removing", dest
        shutil.rmtree(dest, ignore_errors=True)
    else:
        presetupStr = []
        for p in presetup:
            presetupStr += ["--product %s=%s" % (p, presetup[p])]
        presetup = " ".join(presetupStr)

        env = env.Clone(ENV = os.environ)
        #
        # Add any build/table files to the desired files
        #
        files += glob.glob(os.path.join("ups", "*.build")) + glob.glob(os.path.join("ups","*.table"))
        files = list(set(files))        # remove duplicates

        buildFiles = filter(lambda f: re.search(r"\.build$", f), files)
        build_obj = env.Install(dest, buildFiles)
        
        tableFiles = filter(lambda f: re.search(r"\.table$", f), files)
        table_obj = env.Install(dest, tableFiles)

        miscFiles = filter(lambda f: not re.search(r"\.(build|table)$", f), files)
        misc_obj = env.Install(dest, miscFiles)

        for i in build_obj:
            env.AlwaysBuild(i)

            cmd = "eups expandbuild -i --version %s %s" % (env['version'], str(i))
            env.AddPostAction(i, Action("%s" %(cmd), cmd, ENV = os.environ))

        for i in table_obj:
            env.AlwaysBuild(i)

            cmd = "eups expandtable -i "
            if presetup:
                cmd += presetup + " "
            cmd += str(i)

            env.AddPostAction(i, Action("%s" %(cmd), cmd, ENV = os.environ))

    return dest

SConsEnvironment.InstallEups = InstallEups

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def PkgConfigEUPS(self, product, function=None, unique=1):
    """Load pkg-config options into the environment. Look for packages in
    PRODUCT_DIR, if they're not in the path, and suppress error messages
    about failing to find config files"""
    
    try:
        self.ParseConfig('%s-config --cflags --libs 2> /dev/null' % product)
        #print "pkg %s succeeded" % product
    except OSError:
        try:
            self.ParseConfig('env PKG_CONFIG_PATH=%s/etc pkg-config %s --cflags --libs 2> /dev/null' % \
                             (ProductDir(product), product))
            #print "pkg %s succeeded from EUPS" % product
        except OSError:
            #print "pkg %s failed" % product
            raise OSError, "Failed to find config file for %s" % product
    #
    # Strip flags that we don't want added
    #
    for k in ['CCFLAGS', 'LINKFLAGS']:
        new = []
        for flag in self[k]:
            if isinstance(flag, tuple):
                if flag[0] == "-arch":
                    continue
            new += [flag]    
        self[k] = new

SConsEnvironment.PkgConfigEUPS = PkgConfigEUPS

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def CheckPython(self):
    """Attempt to auto-detect Python"""

    import distutils.sysconfig

    if not self.has_key('CPPPATH'):
        self['CPPPATH'] = []

    cpppath = []
    for d in (self['CPPPATH'] + distutils.sysconfig.get_python_inc().split()):
        if not d in cpppath:
            cpppath += [d]
        
    self.Replace(CPPPATH = cpppath)

    if self.has_key('LIBPATH'):
        libpath = self['LIBPATH']
    else:
        libpath = []
    pylibs = []

    dir = distutils.sysconfig.get_config_var("LIBPL")
    if not dir in libpath:
        libpath += [dir]
    pylibrary = distutils.sysconfig.get_config_var("LIBRARY")
    mat = re.search("(python.*)\.(a|so|dylib)$", pylibrary)
    if mat:
        pylibs += [mat.group(1)]
        
    for w in (" ".join([distutils.sysconfig.get_config_var("MODLIBS"),
                        distutils.sysconfig.get_config_var("SHLIBS")])).split():
        mat = re.search(r"^-([Ll])(.*)", w)
        if mat:
            lL = mat.group(1)
            arg = mat.group(2)
            if lL == "l":
                if not arg in pylibs:
                    pylibs += [arg]
            else:
                if os.path.isdir(arg) and not arg in libpath:
                    libpath += [arg]

    self.Replace(LIBPATH = libpath)
    try:
        type(self.libs)
    except AttributeError:
        self.libs = {}
        
    self.libs["python"] = pylibs

SConsEnvironment.CheckPython = CheckPython

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def CheckSwig(self, language="python", ilang="C", ignoreWarnings=None,
              includedProducts=[], swigdir=None):
    """Adjust the construction environment to allow the use of swig;
    if swigdir is specified it's the path to the swig binary, otherwise
    the calling process' PATH is searched.  Bindings are generated for
    LANGUAGE (e.g. "python") using implementation language ilang (e.g. "c")

    ignoreWarnings is a list of swig warnings to ignore (e.g. "317,362,389");
    either a python list, or a space separated string
    """
    
    if not swigdir:
        for d in os.environ['PATH'].split(os.pathsep):
            if os.path.isfile(os.path.join(d, "swig")):
                swigdir = d
                break

    if not swigdir:
        raise RuntimeError, "Failed to find swig executable"

    if swigdir not in self['ENV']['PATH'].split(os.pathsep):
        self['ENV']['PATH'] = swigdir + os.pathsep + self['ENV']['PATH']

    swigTool = Tool('swig'); swigTool(self)
    self['SWIGFLAGS'] = ""
    if ilang == "c" or ilang == "C":
        pass
    elif ilang == "c++" or ilang == "C++":
        self['SWIGFLAGS'] += " -c++"
    else:
        print >> sys.stderr, "Unknown input language %s" % ilang
        
    self['SWIGFLAGS'] += " -%s" % language

    if ignoreWarnings:
        self['SWIGFLAGS'] += " -w" + ",".join(Split(ignoreWarnings))    
    #
    # Allow swig to search all directories that the compiler sees
    #
    for d in self['CPPPATH']:
        if d:
            d = Dir(d)
            d = r"\ ".join(re.split(r" ", str(d))) # handle spaces in filenames
            self['SWIGFLAGS'] += " -I%s" % d
    #
    # Also search the python directories of any products in includedProducts
    #
    for p in Split(includedProducts):
        pd = ProductDir(p)
        if pd:
            self['SWIGFLAGS'] += " -I%s" % os.path.join(pd, "python")
        else:
            print >> sys.stderr, "Product %s is not setup" % p
        
SConsEnvironment.CheckSwig = CheckSwig

#
# Teach scons about swig included dependencies
#
# From http://www.scons.org/wiki/SwigBuilder
#
SWIGScanner = SCons.Scanner.ClassicCPP(
    "SWIGScan",
    ".i",
    "CPPPATH",
    '^[ \t]*[%,#][ \t]*(?:include|import)[ \t]*(<|")([^>"]+)(>|")'
    )

def SwigDependencies(self):
    # Prepend, as scons has already inserted a [poor] scanner for swig
    # if swig was found on PATH
    self.Prepend(SCANNERS=[SWIGScanner])
    
SConsEnvironment.SwigDependencies = SwigDependencies

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

if False:
    # Here's a way to cache other information if we want to e.g. save
    # the configured include files -- the TryAction could save the
    # paths to a file [I think]
    #
    # As the cached tests don't seem to take any time, we're not using this
    def CheckEups(self, product):
        self.Message("Checking %s ... " % product)
        self.TryAction("echo XX %s" % product)
        ret = True
        self.Result(ret)

        return ret

    conf = env.Configure( custom_tests = { 'CheckEups' : CheckEups } )
    conf.CheckEups("numpy")
    conf.Finish()

# See if a program supports a given flag
if False:
    def CheckOption(context, prog, flag):
        context.Message('Checking for option %s to %s... ' % (flag, prog))
        result = context.TryAction(["%s %s" % (prog, flag)])[0]
        context.Result(result)
        return result

    env = Environment()
    conf = Configure(env, custom_tests = {'CheckOption' : CheckOption})
    if not conf.CheckOption("gcc", "-Wall"):
        print "Can't find flag"
    env = conf.Finish()
    
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def filesToTag(root=".", file_regexp=r"^[a-zA-Z0-9_].*\.(cc|h(pp)?|py)$", ignoreDirs=["examples", "tests"]):
    """Return a list of files that need to be scanned for tags, starting at directory root

    Files are chosen if they match file_regexp; toplevel directories in list ignoreDirs are ignored

    Unless force is true, this routine won't do anything unless you specified a "TAGS" target
    """

    if len(filter(lambda t: t == "TAGS", COMMAND_LINE_TARGETS)) == 0:
        return []

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath == ".":
            dirnames[:] = [d for d in dirnames if not re.search(r"^(%s)$" % "|".join(ignoreDirs), d)]

        dirnames[:] = [d for d in dirnames if not re.search(r"^(\.svn)$", d)] # ignore .svn tree
        #
        # List of possible files to tag, but there's some cleanup required for machine-generated files
        #
        candidates = [f for f in filenames if re.search(file_regexp, f)]
        #
        # Remove files generated by swig
        #
        for swigFile in [f for f in filenames if re.search(r"\.i$", f)]:
            name = os.path.splitext(swigFile)[0]
            candidates = [f for f in candidates if not re.search(r"%s(_wrap\.cc?|\.py)$" % name, f)]

        files += [os.path.join(dirpath, f) for f in candidates]

    return files

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def InstallDir(self, prefix, dir, ignoreRegexp = r"(~$|\.pyc$|\.os?$)", recursive=True):
    """
    Install the directory dir into prefix, (along with all its descendents if recursive is True).
    Omit files and directories that match ignoreRegexp

    Unless force is true, this routine won't do anything unless you specified an "install" target
    """

    if not self.installing:
        return

    targets = []
    for dirpath, dirnames, filenames in os.walk(dir):
        if not recursive:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames if d != ".svn"] # ignore .svn tree
        #
        # List of possible files to install
        #
        for f in filenames:
            if re.search(ignoreRegexp, f):
                continue

            targets += self.Install(os.path.join(prefix, dirpath), os.path.join(dirpath, f))

    return targets

SConsEnvironment.InstallDir = InstallDir

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def InstallLSST(self, prefix, dirs):
    """Install directories in the usual LSST way, handling "doc" and "ups" specially"""
    
    for d in dirs:
        if d == "doc":
            t = self.InstallAs(os.path.join(prefix, "doc", "doxygen"), os.path.join("doc", "htmlDir"))
        elif d == "ups":
            t = self.InstallEups(os.path.join(prefix, "ups"))
        else:
            t = self.InstallDir(prefix, d)

        self.Alias("install", t)
            
    self.Clean("install", prefix)

SConsEnvironment.InstallLSST = InstallLSST
