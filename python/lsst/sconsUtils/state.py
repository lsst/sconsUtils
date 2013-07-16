##
#  @file state.py
#
# This module acts like a singleton, holding all global state for sconsUtils.
# This includes the primary Environment object (state.env), the message log (state.log),
# the command-line variables object (state.opts), and a dictionary of command-line targets
# used to setup aliases, default targets, and dependencies (state.targets).  All four of
# these variables are aliased to the main lsst.sconsUtils scope, so there should be no
# need for users to deal with the state module directly.
#
# These are all initialized when the module is imported, but may be modified by other code
# (particularly dependencies.configure()).
##

import SCons.Script
import sys
import os.path
import re

SCons.Script.EnsureSConsVersion(2, 1, 0)

##
#  @brief A dictionary of SCons aliases and targets.
#
#  These are used to setup aliases, default targets, and dependencies by BasicSConstruct.finish().
#  While one can still use env.Alias to setup aliases (and should for "install"), putting targets
#  here will generally provide better build-time dependency handling (like ensuring everything
#  is built before we try to install, and making sure SCons doesn't rebuild the world before
#  installing).
#
#  Users can add additional keys to the dictionary if desired.
#
#  Targets should be added by calling extend() or using += on the dict values, to keep the lists of
#  targets from turning into lists-of-lists.
##
targets = {"doc": [], "tests": [], "lib": [], "python": [], "examples": [], "include": [], "version": []}

## @cond INTERNAL

env = None
log = None
opts = None


def _initOptions():
    SCons.Script.AddOption('--checkDependencies', dest='checkDependencies',
                           action='store_true', default=False,
                           help="Verify dependencies with autoconf-style tests.")
    SCons.Script.AddOption('--filterWarn', dest='filterWarn', action='store_true', default=False,
                           help="Filter out a class of warnings deemed irrelevant"),
    SCons.Script.AddOption('--force', dest='force', action='store_true', default=False,
                           help="Set to force possibly dangerous behaviours")
    SCons.Script.AddOption('--linkFarmDir', dest='linkFarmDir', action='store', default=None,
                           help="The directory of symbolic links needed to build and use the package")
    SCons.Script.AddOption('--prefix', dest='prefix', action='store', default=False,
                           help="Specify the install destination")
    SCons.Script.AddOption('--setenv', dest='setenv', action='store_true', default=False,
                           help="Treat arguments such as Foo=bar as defining construction variables")
    SCons.Script.AddOption('--tag', dest='tag', action='store', default=None,
                           help="Declare product with this eups tag")
    SCons.Script.AddOption('--verbose', dest='verbose', action='store_true', default=False,
                           help="Print additional messages for debugging.")
    SCons.Script.AddOption('--traceback', dest='traceback', action='store_true', default=False,
                           help="Print full exception tracebacks when errors occur.")
    SCons.Script.AddOption('--c++11', dest='cxx11', action='store_true', default=False,
                           help="Enable C++11 compiler extensions.")

def _initLog():
    from . import utils
    global log
    log = utils.Log()

def _initVariables():
    files = []
    if SCons.Script.ARGUMENTS.has_key("optfile"):
        configfile = SCons.Script.ARGUMENTS["optfile"]
        if configfile not in files:
            files.append(configfile)
    for file in files:
        if not os.path.isfile(file):
            log.warn("Warning: Will ignore non-existent options file, %s" % file)
    if not SCons.Script.ARGUMENTS.has_key("optfile"):
        files.append("buildOpts.py")
    global opts
    opts = SCons.Script.Variables(files)
    opts.AddVariables(
        ('archflags', 'Extra architecture specification to add to CC/LINK flags (e.g. -m32)', ''),
        ('cc', 'Choose the compiler to use', ''),
        SCons.Script.BoolVariable('debug', 'Set to enable debugging flags (use --debug)', True),
        ('eupsdb', 'Specify which element of EUPS_PATH should be used', None),
        ('flavor', 'Set the build flavor', None),
        SCons.Script.BoolVariable('force', 'Set to force possibly dangerous behaviours', False),
        ('optfile', 'Specify a file to read default options from', None),
        ('prefix', 'Specify the install destination', None),
        SCons.Script.EnumVariable('opt', 'Set the optimisation level', 0, 
                                  allowed_values=('0', '1', '2', '3')),
        SCons.Script.EnumVariable('profile', 'Compile/link for profiler', 0, 
                                  allowed_values=('0', '1', 'pg', 'gcov')),
        ('version', 'Specify the version to declare', None),
        ('baseversion', 'Specify the current base version', None),
        ('optFiles', "Specify a list of files that SHOULD be optimized", None),
        ('noOptFiles', "Specify a list of files that should NOT be optimized", None),
        )

