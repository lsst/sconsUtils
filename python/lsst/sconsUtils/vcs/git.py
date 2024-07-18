# This file is part of sconsUtils.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

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
        name = utils.runExternal("git describe --always --dirty --tags", fatal=False).strip()

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
