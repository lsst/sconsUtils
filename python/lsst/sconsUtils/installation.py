"""Builders and path setup for installation targets."""

__all__ = (
    "DirectoryInstaller",
    "SConsUtilsEnvironment",
    "determineVersion",
    "getFingerprint",
    "makeProductPath",
    "setPrefix",
)

import glob
import os.path
import re
import shutil

import SCons.Script
from SCons.Script.SConscript import SConsEnvironment

from . import state
from .utils import memberOf
from .vcs import git, hg, svn


class SConsUtilsEnvironment(SConsEnvironment):
    """Dummy class to make visible the methods injected into the SCons
    parent environment.
    """


def makeProductPath(env, pathFormat):
    """Return a path to use as the installation directory for a product.

    Parameters
    ----------
    env : `SCons.Environment`
        The SCons environment.
    pathFormat : `str`
        The format string to process.

    Returns
    -------
    formatted : `str`
        Formatted path string.
    """
    pathFormat = re.sub(r"%(\w)", r"%(\1)s", pathFormat)

    eupsPath = os.environ["PWD"]
    if "eupsPath" in env and env["eupsPath"]:
        eupsPath = env["eupsPath"]

    return pathFormat % {
        "P": eupsPath,
        "f": env["eupsFlavor"],
        "p": env["eupsProduct"],
        "v": env["version"],
        "c": os.environ["PWD"],
    }


def determineVersion(env, versionString):
    """Set a version ID from env, or a version control ID string
    (``$name$`` or ``$HeadURL$``).

    Parameters
    ----------
    env : `SCons.Environment`
        The SCons environment.
    versionString : `str`
        The string containining version information to search if the
        version can not be found in the environment.

    Returns
    -------
    version : `str`
        The version.
    """
    version = "unknown"
    if "version" in env:
        version = env["version"]
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
        version = svn.guessVersionName(HeadURL)
    elif versionString.lower() in ("hg", "mercurial"):
        # Mercurial (hg).
        version = hg.guessVersionName()
    elif versionString.lower() in ("git",):
        # git.
        version = git.guessVersionName()
    return version.replace("/", "_")


def getFingerprint(versionString):
    """Return a unique fingerprint for a version (e.g. an SHA1);

    Parameters
    ----------
    versionString : `str`
        A string that might contain version information.

    Returns
    -------
    fingerprint : `str`
        Unique fingerprint of this version.  `None` if unavailable.
    """
    if versionString.lower() in ("hg", "mercurial"):
        fingerprint = hg.guessFingerprint()
    elif versionString.lower() in ("git",):
        fingerprint = git.guessFingerprint()
    else:
        fingerprint = None

    return fingerprint


def setPrefix(env, versionString, eupsProductPath=None):
    """Set a prefix based on the EUPS_PATH, the product name, and a
    version string from CVS or SVN.

    Parameters
    ----------
    env : `SCons.Environment`
        Environment to search.
    versionString : `str`
        String that might contain version information.
    eupsProductPath : `str`, optional
        Path to the EUPS product.

    Returns
    -------
    prefix : `str`
        Prefix to use.
    """
    try:
        env["version"] = determineVersion(env, versionString)
    except RuntimeError as err:
        env["version"] = "unknown"
        if (env.installing or env.declaring) and not env["force"]:
            state.log.fail(
                f"{err}\nFound problem with version number; update or specify force=True to proceed"
            )

    if state.env["no_eups"]:
        if "prefix" in env and env["prefix"]:
            return env["prefix"]
        else:
            return "/usr/local"

    if eupsProductPath:
        eupsPrefix = makeProductPath(env, eupsProductPath)
    elif "eupsPath" in env and env["eupsPath"]:
        eupsPrefix = env["eupsPath"]
    else:
        state.log.fail("Unable to determine eupsPrefix from eupsProductPath or eupsPath")
    flavor = env["eupsFlavor"]
    if not re.search("/" + flavor + "$", eupsPrefix):
        eupsPrefix = os.path.join(eupsPrefix, flavor)
        prodPath = env["eupsProduct"]
        if "eupsProductPath" in env and env["eupsProductPath"]:
            prodPath = env["eupsProductPath"]
        eupsPrefix = os.path.join(eupsPrefix, prodPath, env["version"])
    else:
        eupsPrefix = None
    if "prefix" in env:
        if env["version"] != "unknown" and eupsPrefix and eupsPrefix != env["prefix"]:
            state.log.warn(f"Ignoring prefix {eupsPrefix} from EUPS_PATH")
        return makeProductPath(env, env["prefix"])
    elif "eupsPath" in env and env["eupsPath"]:
        prefix = eupsPrefix
    else:
        prefix = "/usr/local"
    return prefix


