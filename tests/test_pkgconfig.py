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

"""Tests for `lsst.sconsUtils.pkgconfig`."""

import os
import shutil
import tempfile
import unittest

from lsst.sconsUtils.pkgconfig import (
    GENERATED_SHIM_SUBDIR,
    CyclicDependencyError,
    PkgConfig,
    PkgConfigError,
    build_search_path,
)


def write_pc(directory: str, name: str, body: str) -> str:
    """Write ``<directory>/<name>.pc`` with ``body`` and return its path."""
    path = os.path.join(directory, f"{name}.pc")
    with open(path, "w") as f:
        f.write(body)
    return path


@unittest.skipUnless(shutil.which("pkg-config"), "pkg-config is not available on PATH")
class SearchPathTestCase(unittest.TestCase):
    """Tests for `build_search_path`."""

    def test_order(self):
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as foo_dir,
            tempfile.TemporaryDirectory() as bar_dir,
            tempfile.TemporaryDirectory() as sconsutils_dir,
        ):
            os.makedirs(os.path.join(root, "lib", "pkgconfig"))
            os.makedirs(os.path.join(foo_dir, "lib", "pkgconfig"))
            # bar_dir deliberately has no lib/pkgconfig subdirectory.
            os.makedirs(os.path.join(sconsutils_dir, "pkgconfig"))

            environ = {
                "FOO_DIR": foo_dir,
                "BAR_DIR": bar_dir,
                "SCONSUTILS_DIR": sconsutils_dir,
                "PKG_CONFIG_PATH": "/x:/y",
            }
            path = build_search_path(root, environ)
            self.assertEqual(
                path,
                [
                    os.path.join(root, "lib", "pkgconfig"),
                    os.path.join(foo_dir, "lib", "pkgconfig"),
                    os.path.join(sconsutils_dir, "pkgconfig"),
                    os.path.join(root, GENERATED_SHIM_SUBDIR),
                    "/x",
                    "/y",
                ],
            )

    def test_dir_extra_is_ignored(self):
        with (
            tempfile.TemporaryDirectory() as root,
            tempfile.TemporaryDirectory() as foo_dir_extra,
        ):
            # Create the lib/pkgconfig subdirectory so that, if the
            # `_EXTRA` guard were removed, `os.path.isdir` would not be
            # the thing hiding the bug: the entry would actually appear.
            os.makedirs(os.path.join(foo_dir_extra, "lib", "pkgconfig"))
            environ = {
                "FOO_DIR_EXTRA": foo_dir_extra,
            }
            path = build_search_path(root, environ)
            for entry in path:
                self.assertNotIn(foo_dir_extra, entry)

    def test_deduplicates_preserving_first_occurrence(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "lib", "pkgconfig"))
            # FOO_DIR happens to point at the build root itself, so
            # <FOO_DIR>/lib/pkgconfig duplicates <build root>/lib/pkgconfig.
            environ = {
                "FOO_DIR": root,
            }
            path = build_search_path(root, environ)
            self.assertEqual(path.count(os.path.join(root, "lib", "pkgconfig")), 1)
            self.assertEqual(path[0], os.path.join(root, "lib", "pkgconfig"))


