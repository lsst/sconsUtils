#
# Note that this file is called SConsUtils.py not SCons.py so as to allow us to import SCons
#
import glob
import os
import re
import shutil
from SCons.Script import *
from SCons.Script.SConscript import SConsEnvironment
SCons.progress_display = SCons.Script.Main.progress_display
import stat
import sys

from . import svn
from . import hg
from . import configure
from . import utils

try:
    import eups
except ImportError:
    pass

def MakeEnv(packageName, versionString=None, eupsProduct=None, eupsProductPath=None, variables=None):
    """
    Setup a standard SCons environment, add our dependencies, and fix some
    os/x problems
    
    This function should be called early in a SConstruct file to initialize
    the build environment for the product being built.

    Identifying the Product

    The eupsProduct, versionString, and eupsProductPath arguments are
    used to identify the product being built.  eupsProduct is the name that
    EUPS will know the product as; that is, this is the name one would provide
    to the EUPS setup command to load the product into the user's environment.
    Certain assumptions are made about the product based on this name and
    LSST conventions.  In particular,
    - if the product builds a linkable library, that library will be
      named after the product name.  For example, if eupsProduct='foo',
      the static library will be called libfoo.a.
    - Unless the eupsProductPath is specified, it will be assumed that
      the default location for installing the product will be
      root/flavor/eupsProduct/version where root is the first directory 
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

    The eupsProductPath argument is the path to the default directory for
    installing the product relative.  The value can be parameterized with
    with printf-like directives.  For example, when eupsProductPath is
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
    
    @param eupsProduct   the name of this product (as it is to be known as
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
    @param eupsProductPath  the relative path to the default installation
                             directory as format string.  Use this if the
                             product should be installed in a subdirectory
                             relative to $EUPS_PATH.  See "Identifying the
                             Product" above for more details.
    @param variables       a Variables object to use to define command-line
                             options custom to the current build script.
                             If provided, this should have been created with
                             LsstVariables()
    """
    # TODO: fix docstring once signature stabilizes.
    EnsureSConsVersion(2, 1, 0)

    #
    # Argument handling
    #
    opts = variables
    if opts is None:
        opts = LsstVariables()

    AddOption('--checkProducts', dest='checkDependencies', action='store_true', default=False,
              help="Verify dependencies with autoconf-style tests.")
    # These options were originally settable as variables; but this way is easier/more idiomatic
    AddOption('--filterWarn', dest='filterWarn', action='store_true', default=False,
              help="Filter out a class of warnings deemed irrelevant"),
    AddOption('--force', dest='force', action='store_true', default=False,
              help="Set to force possibly dangerous behaviours")
    AddOption('--prefix', dest='prefix', action='store', default=False,
              help="Specify the install destination")
    AddOption('--setenv', dest='setenv', action='store_true', default=False,
              help="Treat arguments such as Foo=bar as defining construction variables")
    AddOption('--verbose', dest='verbose', action='store_true', default=False,
              help="Print additional information when configuring dependencies and setting up environment.")
    AddOption('--traceback', dest='traceback', action='store_true', default=False,
              help="Print full exception tracebacks when errors occur.")

    opts.AddVariables(
        ('archflags', 'Extra architecture specification to add to CC/LINK flags (e.g. -m32)', ''),
        ('cc', 'Choose the compiler to use', ''),
        BoolVariable('debug', 'Set to enable debugging flags (use --debug)', True),
        ('eupsdb', 'Specify which element of EUPS_PATH should be used', None),
        ('flavor', 'Set the build flavor', None),
        BoolVariable('force', 'Set to force possibly dangerous behaviours', False),
        ('optfile', 'Specify a file to read default options from', None),
        ('prefix', 'Specify the install destination', None),
        EnumVariable('opt', 'Set the optimisation level', 0, allowed_values=('0', '1', '2', '3')),
        EnumVariable('profile', 'Compile/link for profiler', 0, allowed_values=('0', '1', 'pg', 'gcov')),
        ('version', 'Specify the current version', None),
        ('baseversion', 'Specify the current base version', None),
        ('optFiles', "Specify a list of files that SHOULD be optimized", None),
        ('noOptFiles', "Specify a list of files that should NOT be optimized", None)
        )
        
    ourEnv = {
        'EUPS_DIR' : os.environ.get("EUPS_DIR"),
        'EUPS_PATH' : os.environ.get("EUPS_PATH"),
        'PATH' : os.environ.get("PATH"),
        'DYLD_LIBRARY_PATH' : os.environ.get("DYLD_LIBRARY_PATH"),
        'LD_LIBRARY_PATH' : os.environ.get("LD_LIBRARY_PATH"),
        'SHELL' : os.environ.get("SHELL"), # needed by eups
        'TMPDIR' : os.environ.get("TMPDIR"), # needed by eups
        }
    # Add all EUPS directories
    upsDirs = []
    for k in filter(lambda x: re.search(r"_DIR$", x), os.environ.keys()):
        p = re.search(r"^(.*)_DIR$", k).groups()[0]
        try:
            varname = eups.utils.setupEnvNameFor(p)
        except AttributeError:
            varname = "SETUP_" + p      # We're running an old (<= 1.2) version of eups
        if os.environ.has_key(varname):
            ourEnv[varname] = os.environ[varname]
            ourEnv[k] = os.environ[k]
            upsDirs.append(os.path.join(os.environ[k], "ups"))
    
    toolpath = [os.path.dirname(__file__)]

    #
    # Add any values marked as export=FOO=XXX[,GOO=YYY] to ourEnv
    #
    opt = "export"
    if ARGUMENTS.has_key(opt):
        for kv in ARGUMENTS[opt].split(','):
            k, v = kv.split('=')
            ourEnv[k] = v

        del ARGUMENTS[opt]

    env = Environment(ENV = ourEnv, variables=opts,
		      tools = ["default", "doxygen"],
		      toolpath = toolpath
		      )
    env0 = env.Clone()
    
    if eupsProduct is None:
        eupsProduct = packageName

    env['eupsProduct'] = eupsProduct
    env['packageName'] = packageName
    Help(opts.GenerateHelpText(env))

    #
    # We don't want "lib" inserted at the beginning of loadable module names;
    # we'll import them under their given names.
    #
    env['LDMODULEPREFIX'] = ""

    if env['PLATFORM'] == 'darwin':
        env['LDMODULESUFFIX'] = ".so"

        if not re.search(r"-install_name", str(env['SHLINKFLAGS'])):
            env.Append(SHLINKFLAGS = ["-Wl,-install_name", "-Wl,${TARGET.file}"])
        
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
    for k in ("force", "prefix"):       # these may now be set as options instead of variables
        if GetOption(k):
            env[k] = GetOption(k)
        
    if env['debug']:
        env.Append(CCFLAGS = ['-g'])

    checkDependencies = GetOption('checkDependencies')

    eupsPath = None
    try:
        db = env['eupsdb']
        if not os.environ.has_key('EUPS_PATH'):
            raise RuntimeError("You can't use eupsdb=XXX without an EUPS_PATH set")
        eupsPath = None
        for d in os.environ['EUPS_PATH'].split(':'):
            if re.search(r"/%s$|^%s/|/%s/" % (db, db, db), d):
                eupsPath = d
                break
        if not eupsPath:
            raise RuntimeError("I cannot find DB \"%s\" in $EUPS_PATH" % db)
    except KeyError:
        if os.environ.has_key('EUPS_PATH'):
            eupsPath = os.environ['EUPS_PATH'].split(':')[0]

    env['eupsPath'] = eupsPath

    try:
        env['PLATFORM'] = env['flavor']
        del env['flavor']
    except KeyError:
        pass
    #
    # Check arguments
    #
    errorStr = ""
    #
    # Process otherwise unknown arguments.  If setenv is true,
    # set construction variables; otherwise generate an error
    #
    if GetOption("setenv"):
        for key in ARGUMENTS.keys():
            env[key] = Split(ARGUMENTS[key])
    else:
        for key in ARGUMENTS.keys():
            errorStr += " %s=%s" % (key, ARGUMENTS[key])
        if errorStr:
            utils.log.fail("Unprocessed arguments:%s" % errorStr)
    #
    # We need a binary name, not just "Posix"
    #
    try:
        env['eupsFlavor'] = eups.flavor()
    except:
        print >> sys.stderr, "Unable to import eups; guessing flavor"
        if env['PLATFORM'] == "posix":
            env['eupsFlavor'] = os.uname()[0].title()
        else:
            env['eupsFlavor'] = env['PLATFORM'].title()

    #
    # Where to install
    #
    env.installing = filter(lambda t: t == "install", BUILD_TARGETS) # are we installing?
    env.declaring = filter(lambda t: t == "declare" or t == "current", BUILD_TARGETS) # are we declaring?

    prefix = setPrefix(env, versionString, eupsProductPath)
    env['prefix'] = prefix

    env["libDir"] = "%s/lib" % prefix
    env["pythonDir"] = "%s/python" % prefix

    if env.installing:
        SCons.progress_display("Installing into %s" % prefix)
    #
    # Is the C compiler really gcc/g++?
    #
    def ClassifyCc(context):
        """Return a string identifing the compiler in use"""
        versionStrings = {"Free Software Foundation" : "gcc",
                          "Intel Corporation" : "icc",
                          "Apple clang version" : "clang"
                          }
        context.Message("Checking who built the CC compiler...")
        for string, key in versionStrings.items():
            action = r"$CC --version | grep '%s' > $TARGET" % string
            result = context.TryAction(Action(action))
            if result[0]:
                context.Result(key)
                return key
        return "unknown"

    if env.GetOption("clean") or env.GetOption("no_exec") or env.GetOption("help") :
        env.whichCc = "unknown"         # who cares? We're cleaning/not execing, not building
    else:
        if env['cc'] != '':
            CC = CXX = None

            if re.search(r"^gcc(-\d+(\.\d+)*)?( |$)", env['cc']):
                CC = env['cc']
                CXX = re.sub(r"^gcc", "g++", CC)
            elif re.search(r"^icc( |$)", env['cc']):
                CC = env['cc']
                CXX = re.sub(r"^icc", "icpc", CC)
            elif re.search(r"^clang( |$)", env['cc']):
                CC = env['cc']
                CXX = re.sub(r"^clang", "clang++", CC)
            else:
                utils.log.fail("Unrecognised compiler:%s" % env['cc'])

            if CC and env['CC'] == env0['CC']:
                env['CC'] = CC
            if CC and env['CXX'] == env0['CXX']:
                env['CXX'] = CXX

        conf = env.Configure(custom_tests = {'ClassifyCc' : ClassifyCc})
        env.whichCc = conf.ClassifyCc()
        conf.Finish()
    #
    # Compiler flags; CCFLAGS => C and C++
    #
    ARCHFLAGS = os.environ.get("ARCHFLAGS", env.get('archflags'))
    if ARCHFLAGS:
        env.Append(CCFLAGS = [ARCHFLAGS])
        env.Append(LINKFLAGS = [ARCHFLAGS])

    # We'll add warning and optimisation options last
    if env['profile'] == '1' or env['profile'] == "pg":
        env.Append(CCFLAGS = ['-pg'])
        env.Append(LINKFLAGS = ['-pg'])
    elif env['profile'] == 'gcov':
        env.Append(CCFLAGS = '--coverage')
        env.Append(LINKFLAGS = '--coverage')

    env.GetOption("silent")
    #
    # Is C++'s TR1 available?  If not, use e.g. #include "lsst/tr1/foo.h"
    #
    if not (env.GetOption("clean") or env.GetOption("help") or env.GetOption("no_exec")):
        conf = env.Configure()
        env.Append(CCFLAGS = ['-DLSST_HAVE_TR1=%d' % int(conf.CheckCXXHeader("tr1/unordered_map"))])
        conf.Finish()
    #
    # Byte order
    #
    import socket
    if socket.htons(1) != 1:
        env.Append(CCFLAGS = ['-DLSST_LITTLE_ENDIAN=1'])

    #
    # If we're linking to libraries that themselves linked to
    # shareable libraries we need to do something special.
    if (re.search(r"^(Linux|Linux64)$", env["eupsFlavor"]) and os.environ.has_key("LD_LIBRARY_PATH")):
        env.Append(LINKFLAGS = ["-Wl,-rpath-link"])
        env.Append(LINKFLAGS = ["-Wl,%s" % os.environ["LD_LIBRARY_PATH"]])

    #
    # Process dependencies
    #
    utils.log.traceback = env.GetOption("traceback")
    utils.log.verbose = env.GetOption("verbose")
    packages = configure.Tree(packageName, upsDirs)
    utils.log.finish() # if we've already hit a fatal error, die now.
    env.libs = {"main":[], "python":[], "test":[]}
    env.doxygen = {"tags":[], "includes":[]}
    env['CPPPATH'] = []
    env['LIBPATH'] = []
    if not env.GetOption("clean") and not env.GetOption("help"):
        packages.configure(env, check=checkDependencies)
        for target in env.libs:
            utils.log.info("Libraries in target '%s': %s" % (target, env.libs[target]))
        
    if env['opt']:
        env["CCFLAGS"] = [o for o in env["CCFLAGS"] if not re.search(r"^-O(\d|s)$", o)]
        env.MergeFlags('-O%d' % int(env['opt']))

    if env.whichCc == "clang":
        env.Append(CCFLAGS = ['-Wall'])
        env.Append(CCFLAGS = ['-Wno-char-subscripts']) # seems innocous enough, and is used by boost

        ignoreWarnings = {
            "unused-function" : 'boost::regex has functions in anon namespaces in headers',
            }

        if GetOption('filterWarn'):
            env.Append(CCFLAGS = ["-Wno-%s" % (",".join([str(k) for k in ignoreWarnings.keys()]))])
    elif env.whichCc == "gcc":
        env.Append(CCFLAGS = ['-Wall'])
    elif env.whichCc == "icc":
        env.Append(CCFLAGS = ['-Wall'])

        ignoreWarnings = {
            21 : 'type qualifiers are meaningless in this declaration',
            68 : 'integer conversion resulted in a change of sign',
            111 : 'statement is unreachable',
            191 : 'type qualifier is meaningless on cast type',
            193 : 'zero used for undefined preprocessing identifier "SYMB"',
            279 : 'controlling expression is constant',
            304 : 'access control not specified ("public" by default)', # comes from boost
            383 : 'value copied to temporary, reference to temporary used',
            #424 : 'Extra ";" ignored',
            444 : 'destructor for base class "CLASS" is not virtual',
            981 : 'operands are evaluated in unspecified order',
            1418 : 'external function definition with no prior declaration',
            1419 : 'external declaration in primary source file',
            1572 : 'floating-point equality and inequality comparisons are unreliable',
            1720 : 'function "FUNC" has no corresponding member operator delete (to be called if an exception is thrown during initialization of an allocated object)',
            2259 : 'non-pointer conversion from "int" to "float" may lose significant bits',
            }

        if GetOption('filterWarn'):
            env.Append(CCFLAGS = ["-wd%s" % (",".join([str(k) for k in ignoreWarnings.keys()]))])
        # Workaround intel bug; cf. RHL's intel bug report 580167
        env.Append(LINKFLAGS = ["-Wl,-no_compact_unwind", "-wd,11015"])

    utils.log.finish()

    Export('env')
    return env

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def LsstVariables(files=None):
    """@brief Create a Variables object using LSST conventions.

    The SCons Variables object is used in the LSST build system to define
    variables that can be used on the command line or loaded in from a file.
    These variables given as "name=value" arguments on the scons command line or
    listed, one per line, in a separate file.  An variables file can be specified
    on the scons command line with the "optfile" variable (e.g. "optfile=myoptions.py";
    "variables" used to be called "options").  If optfile is not specified, scons will look for
    a file called "buildOpts.py" by default.  (You can specify additional
    option files to load via the "files" argument to this constructor.)  If the
    user provides any command-line variable options that has not been defined
    via an Variables instance, scons will exit with an error, complaining about
    an unused argument.  

    To define your custom variable options, you should create an Variables object
    with this constructor function \e prior to the use of scons.makeEnv.
    Then you can use the standard Variables member functions (Add() or 
    AddVariables()) to define your variable options (see
    @link http://www.scons.org/doc/HTML/scons-man.html the SCons Man
    page for details).  For example,
    @code
       opts = scons.LsstVariables()
       opts.Add('pkgsurl', 'the base url for the software server',
                'http://dev.lsstcorp.org/pkgs')
    @endcode
    In this example, we defined a new options called "pkgsurl" with a default
    value of "http://dev.lsstcorp.org/pkgs".  The second argument is a help
    string.

    To actually use these options, you must load them into the environment
    by passing it to the scons.makeEnv() function via its variables argument:
    @code
       env = scons.makeEnv("mypackage", "$HeadURL$", variables=opts)
    @endcode
    scons.makeEnv() will automatically look for these options on the command
    line as well as any option files.  The values found their will be loaded
    into the environment's dictionary (i.e. accessible via env[optionname]).

    Note that makeEnv() will internally add additional options to the Variables
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
    
    This constructor should be preferred over the standard SCons Variables
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

    return Variables(files)

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def SharedLibraryIncomplete(self, target, source, **keywords):
    """Like SharedLibrary, but don't insist that all symbols are resolved"""

    myenv = self.Clone()

    if myenv['PLATFORM'] == 'darwin':
        myenv['SHLINKFLAGS'] += ["-undefined", "suppress", "-flat_namespace"]

    return myenv.SharedLibrary(target, source, **keywords)