@memberOf(SConsEnvironment)
def Declare(self, products=None):
    """Create current and declare targets for products.

    Parameters
    ----------
    products : `list` of `tuple`, optional
        A list of ``(product, version)`` tuples.  If ``product`` is `None`
        it's taken to be ``self['eupsProduct']``; if version is `None` it's
        taken to be ``self['version']``.

    Returns
    -------
    acts : `list`
        Commands to execute.
    """

    if "undeclare" in SCons.Script.COMMAND_LINE_TARGETS and not self.GetOption("silent"):
        state.log.warn("'scons undeclare' is deprecated; please use 'scons declare -c' instead")

    acts = []
    if (
        "declare" in SCons.Script.COMMAND_LINE_TARGETS
        or "undeclare" in SCons.Script.COMMAND_LINE_TARGETS
        or ("install" in SCons.Script.COMMAND_LINE_TARGETS and self.GetOption("clean"))
        or "current" in SCons.Script.COMMAND_LINE_TARGETS
    ):
        current = []
        declare = []
        undeclare = []

        if not products:
            products = [None]

        for prod in products:
            if not prod or isinstance(prod, str):  # i.e. no version
                product = prod

                if "version" in self:
                    version = self["version"]
                else:
                    version = None
            else:
                product, version = prod

            if not product:
                product = self["eupsProduct"]

            if "EUPS_DIR" in os.environ:
                self["ENV"]["PATH"] += os.pathsep + f"{os.environ['EUPS_DIR']}/bin"
                self["ENV"]["EUPS_LOCK_PID"] = os.environ.get("EUPS_LOCK_PID", "-1")
                if "undeclare" in SCons.Script.COMMAND_LINE_TARGETS or self.GetOption("clean"):
                    if version:
                        command = f"eups undeclare --flavor {self['eupsFlavor']} {product} {version}"
                        if (
                            "current" in SCons.Script.COMMAND_LINE_TARGETS
                            and "declare" not in SCons.Script.COMMAND_LINE_TARGETS
                        ):
                            command += " --current"

                        if self.GetOption("clean"):
                            self.Execute(command)
                        else:
                            undeclare += [command]
                    else:
                        state.log.warn("I don't know your version; not undeclaring to eups")
                else:
                    command = "eups declare --force --flavor {} --root {}".format(
                        self["eupsFlavor"],
                        self["prefix"],
                    )

                    if "eupsPath" in self:
                        command += f" -Z {self['eupsPath']}"

                    if version:
                        command += f" {product} {version}"

                    current += [command + " --current"]

                    if self.GetOption("tag"):
                        command += f" --tag={self.GetOption('tag')}"

                    declare += [command]

        if current:
            acts += self.Command("current", "", action=current)
        if declare:
            if "current" in SCons.Script.COMMAND_LINE_TARGETS:
                acts += self.Command("declare", "", action="")  # current will declare it for us
            else:
                acts += self.Command("declare", "", action=declare)
        if undeclare:
            acts += self.Command("undeclare", "", action=undeclare)

    return acts


class DirectoryInstaller:
    """SCons Action callable to recursively install a directory.

    This is separate from the InstallDir function to allow the
    directory-walking to happen when installation is actually invoked,
    rather than when the SConscripts are parsed.  This still does not ensure
    that all necessary files are built as prerequisites to installing, but
    if one explicitly marks the install targets as dependent on the build
    targets, that should be enough.

    Parameters
    ----------
    ignoreRegex : `str`
        Regular expression to use to ignore files and directories.
    recursive : `bool`
        Control whether to recurse through directories.
    """

    def __init__(self, ignoreRegex, recursive):
        self.ignoreRegex = re.compile(ignoreRegex)
        self.recursive = recursive

    def __call__(self, target, source, env):
        prefix = os.path.abspath(os.path.join(target[0].abspath, ".."))
        destpath = os.path.join(target[0].abspath)
        if not os.path.isdir(destpath):
            state.log.info(f"Creating directory {destpath}")
            os.makedirs(destpath)
        for root, dirnames, filenames in os.walk(source[0].path):
            if not self.recursive:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames if d != ".svn"]  # ignore .svn tree
            for dirname in dirnames:
                destpath = os.path.join(prefix, root, dirname)
                if not os.path.isdir(destpath):
                    state.log.info(f"Creating directory {destpath}")
                    os.makedirs(destpath)
            for filename in filenames:
                if self.ignoreRegex.search(filename):
                    continue
                destpath = os.path.join(prefix, root)
                srcpath = os.path.join(root, filename)
                state.log.info(f"Copying {srcpath} to {destpath}")
                shutil.copy(srcpath, destpath)
        return 0


@memberOf(SConsEnvironment)
def InstallDir(self, prefix, dir, ignoreRegex=r"(~$|\.pyc$|\.os?$)", recursive=True):
    """Install the directory dir into prefix, ignoring certain files.

    Parameters
    ----------
    prefix : `str`
        Prefix to use for installation.
    dir : `str`
        Directory to install.
    ignoreRegex : `str`
        Regular expression to control whether a file is ignored.
    recursive : `bool`
        Recurse into directories?

    Returns
    -------
    result : `bool`
        Was installation successful?
    """
    if not self.installing:
        return []
    result = self.Command(
        target=os.path.join(self.Dir(prefix).abspath, dir),
        source=dir,
        action=DirectoryInstaller(ignoreRegex, recursive),
    )
    self.AlwaysBuild(result)
    return result


