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

"""A simple python interface to hg (Mercurial), using `os.popen`

Based on the svn interface.

If ever we want to do anything clever, we should use one of
the supported svn/python packages
"""

import os
import re

from .. import state, utils


def guessVersionName():
    """Guess a version name.

    Returns
    -------
    name : `str`
        Descriptive name of the repository version state.
    """
    version = "unknown"
    if not os.path.exists(".hg"):
        state.log.warn(f"Cannot guess version without .hg directory; will be set to '{version}'.")
        return version

    idents = utils.runExternal("hg id", fatal=True)
    ident = re.split(r"\s+", idents)
    if len(ident) == 0:
        raise RuntimeError("Unable to determine hg version")

    if re.search(r"\+", ident[0]):
        raise RuntimeError("Error with hg version: uncommitted changes")

    if len(ident) == 1:
        # Somehow, this is all we've got...
        return ident[0]

    # Prefer tag name to branch name; branch names get printed in parens
    index = 1
    while ident[index].startswith("(") and ident[index].endswith(")") and len(ident) > index + 1:
        index += 1

    # Prefer hash to "tip"
    if ident[index] == "tip":
        return ident[0]

    return ident[index]


def guessFingerprint():
    """Guess a unique fingerprint.

    Returns
    -------
    fingerprint : `str`
        SHA1 of current repository state.
    """
    fingerprint = "0x0"
    if not os.path.exists(".hg"):
        state.log.warn(f"Cannot guess fingerprint without .hg directory; will be set to '{fingerprint}'.")
    else:
        idents = utils.runExternal("hg id", fatal=True)
        ident = re.split(r"\s+", idents)
        if len(ident) == 0:
            raise RuntimeError("Unable to determine hg version")

        fingerprint = utils.runExternal("hg ident --id", fatal=True).strip()
        if re.search(r"\+", ident[0]):
            fingerprint += " *"

    return fingerprint