SConsEnvironment.SharedLibraryIncomplete = SharedLibraryIncomplete

def LoadableModuleIncomplete(self, target, source, **keywords):
    """Like LoadableModule, but don't insist that all symbols are resolved"""

    myenv = self.Clone()
    if myenv['PLATFORM'] == 'darwin':
        myenv.Append(LDMODULEFLAGS = ["-undefined", "suppress", "-flat_namespace",])
    #
    # Swig-generated .cc files cast pointers to long longs and back,
    # which is illegal.  This flag tells g++ about the sin
    #
    try:
        if myenv.isGcc:
            myenv.Append(CCFLAGS = ["-fno-strict-aliasing",])
    except AttributeError:
        pass

    return myenv.LoadableModule(target, source, **keywords)

SConsEnvironment.LoadableModuleIncomplete = LoadableModuleIncomplete
SConsEnvironment.SwigLoadableModule = LoadableModuleIncomplete

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def ProductDir(product):
    """Return a product's PRODUCT_DIR, or None"""

    import eups

    global _productDirs

    try:
        _productDirs
    except:
        try:
            _productDirs = eups.productDir()
        except TypeError:               # old version of eups (pre r18588)
            _productDirs = None

    if _productDirs:
        pdir = _productDirs.get(product)
    else:
        pdir = eups.productDir(product)
            
    if pdir == "none":
        pdir = None
        
    return pdir

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
    
    eupsPath = os.environ['PWD']
    if env.has_key('eupsProduct') and env['eupsPath']:
        eupsPath = env['eupsPath']

    return pathFormat % { "P": eupsPath,
                          "f": env['eupsFlavor'],
                          "p": env['eupsProduct'],
                          "v": env['version'],
                          "c": os.environ['PWD'] }
    
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def getVersion(env, versionString):
    """Set a version ID from env, or
    a cvs or svn ID string (dollar name dollar or dollar HeadURL dollar)"""

    version = "unknown"

    if env.has_key('version'):
        version = env['version']
        if env.has_key('baseversion') and \
                not version.startswith(env['baseversion']):
            utils.log.warn("Explicit version %s is incompatible with baseversion %s"
                           % (version, env['baseversion']))
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
        if env.installing or env.declaring:
            try:
                version = svn.guessVersionName(HeadURL)
            except RuntimeError, e:
                if env['force']:
                    version = "unknown"
                else:
                    print >> sys.stderr, \
                          "%s\nFound problem with svn revision number; update or specify force=True to proceed" %e
                    sys.exit(1)
            if env.has_key('baseversion'):
                version = env['baseversion'] + "+" + version
    elif versionString.lower() in ("hg", "mercurial"):
        # Mercurial (hg).
        try:
            version = hg.guessVersionName()
        except RuntimeError, e:
            if env['force']:
                version = "unknown"
            else:
                print >> sys.stderr, \
                      "%s\nFound problem with hg version; update or specify force=True to proceed" %e
                sys.exit(1)

    env["version"] = version
    return version

