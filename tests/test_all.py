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
import sys
import tempfile
import unittest


def _conda_prefix():
    """Return the conda environment pytest runs in, or `None`.

    Under scons ``CONDA_PREFIX`` is not forwarded to the tests (it is not in
    state.py's preserveVars), so fall back to the prefix of the running
    interpreter when that is a conda environment.
    """
    if os.environ.get("CONDA_PREFIX"):
        return os.environ["CONDA_PREFIX"]
    if os.path.isdir(os.path.join(sys.prefix, "conda-meta")):
        return sys.prefix
    return None


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

    @unittest.skipUnless(
        shutil.which("pkg-config") and _conda_prefix(),
        "pkg-config and a conda environment are required to build the testPkgConfig fixture",
    )
    def testPkgConfigPackage(self):
        fixture = os.path.join(os.path.dirname(__file__), "testPkgConfig")
        sconsEnv = dict(os.environ, CONDA_PREFIX=_conda_prefix())

        def clean():
            subprocess.run(
                ["scons", "-Q", "--clean"],
                cwd=fixture,
                env=sconsEnv,
                capture_output=True,
            )

        self.addCleanup(clean)

        def build():
            result = subprocess.run(
                ["scons", "-Q", "lib", "examples"],
                cwd=fixture,
                env=sconsEnv,
                capture_output=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"scons build of testPkgConfig fixture failed:\n"
                f"stdout:\n{result.stdout.decode()}\nstderr:\n{result.stderr.decode()}",
            )

        pc = os.path.join(fixture, "lib", "pkgconfig", "lsst_testPkgConfig.pc")
        build()
        self.assertTrue(os.path.exists(pc))
        self.assertTrue(os.path.exists(os.path.join(fixture, "examples", "hello")))
        # An unchanged .pc file is not rewritten.
        mtime = os.path.getmtime(pc)
        build()
        self.assertEqual(os.path.getmtime(pc), mtime)

        env = dict(sconsEnv, PKG_CONFIG_PATH=os.path.dirname(pc))
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

    def _configureFixtureCopy(self, modify):
        """Configure a modified copy of the testPkgConfig fixture with scons
        and return the completed process."""
        fixture = os.path.join(os.path.dirname(__file__), "testPkgConfig")
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "testPkgConfig")
            shutil.copytree(
                fixture, copy, ignore=shutil.ignore_patterns(".sconf_temp", ".sconsign.dblite", "config.log")
            )
            modify(copy)
            return subprocess.run(
                ["scons", "-Q", "lib"],
                cwd=copy,
                env=dict(os.environ, CONDA_PREFIX=_conda_prefix()),
                capture_output=True,
                text=True,
            )

    @unittest.skipUnless(
        shutil.which("pkg-config") and _conda_prefix(),
        "pkg-config and a conda environment are required to configure the testPkgConfig fixture",
    )
    def testPkgConfigConfigurationErrors(self):
        def addCfgFile(root):
            os.makedirs(os.path.join(root, "ups"))
            with open(os.path.join(root, "ups", "testPkgConfig.cfg"), "w") as f:
                f.write("")

        def dropVersionToken(root):
            template = os.path.join(root, "lsst_testPkgConfig.pc.in")
            with open(template) as f:
                contents = f.read()
            with open(template, "w") as f:
                f.write(contents.replace("@VERSION@", "1.0"))

        for modify, message in (
            (addCfgFile, "testPkgConfig.cfg"),
            (dropVersionToken, "does not contain the @VERSION@ token"),
        ):
            with self.subTest(modify=modify.__name__):
                result = self._configureFixtureCopy(modify)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
