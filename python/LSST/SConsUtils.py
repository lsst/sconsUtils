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

def makeEnv(eups_product, versionString=None, dependencies=[], traceback=False):
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
                       dir and dir + "/include" or None),
            PathOption(p + "Lib", "Specify the location of %s's libraries" % p,
                       dir and dir + "/lib" or None),
            )

    env = Environment(ENV = {'EUPS_DIR' : os.environ['EUPS_DIR'],
                             'EUPS_PATH' : os.environ['EUPS_PATH'],
                             'PATH' : os.defpath,
                             }, options = opts)
    env['eups_product'] = eups_product
    Help(opts.GenerateHelpText(env))
    #
    # SCons gets confused about shareable/static objects if
    # you specify libraries as e.g. "#libwcs.a", but it's OK
    # if you say LIBS = ["wcs"].
    #
    if False:
        env['STATIC_AND_SHARED_OBJECTS_ARE_THE_SAME'] = True
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
    if env['PLATFORM'] == "posix":
        env['eups_flavor'] = os.uname()[0]
    else:
        env['eups_flavor'] = env['PLATFORM']

    if env['opt']:
        env.Append(CCFLAGS = '-O%d' % int(env['opt']))
    #
    # Process dependencies
    #
    env['CPPPATH'] = []
    env['LIBPATH'] = []
    if not CleanFlagIsSet() and not HelpFlagIsSet() and dependencies:
        for productProps in dependencies:
            while len(productProps) < 4:     # allow the user to omit values
                productProps += [""]
            if len(productProps) > 4:
                print >> sys.stderr, "Ignoring extra values while configuring %s: %s" % \
                      (productProps[0], " ".join(productProps[4:]))

            (product, incfile, libs, symbol) = productProps[0:4]
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
                                        # specify incfile/libs, we'll have to trust them
                if incfile:
                    conf = env.Clone(CPPPATH = env['CPPPATH'] + [incdir]).Configure()
                    if conf.CheckCHeader(incfile):
                        env.Replace(CPPPATH = env['CPPPATH'] + [incdir])
                    else:
                        errors += ["Failed to find %s in %s" % (incfile, incdir)]
                        success = False
                        
                    conf.Finish()
                if libs:
                    conf = env.Clone(LIBPATH = env['LIBPATH'] + [libdir]).Configure()
                    if conf.CheckLib(libs, symbol):
                        env.Replace(LIBPATH = env['LIBPATH'] + [libdir])
                        Repository(libdir)                        
                    else:
                        errors += ["Failed to find %s in %s" % (libs, libdir)]
                        success = False
                    conf.Finish()

                if success:
                    continue
            elif incfile or libs:       # Not specified; see if we got lucky in the environment
                conf = env.Configure()

                success = True
                if incfile and not conf.CheckCHeader(incfile):
                    success = False
                if libs and not conf.CheckLib(libs, symbol):
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
    #
    # Where to install
    #
    prefix = setPrefix(env, versionString)
    env['prefix'] = prefix
    
    env["libDir"] = "%s/lib" % prefix
    env["pythonDir"] = "%s/python" % prefix

    Export('env')

    return env

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

def SharedLibraryIncomplete(self, target, source, LIBS=None):
    """Like SharedLibrary, but don't insist that all symbols are resolved"""

    myenv = self.Clone()

    if myenv['PLATFORM'] == 'darwin':
        myenv['SHLINKFLAGS'] += " -undefined suppress -flat_namespace"

    return myenv.SharedLibrary(target, source, LIBS=LIBS)

SConsEnvironment.SharedLibraryIncomplete = SharedLibraryIncomplete


def LoadableModuleIncomplete(self, target, source, LIBS=None):
    """Like LoadableModule, but don't insist that all symbols are resolved"""

    myenv = self.Clone()

    if myenv['PLATFORM'] == 'darwin':
        myenv['LDMODULEFLAGS'] += " -undefined suppress -flat_namespace"
        myenv['LDMODULESUFFIX'] = ".so"

    return myenv.LoadableModule(target, source, LIBS=LIBS)

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

    return version

def setPrefix(env, versionString):
    """Set a prefix based on the EUPS_PATH, the product name, and a versionString from cvs or svn"""

    if env.has_key('eups_path') and env['eups_path']:
        eups_prefix = os.path.join(env['eups_path'], env['eups_flavor'].title(),
                                   env['eups_product'], getVersion(env, versionString))
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
    """Return True iff they're running "scons clean" """
    return SCons.Script.Main.options.clean

def HelpFlagIsSet():
    """Return True iff they're running "scons --help" """
    return SCons.Script.Main.options.help_msg

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

def Declare(self):
    """Create a declare target; we'll add this to class Environment"""
    if "declare" in COMMAND_LINE_TARGETS:
        if "EUPS_DIR" in os.environ.keys():
            self['ENV']['PATH'] += os.pathsep + "%s/bin" % (os.environ["EUPS_DIR"])
            
            if CleanFlagIsSet():
                if self.has_key('version'):
                    command = "-eups undeclare --flavor %s %s %s" % \
                              (self['eups_flavor'].title(), self['eups_product'], self['version'])
                    self.Execute(command)
                else:
                    print >> sys.stderr, "I don't know your version; not undeclaring to eups"
            else:
                command = "eups declare --force --flavor %s --root %s" % \
                          (self['eups_flavor'].title(), self['prefix'])

                if self.has_key('version'):
                    command += " %s %s" % (self['eups_product'], self['version'])
                    
                self.Command("declare", "", action=command)

SConsEnvironment.Declare = Declare

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def InstallEups(env, dest, files):
    """Install a ups directory, setting absolute versions as appropriate"""

    env = env.Clone(ENV = os.environ)

    obj = env.Install(dest, files)
    for i in obj:
        cmd = "eups_expandtable -i %s" % (str(i))
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

def CheckSwig(self, language="python", swigdir=None):
    """Adjust the construction environment to allow the use of swig;
    if swigdir is specified it's the path to the swig binary, otherwise
    the calling process' PATH is searched"""
    
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
    self['SWIGFLAGS'] = "-%s" % language

SConsEnvironment.CheckSwig = CheckSwig
