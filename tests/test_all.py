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
Tests for sconsUtils

Run with:
   python test_all.py
or by typing
   pytest
"""

import os
import shutil
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
                f"""
                cd "{os.path.dirname(__file__)}/testFailedTests"
                scons > /dev/null 2>&1
            """,
                shell=True,
            ),
            "Failed to detect failed tests",
        )

    # When this file is run under scons's own pytest invocation, the
    # environment scons forwards to that subprocess (state.py's
    # preserveVars) does not include CONDA_PREFIX, so this test always
    # skips there. It is instead exercised by a CI step that runs plain
    # pytest directly, where CONDA_PREFIX is present.
    @unittest.skipUnless(
        shutil.which("pkg-config") and os.environ.get("CONDA_PREFIX"),
        "pkg-config and a conda environment are required to build the testPkgConfig fixture",
    )
    def testPkgConfigPackage(self):
        fixture = os.path.join(os.path.dirname(__file__), "testPkgConfig")

        def clean():
            subprocess.run(
                ["scons", "-Q", "--clean"],
                cwd=fixture,
                capture_output=True,
            )

        self.addCleanup(clean)

        result = subprocess.run(
            ["scons", "-Q", "lib"],
            cwd=fixture,
            capture_output=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"scons build of testPkgConfig fixture failed:\n"
            f"stdout:\n{result.stdout.decode()}\nstderr:\n{result.stderr.decode()}",
        )

        pc = os.path.join(fixture, "lib", "pkgconfig", "lsst_testPkgConfig.pc")
        self.assertTrue(os.path.exists(pc))

        env = dict(os.environ, PKG_CONFIG_PATH=os.path.dirname(pc))
        version = subprocess.check_output(["pkg-config", "--modversion", "lsst_testPkgConfig"], env=env)
        version = version.decode().strip()
        self.assertNotEqual(version, "")
        self.assertNotIn("@VERSION@", version)

        # pkg-config does not normalize ${pcfiledir}/../.., so compare
        # realpaths.
        cflags = subprocess.check_output(["pkg-config", "--cflags", "lsst_testPkgConfig"], env=env)
        cflags = cflags.decode().split()
        self.assertEqual(
            [os.path.realpath(f[2:]) for f in cflags],
            [os.path.realpath(os.path.join(fixture, "include"))],
        )

        libs = subprocess.check_output(["pkg-config", "--libs", "lsst_testPkgConfig"], env=env)
        libs = libs.decode().split()
        self.assertEqual(os.path.realpath(libs[0][2:]), os.path.realpath(os.path.join(fixture, "lib")))
        self.assertEqual(libs[1:], ["-ltestPkgConfig"])

        clean()
        self.assertFalse(os.path.exists(pc), "Generated .pc file should be removed by scons --clean")


if __name__ == "__main__":
    unittest.main()
