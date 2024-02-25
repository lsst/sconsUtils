"""A simple python interface to git, using `os.popen`.

Based on the svn interface.

If ever we want to do anything clever, we should use one of
the supported python packages
"""

import os

from .. import state, utils


def guessVersionName():
    """Guess a version name.

    Returns
    -------
    name : `str`
        Descriptive name of the repository version state.
    """
    name = "unknown"

    if not os.path.exists(".git"):
        state.log.warn(f"Cannot guess version without .git directory; will be set to '{name}'.")
    else:
        name = utils.runExternal("git describe --always --dirty", fatal=False).strip()

    return name


def guessFingerprint():
    """Guess a unique fingerprint.

    Returns
    -------
    fingerprint : `str`
        SHA1 of current repository state.
    """
    fingerprint = "0x0"

    if not os.path.exists(".git"):
        state.log.warn(f"Cannot guess fingerprint without .git directory; will be set to '{fingerprint}'.")
    else:
        fingerprint = utils.runExternal(
            "git describe --match=" " --always --abbrev=0 --dirty", fatal=False
        ).strip()

    return fingerprint