def setPrefix(env, versionString, eupsProductPath=None):
    """Set a prefix based on the EUPS_PATH, the product name, and a versionString from cvs or svn"""

    if eupsProductPath:
        getVersion(env, versionString)
        eupsPrefix = makeProductPath(eupsProductPath, env)
        
    elif env.has_key('eupsPath') and env['eupsPath']:
        eupsPrefix = env['eupsPath']
	flavor = env['eupsFlavor']
	if not re.search("/" + flavor + "$", eupsPrefix):
	    eupsPrefix = os.path.join(eupsPrefix, flavor)
        prodPath = env['eupsProduct']
        if env.has_key('eupsProductPath') and env['eupsProductPath']:
            prodPath = env['eupsProductPath']
        eupsPrefix = os.path.join(eupsPrefix, prodPath, getVersion(env, versionString))
    else:
        eupsPrefix = None

    if env.has_key('prefix'):
        if getVersion(env, versionString) != "unknown" and eupsPrefix and eupsPrefix != env['prefix']:
            print >> sys.stderr, "Ignoring prefix %s from EUPS_PATH" % eupsPrefix

        return makeProductPath(env['prefix'], env)
    elif env.has_key('eupsPath') and env['eupsPath']:
        prefix = eupsPrefix
    else:
        prefix = "/usr/local"

    return prefix

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
    #
    action += " ; rm -rf .sconf_temp" # had to remove .sconsign.dblite for scons 2.1.0
    #
    # Do we actually want to clean up?  We don't if the command is e.g. "scons -c install"
    #
    if "clean" in COMMAND_LINE_TARGETS:
        Command("clean", "", action=action)
    elif not COMMAND_LINE_TARGETS and GetOption("clean"):
        Execute(Action([action]))

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
                f = flag[0]
            else:
                f = flag

            if f in ("-arch", "-dynamic", "-fwrapv",
                     "-fno-strict-aliasing", "-fno-common",
                     "-Wstrict-prototypes"):
                continue
            
            new += [flag]
        self[k] = new

