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

"""
Very simple tests to show that the test running
infrastructure can run more than one test file.
There is nothing scons-specific about these tests.
"""

import os
import unittest


class SimplestPossibleTestCase(unittest.TestCase):
    """Tests that don't rely on any external code."""

    def testSimple(self):
        self.assertEqual(2 + 2, 4)

    def testEnvironment(self):
        """Test the environment. The test will fail if the tests are run
        by anything other than SCons."""
        envVar = "XDG_CACHE_HOME"
        self.assertIn(envVar, os.environ)
        self.assertTrue(os.path.exists(os.environ[envVar]), f"Check path {os.environ[envVar]}")

    def testNoImplicitMultithreading(self):
        """Test that the environment has turned off implicit
        multithreading.
        """
        envVar = "OMP_NUM_THREADS"
        self.assertIn(envVar, os.environ)
        self.assertEqual(os.environ[envVar], "1")

        try:
            import numexpr
        except ImportError:
            numexpr = None

        if numexpr:
            self.assertEqual(numexpr.utils.get_num_threads(), 1)


if __name__ == "__main__":
    unittest.main()