def _initEnvironment():
    """Construction and basic setup of the state.env variable."""

    ourEnv = {}
    for key in ('EUPS_DIR', 'EUPS_PATH', 'PATH' ,'DYLD_LIBRARY_PATH', 'LD_LIBRARY_PATH',
                'SHELL', 'TMPDIR', 'TEMP', 'TMP', 'EUPS_LOCK_PID', 'XPA_PORT'):
        if key in os.environ:
            ourEnv[key] = os.environ[key]

    # Find and propagate EUPS environment variables.
    cfgPath = []
    for k in os.environ.keys():
        m = re.search(r"^(?P<name>\w+)_DIR(?P<extra>_EXTRA)?$", k)
        if not m: continue
        cfgPath.append(os.path.join(os.environ[k], "ups"))
        if m.group("extra"):
            cfgPath.append(os.environ[k])
        else:
            cfgPath.append(os.path.join(os.environ[k], "ups"))
            p = m.group("name")
            import eups
            varname = eups.utils.setupEnvNameFor(p)
            if os.environ.has_key(varname):
                ourEnv[varname] = os.environ[varname]
                ourEnv[k] = os.environ[k]

    # Recursively walk LSST_CFG_PATH
    for root in os.environ.get("LSST_CFG_PATH", "").split(":"):
        for base, dirs, files in os.walk(root):
            dirs = [d for d in dirs if not d.startswith(".")]
            cfgPath.insert(0, base)
    #
    # Add any values marked as export=FOO=XXX[,GOO=YYY] to ourEnv
    #
    opt = "export"
    if SCons.Script.ARGUMENTS.has_key(opt):
        for kv in ARGUMENTS[opt].split(','):
            k, v = kv.split('=')
            ourEnv[k] = v

        del SCons.Script.ARGUMENTS[opt]
    global env
    sconsUtilsPath, thisFile = os.path.split(__file__)
    toolPath = os.path.join(sconsUtilsPath, "tools")
    env = SCons.Script.Environment(
        ENV=ourEnv,
        variables=opts,
        toolpath=[toolPath],
        tools=["default", "cuda"]
    )
    env.cfgPath = cfgPath
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
            del SCons.Script.ARGUMENTS[opt]
        except KeyError:
            pass
    #
    # Process those arguments
    #
    for k in ("force", "prefix"):       # these may now be set as options instead of variables
        if SCons.Script.GetOption(k):
            env[k] = SCons.Script.GetOption(k)
        
    if env['debug']:
        env.Append(CCFLAGS = ['-g'])
    #
    # Find the eups path, replace 'flavor' in favor of 'PLATFORM' if needed.
    #
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
    if SCons.Script.GetOption("setenv"):
        for key in SCons.Script.ARGUMENTS.keys():
            env[key] = SCons.Script.Split(SCons.Script.ARGUMENTS[key])
    else:
        for key in SCons.Script.ARGUMENTS.keys():
            errorStr += " %s=%s" % (key, SCons.Script.ARGUMENTS[key])
        if errorStr:
            log.fail("Unprocessed arguments:%s" % errorStr)
    #
    # We need a binary name, not just "Posix"
    #
    try:
        import eups
        env['eupsFlavor'] = eups.flavor()
    except:
        log.warn("Unable to import eups; guessing flavor")
        if env['PLATFORM'] == "posix":
            env['eupsFlavor'] = os.uname()[0].title()
        else:
            env['eupsFlavor'] = env['PLATFORM'].title()