SConsEnvironment.PkgConfigEUPS = PkgConfigEUPS

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def getLibs(env, targets="main"):
    """Get the libraries the package should be linked with.

    Arguments:
       targets --- A string containing whitespace-delimited targets.  Standard
                   targets are "main", "python", and "test".  Default is "main".
                   A special virtual target "self" can be provided, returning
                   the results of targets="main" with the eups_target library
                   removed.

    Typically, main libraries will be linked with LIBS=getLibs("self"),
    Python modules will be linked with LIBS=getLibs("main python") and
    C++-coded test programs will be linked with LIBS=getLibs("main test")
    """
    libs = []
    removeSelf = False
    for target in targets.split():
        if target == "self":
            target = "main"
            removeSelf = True
        for lib in env.libs[target]:
            if lib not in libs:
                libs.append(lib)
    if removeSelf:
        try:
            libs.remove(env["eupsProduct"])
        except ValueError:
            pass
    return libs

SConsEnvironment.getLibs = getLibs

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def SourcesForSharedLibrary(self, files):
    """Prepare the list of files to be passed to a SharedLibrary constructor

In particular, ensure that any files listed in env.NoOptFiles (set by the command line option
noOptFile="file1 file2") are built without optimisation and files listed in env.optFiles are
built with optimisation

The usage pattern in an SConscript file is:
   ccFiles = env.SourcesForSharedLibrary(glob.glob("../src/*/*.cc"))
   env.SharedLibrary('afw', ccFiles, LIBS=filter(lambda x: x != "afw", env.getlibs("afw")))
"""

    if not (self.get("optFiles") or self.get("noOptFiles")):
        return files

    if self.get("optFiles"):
        optFiles = self["optFiles"].replace(".", r"\.") # it'll be used in an RE
        optFiles = Split(optFiles.replace(",", " "))
        optFilesRe = "/(%s)$" % "|".join(optFiles)
    else:
        optFilesRe = None

    if self.get("noOptFiles"):
        noOptFiles = self["noOptFiles"].replace(".", r"\.") # it'll be used in an RE
        noOptFiles = Split(noOptFiles.replace(",", " "))
        noOptFilesRe = "/(%s)$" % "|".join(noOptFiles)
    else:
        noOptFilesRe = None

    if self.get("opt"):
        opt = int(self["opt"])
    else:
        opt = 0

    if opt == 0:
        opt = 3

    CCFLAGS_OPT = re.sub(r"-O(\d|s)\s*", "-O%d " % opt, str(self["CCFLAGS"]))
    CCFLAGS_NOOPT = re.sub(r"-O(\d|s)\s*", "-O0 ", str(self["CCFLAGS"])) # remove -O flags from CCFLAGS

    sources = []
    for ccFile in files:
        if optFilesRe and re.search(optFilesRe, ccFile):
            self.SharedObject(ccFile, CCFLAGS=CCFLAGS_OPT)
            ccFile = os.path.splitext(ccFile)[0] + self["SHOBJSUFFIX"]
        elif noOptFilesRe and re.search(noOptFilesRe, ccFile):
            self.SharedObject(ccFile, CCFLAGS=CCFLAGS_NOOPT)
            ccFile = os.path.splitext(ccFile)[0] + self["SHOBJSUFFIX"]

        sources.append(ccFile)

    return sources

