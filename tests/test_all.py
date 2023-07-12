#
# LSST Data Management System
# Copyright 2008, 2009, 2010 LSST Corporation.
#
# This product includes software developed by the
# LSST Project (http://www.lsst.org/).
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
# You should have received a copy of the LSST License Statement and
# the GNU General Public License along with this program.  If not,
# see <http://www.lsstcorp.org/LegalNotices/>.
#

"""
Tests for sconsUtils

Run with:
   python test_all.py
or by typing
   pytest
"""

import os
import subprocess
import unittest


class SconsUtilsTestCase(unittest.TestCase):
    """A test case for sconsUtils"""

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testCheckErrorCode(self):
        self.assertTrue(
            subprocess.call(
                """
                cd "%s/testFailedTests"
                scons > /dev/null 2>&1
            """
                % os.path.dirname(__file__),
                shell=True,
            ),
            "Failed to detect failed tests",
        )


if __name__ == "__main__":
    unittest.main()