def _configureCommon():
    """Configuration checks for the compiler, platform, and standard libraries."""
    #
    # Is the C compiler really gcc/g++?
    #
    def ClassifyCc(context):
        """Return a string identifing the compiler in use"""
        versionStrings = {"Free Software Foundation" : "gcc",
                          "Intel Corporation" : "icc",
                          "clang version" : "clang",
                          "LLVM" : "clang",
                          }
        context.Message("Checking who built the CC compiler...")
        for string, key in versionStrings.items():
            action = r"$CC --version | grep '%s' > $TARGET" % string
            result = context.TryAction(SCons.Script.Action(action))
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
            env0 = SCons.Script.Environment()
            if CC and env['CC'] == env0['CC']:
                env['CC'] = CC
            if CC and env['CXX'] == env0['CXX']:
                env['CXX'] = CXX
        conf = env.Configure(custom_tests = {'ClassifyCc' : ClassifyCc,})
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

    #
    # Do we want to use C++11 compiler extensions?
    #
    if not (env.GetOption("clean") or env.GetOption("help") or env.GetOption("no_exec")):
        if env.whichCc == 'gcc':
            env.Append(CFLAGS = '-std=c99')

        if env.GetOption("cxx11"):
            if env.whichCc == "clang":
                env.Append(CCFLAGS = '-std=c++11')
            elif env.whichCc == "icc":
                env.Append(CCFLAGS = '-std=c++0x')
            elif env.whichCc == 'gcc':
                env.Append(CCFLAGS = '-std=gnu++0x')
            else:
                log.fail("C++11 extensions could not be enabled for compiler %r" % env.whichCc)
            log.info("Enabling C++11 extensions")
    #
    # Is C++'s TR1 available?  If not, use e.g. #include "lsst/tr1/foo.h"
    #
    # NOTE: previously this was only checked when none of --clean, --help, and --noexec,
    # but that was causing "no" to be cached and used on later runs.
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
    #
    if (re.search(r"^(Linux|Linux64)$", env["eupsFlavor"]) and os.environ.has_key("LD_LIBRARY_PATH")):
        env.Append(LINKFLAGS = ["-Wl,-rpath-link"])
        env.Append(LINKFLAGS = ["-Wl,%s" % os.environ["LD_LIBRARY_PATH"]])
    #
    # Set the optimization level.
    #
    if env['opt']:
        env["CCFLAGS"] = [o for o in env["CCFLAGS"] if not re.search(r"^-O(\d|s)$", o)]
        env.MergeFlags('-O%d' % int(env['opt']))
    #
    # Set compiler-specific warning flags.
    #
    if env.whichCc == "clang":
        env.Append(CCFLAGS = ['-Wall'])
        if False:                       # requires you to rebuild boost; not worth it (yet).
            env.Append(CCFLAGS = ['-stdlib=libc++'])
            env.Append(LINKFLAGS = ['-stdlib=libc++'])
        env["CCFLAGS"] = [o for o in env["CCFLAGS"] if not re.search(r"^-mno-fused-madd$", o)]

        ignoreWarnings = {
            "unused-function" : 'boost::regex has functions in anon namespaces in headers',
            }
        filterWarnings = {
            "attributes" : "clang pretends to be g++, but complains about g++ attributes such as flatten",
            "char-subscripts" : 'seems innocous enough, and is used by boost',
            "constant-logical-operand" : "Used by eigen 2.0.15. Should get this fixed",
            "format-security" : "format string is not a string literal",
            "mismatched-tags" : "mixed class and struct.  Used by gcc 4.2 RTL and eigen 2.0.15",
            "parentheses" : "equality comparison with extraneous parentheses",
            "shorten-64-to-32" : "implicit conversion loses integer precision",
            "self-assign" : "x = x",
            "unknown-pragmas" : "unknown pragma ignored",
            }
        for k in ignoreWarnings.keys():
            env.Append(CCFLAGS = ["-Wno-%s" % k])
        if env.GetOption('filterWarn'):
            for k in filterWarnings.keys():
                env.Append(CCFLAGS = ["-Wno-%s" % k])
    elif env.whichCc == "gcc":
        env.Append(CCFLAGS = ['-Wall'])
        env.Append(CCFLAGS = ["-Wno-unknown-pragmas"]) # we don't want complaints about icc/clang pragmas
    elif env.whichCc == "icc":
        env.Append(CCFLAGS = ['-Wall'])
        filterWarnings = {
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
        if env.GetOption('filterWarn'):
            env.Append(CCFLAGS = ["-wd%s" % (",".join([str(k) for k in filterWarnings.keys()]))])
        # Workaround intel bug; cf. RHL's intel bug report 580167
        env.Append(LINKFLAGS = ["-Wl,-no_compact_unwind", "-wd,11015"])

def _saveState():
    """Save state such as optimization level used.  The scons mailing lists were unable to tell
    RHL how to get this back from .sconsign.dblite
    """

    if env.GetOption("clean"):
        return

    import ConfigParser

    config = ConfigParser.ConfigParser()
    config.add_section('Build')
    config.set('Build', 'cc', env.whichCc)
    if env['opt']:
        config.set('Build', 'opt', env['opt'])

    try:
        confFile = os.path.join(env.Dir(env["CONFIGUREDIR"]).abspath, "build.cfg")
        with open(confFile, 'wb') as configfile:
            config.write(configfile)
    except Exception, e:
        log.warn("Unexpected exception in _saveState: %s" % e)
        
_initOptions()
_initLog()
_initVariables()
_initEnvironment()
_configureCommon()
_saveState()

## @endcond
