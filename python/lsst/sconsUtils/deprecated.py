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
    def CheckVariable(context, prog, flag):
        context.Message('Checking for option %s to %s... ' % (flag, prog))
        result = context.TryAction(["%s %s" % (prog, flag)])[0]
        context.Result(result)
        return result

    env = Environment()
    conf = Configure(env, custom_tests = {'CheckOption' : CheckOption})
    if not conf.CheckVariable("gcc", "-Wall"):
        print "Can't find flag"
    env = conf.Finish()
    

#=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def MakeEnv(, variables=None):
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
    pass
    

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=

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
    pass

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
