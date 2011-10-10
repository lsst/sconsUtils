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
    
