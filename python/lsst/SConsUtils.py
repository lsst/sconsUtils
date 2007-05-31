#
# Note that this file is called SConsUtils.py not SCons.py so as to allow us to import SCons
#
import glob
import os
import re
import shutil
from SCons.Script import *              # So that this file has the same namespace as SConstruct/SConscript
from SCons.Script.SConscript import SConsEnvironment
import stat
import sys

try:
    import eups
except ImportError:
    pass    

def MakeEnv(eups_product, versionString=None, dependencies=[], traceback=False):
    """Setup a standard SCons environment, add our dependencies, and fix some os/x problems"""
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
    if ARGUMENTS.has_key("optfile"):
        configfile = ARGUMENTS["optfile"]
        if not os.path.isfile(configfile):
            print >> sys.stderr, "Ignoring optfile=%s as file %s doesn't exist" % (configfile, configfile)
    else:
        configfile = "buildOpts.py"
        
    if os.path.isfile(configfile):
        opts = Options(configfile)
    else:
        opts = Options()
        
    opts.AddOptions(
        BoolOption('debug', 'Set to enable debugging flags', 1),
        ('eupsdb', 'Specify which element of EUPS_PATH should be used', None),
        ('flavor', 'Set the build flavor', None),
        ('optfile', 'Specify a file to read default options from', None),
        ('prefix', 'Specify the install destination', None),
        EnumOption('opt', 'Set the optimisation level', 0, allowed_values=('0', '1', '2', '3')),
        ('version', 'Specify the current version', None),
        )

    products = []
    for productProps in dependencies:
        products += [productProps[0]]
    products.sort()

    for p in products:
        dir = productDir(p)
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

    env = Environment(ENV = {'EUPS_DIR' : os.environ['EUPS_DIR'],
                             'EUPS_PATH' : os.environ['EUPS_PATH'],
                             'PATH' : os.environ['PATH'],
                             'LD_LIBRARY_PATH' : os.environ['LD_LIBRARY_PATH']
                             }, options = opts,
		      tools = ["default", "doxygen"],
		      toolpath = toolpath
		      )
    env['eups_product'] = eups_product
    Help(opts.GenerateHelpText(env))

    env.libs = {}
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
    # Check for unprocessed arguments
    #
    errors = []
    errorStr = ""
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
    # Is the C compiler really gcc/g++?
    #
    def IsGcc(context):
        context.Message("Checking if  CC is really gcc...")
        result = context.TryAction(["%s --help | grep gcc" % env['CC']])[0]
        context.Result(result)
        return result

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
    if not CleanFlagIsSet() and not HelpFlagIsSet() and dependencies:
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
            if not productDir(product): # don't override EUPS
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
                        if env.CheckHeaderGuessLanguage(incdir, incfiles):
                            env.Replace(CPPPATH = env['CPPPATH'] + [incdir])
                    except RuntimeError, msg:
                        errors += [str(msg)]
                        
                if libs:
                    conf = env.Clone(LIBPATH = env['LIBPATH'] + [libdir]).Configure()
                    try:
                        libs, lang = libs.split(":")
                    except ValueError:
                        lang = "C"

                    libs = Split(libs)
                    for lib in libs[:-1]:
                        if not conf.CheckLib(lib, language=lang):
                            errors += ["Failed to find %s" % (lib)]
                            success = False
                    lib = libs[-1]

                    if product == "boost": # Special case boost as it messes with library names. Sigh.
                        blib = chooseBoostLib(env, libdir, lib)
                        #print "Choosing %s for %s" % (blib, lib)
                        lib = blib

                    if conf.CheckLib(lib, symbol, language=lang):
                        if libdir not in env['LIBPATH']:
                            env.Replace(LIBPATH = env['LIBPATH'] + [libdir])
                            Repository(libdir)                        
                    else:
                        errors += ["Failed to find %s in %s" % (lib, libdir)]
                        success = False
                    conf.Finish()

                    env.libs[product] += [lib]

                if success:
                    continue
            elif incfiles or libs:       # Not specified; see if we got lucky in the environment
                success = True
                
                if incfiles:
                    try:
                        if env.CheckHeaderGuessLanguage(incdir, incfiles):
                            env.Replace(CPPPATH = env['CPPPATH'] + [incdir])
                    except RuntimeError, msg:
                        errors += [str(msg)]
                        success = False

                if libs:
                    conf = env.Configure()
                    for lib in Split(libs):
                        if not conf.CheckLib(lib, symbol):
                            success = False
                    conf.Finish()

                if success:
                    continue
            elif pkgConfig:
                continue                # We'll trust them here too; they did provide a pkg-config script
            else:
                pass                    # what can we do? No PRODUCT_DIR, no product-config,
                                        # no include file to find

            errors += ["Failed to find %s -- do you need to setup %s or specify %s=DIR?" % \
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
    # Where to install
    #
    prefix = setPrefix(env, versionString)
    env['prefix'] = prefix
    
    env["libDir"] = "%s/lib" % prefix
    env["pythonDir"] = "%s/python" % prefix

    Export('env')

    return env

makeEnv = MakeEnv                       # backwards compatibility

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

    for lang in languages:
        conf = self.Clone(CPPPATH = self['CPPPATH'] + [incdir]).Configure()
        foundHeader = conf.CheckHeader(incfiles, language=lang)
        conf.Finish()

        if foundHeader:
            if incdir in self['CPPPATH']:
                return False            # no need for another copy
            else:
                return True

    raise RuntimeError, "Failed to find %s in %s" % (incfiles[-1], incdir)

SConsEnvironment.CheckHeaderGuessLanguage = CheckHeaderGuessLanguage

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def getlibs(env, *libraries):

    libs = []
    for lib in libraries:
        libs += env.libs[lib]

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

def chooseBoostLib(env, libdir, lib):
    """Choose the proper boost library; there maybe a number to choose from"""
    
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

def installFunc(dest, source, env):
    """Install a source file or directory into a destination by copying,
    (including copying permission/mode bits)."""

    if env.has_key('IgnoreFiles'):
        ignore = env['IgnoreFiles']
    else:
        ignore = False

    if os.path.isdir(source):
        if os.path.exists(dest):
            if not os.path.isdir(dest):
                raise SCons.Errors.UserError, "cannot overwrite non-directory `%s' with a directory `%s'" % (str(dest), str(source))
        else:
            parent = os.path.split(dest)[0]
            if not os.path.exists(parent):
                os.makedirs(parent)
        copytree(source, dest, ignore = ignore)
    else:
        if ignore and re.search(ignore, source):
            #print "Ignoring", source
            pass
        else:
            shutil.copy2(source, dest)
            st = os.stat(source)
            os.chmod(dest, stat.S_IMODE(st[stat.ST_MODE]) | stat.S_IWRITE)

    return 0

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def productDir(product):
    """Return a product's PRODUCT_DIR, or None"""
    product_dir = product.upper() + "_DIR"

    if os.environ.has_key(product_dir):
        return os.environ[product_dir]
    else:
        return None
    
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def getVersion(env, versionString):
    """Set a version ID from env, or
    a cvs or svn ID string (dollar name dollar or dollar HeadURL dollar)"""

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
        version = re.search(r"/([^/]+)$", os.path.split(versionString)[0]).group(1)
        if version == "trunk":
            version = "svn"
    else:
        version = "unknown"

    env["version"] = version
    return version

def setPrefix(env, versionString):
    """Set a prefix based on the EUPS_PATH, the product name, and a versionString from cvs or svn"""

    if env.has_key('eups_path') and env['eups_path']:
        eups_prefix = env['eups_path']
	flavor = env['eups_flavor']
	if not re.search("/" + flavor + "$", eups_prefix):
	    eups_prefix = os.path.join(eups_prefix, flavor)

        eups_prefix = os.path.join(eups_prefix, env['eups_product'],
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

def CleanFlagIsSet():
    """Return True iff they're running "scons --clean" """
    return SCons.Script.Main.options.clean

def NoexecFlagIsSet():
    """Return True iff they're running "scons -n" """
    return SCons.Script.Main.options.noexec

def HelpFlagIsSet():
    """Return True iff they're running "scons --help" """
    return SCons.Script.Main.options.help_msg

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def Declare(self, products=None):
    """Create current and declare targets for products.  products
    may be a list of (product, version) tuples.  If product is None
    it's taken to be self['eups_product']; if version is None it's
    taken to be self['version'].
    
    We'll add Declare to class Environment"""

    if \
           "declare" in COMMAND_LINE_TARGETS or \
           "undeclare" in COMMAND_LINE_TARGETS or \
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

                if "undeclare" in COMMAND_LINE_TARGETS or CleanFlagIsSet():
                    if version:
                        command = "eups undeclare --flavor %s %s %s" % \
                                  (self['eups_flavor'], product, version)
                        if CleanFlagIsSet():
                            self.Execute(command)
                        else:
                            undeclare += [command]
                    else:
                        print >> sys.stderr, "I don't know your version; not undeclaring to eups"
                else:
                    command = "eups declare --force --flavor %s --root %s" % \
                              (self['eups_flavor'], self['prefix'])

                    if version:
                        command += " %s %s" % (product, version)

                    current += [command + " --current"]
                    declare += [command]

        if current:
            self.Command("current", "", action=current)
        if declare:
            self.Command("declare", "", action=declare)
        if undeclare:
            self.Command("undeclare", "", action=undeclare)
                
SConsEnvironment.Declare = Declare

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def CleanTree(files, dir=".", recurse=True, verbose=False):
    """Remove files matching the argument list starting at dir
    when scons is invoked with -c/--clean
    
    E.g. CleanTree(r"*~ core")

    If recurse is True, recursively descend the file system; if
    verbose is True, print each filename after deleting it
    """
    
    if CleanFlagIsSet() :
	files_expr = ""
	for file in Split(files):
	    if files_expr:
		files_expr += " -o "

	    files_expr += "-name %s" % file
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
	
	Execute(Action([action]))

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

try:
    type(_Install)
except:
    _Install = SConsEnvironment.Install

def MyInstall(env, dest, files):
    """Like Install, but remove the target when cleaning if files is a directory"""

    if CleanFlagIsSet():
        try:
            if os.path.isdir(files):
                dir = os.path.join(dest, files)
                print >> sys.stderr, "Removing", dir
                shutil.rmtree(dir, ignore_errors=True)
        except TypeError:
            pass                        # "files" isn't a string
    
    return _Install(env, dest, files)

if False:                               # tickles an scons bug
    SConsEnvironment.Install = MyInstall

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def InstallEups(env, dest, files, presetup=""):
    """Install a ups directory, setting absolute versions as appropriate
    if presetup is provided, it's expected to be a dictionary with keys
    prudoct names and values the version that should be installed into
    the table files, overriding eups expandtable's usual behaviour. E.g.
env.InstallEups(env['prefix'] + "/ups",
                glob.glob("ups/*.table"),
                dict([("sconsUtils", env['version'])])
                )    
    """

    if CleanFlagIsSet():
        print >> sys.stderr, "Removing", dest
        shutil.rmtree(dest, ignore_errors=True)
    else:
        presetupStr = []
        for p in presetup:
            presetupStr += ["--product %s=%s" % (p, presetup[p])]
        presetup = " ".join(presetupStr)

        env = env.Clone(ENV = os.environ)

        obj = env.Install(dest, files)
        for i in obj:
            cmd = "eups_expandtable -i "
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
                             (productDir(product), product))
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
    self.Replace(CPPPATH = self['CPPPATH'] + [distutils.sysconfig.get_python_inc()])

    if not self.has_key('LIBPATH'):
        self['LIBPATH'] = []
    self.Replace(LIBPATH = self['LIBPATH'] + [distutils.sysconfig.get_python_lib()])

SConsEnvironment.CheckPython = CheckPython

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def CheckSwig(self, language="python", ilang="C", ignoreWarnings=None,
              swigdir=None):
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
        self['ENV']['PATH'] += os.pathsep + swigdir

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
    