SConsEnvironment.SourcesForSharedLibrary = SourcesForSharedLibrary
    
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def filesToTag(root=None, fileRegex=None, ignoreDirs=None):
    """Return a list of files that need to be scanned for tags, starting at directory root

    Files are chosen if they match fileRegex; toplevel directories in list ignoreDirs are ignored

    This routine won't do anything unless you specified a "TAGS" target
    """
    if root is None: root = "."
    if fileRegex is None: fileRegex = r"^[a-zA-Z0-9_].*\.(cc|h(pp)?|py)$"
    if ignoreDirs is None: ignoreDirs = ["examples", "tests"]

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
        candidates = [f for f in filenames if re.search(fileRegex, f)]
        #
        # Remove files generated by swig
        #
        for swigFile in [f for f in filenames if re.search(r"\.i$", f)]:
            name = os.path.splitext(swigFile)[0]
            candidates = [f for f in candidates if not re.search(r"%s(_wrap\.cc?|\.py)$" % name, f)]

        files += [os.path.join(dirpath, f) for f in candidates]

    return files

def BuildETags(env, root=None, fileRegex=None, ignoreDirs=None):
    toTag = filesToTag(root, fileRegex, ignoreDirs)
    if toTag:
        return env.Command("TAGS", files, "etags -o $TARGET $SOURCES")

SConsEnvironment.BuildETags = BuildETags