@unittest.skipUnless(shutil.which("pkg-config"), "pkg-config is not available on PATH")
class PkgConfigRunnerTestCase(unittest.TestCase):
    """Tests for `PkgConfig`."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.d = self._tmpdir.name
        self.addCleanup(self._tmpdir.cleanup)

    def test_exists_and_modversion(self):
        write_pc(self.d, "alpha", "Name: alpha\nDescription: x\nVersion: 1.2\nCflags:\nLibs:\n")
        pc = PkgConfig([self.d], conda_prefix="/opt/conda")
        self.assertTrue(pc.exists("alpha"))
        self.assertFalse(pc.exists("missing"))
        self.assertEqual(pc.modversion("alpha"), "1.2")

    def test_variable_none_when_unset(self):
        write_pc(self.d, "alpha", "Name: alpha\nDescription: x\nVersion: 1.2\nCflags:\nLibs:\n")
        pc = PkgConfig([self.d], conda_prefix="/opt/conda")
        self.assertIsNone(pc.variable("alpha", "lsst_build_requires"))

    def test_conda_prefix_define_variable(self):
        write_pc(
            self.d,
            "beta",
            "Name: beta\nDescription: x\nVersion: 0\nCflags: -I${conda_prefix}/include/beta\nLibs:\n",
        )
        pc = PkgConfig([self.d], conda_prefix="/opt/conda")
        self.assertEqual(pc.run("--cflags-only-I", "beta").split(), ["-I/opt/conda/include/beta"])

    def test_run_failure_raises(self):
        pc = PkgConfig([self.d], conda_prefix="/opt/conda")
        with self.assertRaises(PkgConfigError) as cm:
            pc.run("--cflags", "missing")
        # pkg-config 0.29.2's stderr for a missing module includes this
        # sentence; assert on it so the exception message is confirmed to
        # carry pkg-config's actual stderr, not just the echoed arguments.
        self.assertIn("was not found in the pkg-config search path", str(cm.exception))

    def test_no_conda_prefix_fails(self):
        with self.assertRaises(PkgConfigError):
            PkgConfig([self.d], conda_prefix=None)


@unittest.skipUnless(shutil.which("pkg-config"), "pkg-config is not available on PATH")
class ClosureTestCase(unittest.TestCase):
    """Tests for `PkgConfig.closure` and `PkgConfig.requires`."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.d = self._tmpdir.name
        self.addCleanup(self._tmpdir.cleanup)
        # top -> mid -> leaf ; top -> leaf (leaf reachable by two paths,
        # must appear only once in the closure) ; side is independent.
        write_pc(self.d, "leaf", "Name: leaf\nDescription: x\nVersion: 1.0\nCflags:\nLibs:\n")
        write_pc(
            self.d,
            "mid",
            "Name: mid\nDescription: x\nVersion: 1.0\nRequires: leaf\nCflags:\nLibs:\n",
        )
        write_pc(
            self.d,
            "top",
            "Name: top\nDescription: x\nVersion: 1.0\nRequires: mid, leaf\nCflags:\nLibs:\n",
        )
        write_pc(self.d, "side", "Name: side\nDescription: x\nVersion: 1.0\nCflags:\nLibs:\n")
        # a -> b -> a is a cycle.
        write_pc(self.d, "a", "Name: a\nDescription: x\nVersion: 1.0\nRequires: b\nCflags:\nLibs:\n")
        write_pc(self.d, "b", "Name: b\nDescription: x\nVersion: 1.0\nRequires: a\nCflags:\nLibs:\n")
        self.pc = PkgConfig([self.d], conda_prefix="/opt/conda")

    def test_closure_order(self):
        self.assertEqual(self.pc.closure(["top", "side"]), ["top", "mid", "leaf", "side"])

    def test_cycle_detected(self):
        with self.assertRaises(CyclicDependencyError) as cm:
            self.pc.closure(["a"])
        self.assertIn("a", str(cm.exception))
        self.assertIn("b", str(cm.exception))


@unittest.skipUnless(shutil.which("pkg-config"), "pkg-config is not available on PATH")
class FlagQueryTestCase(unittest.TestCase):
    """Tests for the ``*_only_*`` flag query methods on `PkgConfig`."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.d = self._tmpdir.name
        self.addCleanup(self._tmpdir.cleanup)
        write_pc(
            self.d,
            "leaf",
            "Name: leaf\nDescription: x\nVersion: 1.0\nCflags: -I/inc/leaf\nLibs: -L/lib/leaf -lleaf\n",
        )
        write_pc(
            self.d,
            "top",
            "Name: top\nDescription: x\nVersion: 1.0\nRequires: leaf\n"
            "Cflags: -I/inc/top -DTOP\n"
            "Libs: -L/lib/top -ltop -Wl,-rpath,/lib/top\n",
        )
        self.pc = PkgConfig([self.d], conda_prefix="/opt/conda")

    def test_split_queries(self):
        self.assertEqual(self.pc.cflags_only_I(["top"]), ["/inc/top", "/inc/leaf"])
        self.assertEqual(self.pc.cflags_only_other(["top"]), ["-DTOP"])
        self.assertEqual(self.pc.libs_only_L(["top"]), ["/lib/top", "/lib/leaf"])
        self.assertEqual(self.pc.libs_only_l(["top"]), ["top", "leaf"])
        self.assertEqual(self.pc.libs_only_other(["top"]), ["-Wl,-rpath,/lib/top"])

    def test_empty_modules_returns_empty_without_invoking(self):
        self.assertEqual(self.pc.cflags_only_I([]), [])
        self.assertEqual(self.pc.cflags_only_other([]), [])
        self.assertEqual(self.pc.libs_only_L([]), [])
        self.assertEqual(self.pc.libs_only_l([]), [])
        self.assertEqual(self.pc.libs_only_other([]), [])


if __name__ == "__main__":
    unittest.main()