@memberOf(SConsEnvironment)
def InstallEups(env, dest, files=(), presetup=""):
    """Install a ups directory, setting absolute versions as appropriate
    (unless you're installing from the trunk, in which case no versions
    are expanded).

    Parameters
    ----------
    env : `SCons.Environment`
        Environment to use.
    dest : `str`
        Destination directory.
    files : `collections.abc.Sequence`, optional
        List of files to install.  Any build/table files present in ``./ups``
        are automatically added to this list.
    presetup : `dict`, optional
        A dictionary with keys product names and values the version that
        should be installed into the table files, overriding eups
        expandtable's usual behaviour.

    Returns
    -------
    acts : `list`
        Commands to execute.

    Notes
    -----
    Sample usage:

    .. code-block:: python

        env.InstallEups(
            os.path.join(env["prefix"], "ups"),
            presetup={"sconsUtils": env["version"]},
        )
    """
    acts = []
    if not env.installing:
        return acts

    if env.GetOption("clean"):
        state.log.warn("Removing" + dest)
        shutil.rmtree(dest, ignore_errors=True)
    else:
        presetupStr = []
        for p in presetup:
            presetupStr += [f"--product {p}={presetup[p]}"]
        presetup = " ".join(presetupStr)

        env = env.Clone(ENV=os.environ)
        #
        # Add any build/table/cfg files to the desired files
        #
        files = [str(f) for f in files]  # in case the user used Glob not glob.glob
        files += (
            glob.glob(os.path.join("ups", "*.build"))
            + glob.glob(os.path.join("ups", "*.table"))
            + glob.glob(os.path.join("ups", "*.cfg"))
            + glob.glob(os.path.join("ups", "eupspkg*"))
        )
        files = list(set(files))  # remove duplicates

        buildFiles = [f for f in files if re.search(r"\.build$", f)]
        build_obj = env.Install(dest, buildFiles)
        acts += build_obj

        tableFiles = [f for f in files if re.search(r"\.table$", f)]
        table_obj = env.Install(dest, tableFiles)
        acts += table_obj

        eupspkgFiles = [f for f in files if re.search(r"^eupspkg", f)]
        eupspkg_obj = env.Install(dest, eupspkgFiles)
        acts += eupspkg_obj

        miscFiles = [f for f in files if not re.search(r"\.(build|table)$", f)]
        misc_obj = env.Install(dest, miscFiles)
        acts += misc_obj

        try:
            import eups.lock

            path = eups.Eups.setEupsPath()
            if path:
                locks = eups.lock.takeLocks("setup", path, eups.lock.LOCK_SH)  # noqa F841 keep locks active
                env["ENV"]["EUPS_LOCK_PID"] = os.environ.get("EUPS_LOCK_PID", "-1")
        except ImportError:
            state.log.warn("Unable to import eups; not locking")

        eupsTargets = []

        for i in build_obj:
            env.AlwaysBuild(i)

            cmd = f"eups expandbuild -i --version {env['version']} "
            if "baseversion" in env:
                cmd += f" --repoversion {env['baseversion']} "
            cmd += str(i)
            eupsTargets.extend(env.AddPostAction(build_obj, env.Action(f"{cmd}", cmd)))

        for i in table_obj:
            env.AlwaysBuild(i)

            cmd = "eups expandtable -i -W '^(?!LOCAL:)' "  # version doesn't start "LOCAL:"
            if presetup:
                cmd += presetup + " "
            cmd += str(i)

            act = env.Command("table", "", env.Action(f"{cmd}", cmd))
            eupsTargets.extend(act)
            acts += act
            env.Depends(act, i)

        # By declaring that all the Eups operations create a file called
        # "eups" as a side-effect, even though they don't, SCons knows it
        # can't run them in parallel (it thinks of the  side-effect file as
        # something like a log, and knows you shouldn't be appending to it
        # in parallel).  When Eups locking is working, we may be able to
        # remove this.
        env.SideEffect("eups", eupsTargets)

    return acts


@memberOf(SConsEnvironment)
def InstallLSST(self, prefix, dirs, ignoreRegex=None):
    """Install directories in the usual LSST way, handling "ups" specially.

    Parameters
    ----------
    prefix : `str`
        Installation prefix.
    dirs : `list`
        Directories to install.
    ignoreRegex : `str`
        Regular expression for files and directories to ignore.

    Returns
    -------
    results : `list`
        Commands to execute.
    """
    results = []
    for d in dirs:
        # if eups is disabled, the .build & .table files will not be "expanded"
        if d == "ups" and not state.env["no_eups"]:
            t = self.InstallEups(os.path.join(prefix, "ups"))
        else:
            t = self.InstallDir(prefix, d, ignoreRegex=ignoreRegex)
        self.Depends(t, d)
        results.extend(t)
        self.Alias("install", t)
    self.Clean("install", prefix)
    return results
