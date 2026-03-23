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

import os

try:
    # Prefer to use native EUPS but if that is not available, fallback
    # versions are defined. Only a subset of EUPS functions are required
    # but all are imported to prevent warnings from redefinitions below.
    from eups import *  # noqa F403 F401

    eupsLoaded = True
except ImportError:
    eupsLoaded = False


def haveEups():
    return eupsLoaded


if not haveEups():
    #
    # Fake what we can so sconsUtils can limp along without eups
    #
    def flavor():
        from .state import env, log

        log.warn("Unable to import eups; guessing flavor")

        if env["PLATFORM"] == "posix":
            return os.uname()[0].title()
        else:
            return env["PLATFORM"].title()

    def productDir(name):
        return os.environ.get(f"{name.upper()}_DIR")

    def findSetupVersion(eupsProduct):
        return None, None, None, None, flavor()

    class _Eups:
        def __call__(self):
            return self

    Eups = _Eups()

    Eups.findSetupVersion = findSetupVersion

    class _Utils:
        pass

    utils = _Utils()

    def setupEnvNameFor(productName):
        return f"SETUP_{productName}"

    utils.setupEnvNameFor = setupEnvNameFor


def getEups():
    """Return a cached Eups instance, auto-creating if necessary."""
    try:
        return getEups._eups
    except AttributeError:
        getEups._eups = Eups()
        return getEups._eups
