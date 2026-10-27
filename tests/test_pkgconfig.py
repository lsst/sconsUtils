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
import subprocess
import tempfile
import unittest

import SCons.Environment
from lsst.sconsUtils.pkgconfig import (
    GENERATED_SHIM_SUBDIR,
    CyclicDependencyError,
    PkgConfig,
    PkgConfigDependencies,
    PkgConfigError,
    ResolvedDependencies,
    apply_to_env,
    build_search_path,
    cfg_path,
    check_single_format,
    main,
    output_path,
    remove_generated_pc,
    resolve,
    template_path,
    write_pc_from_template,
    write_shims,
)

#: Absolute path to the repository's top-level static shim directory.
_STATIC_SHIM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pkgconfig")


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


@unittest.skipUnless(shutil.which("pkg-config"), "pkg-config is not available on PATH")
class ResolveTestCase(unittest.TestCase):
    """Tests for `resolve`."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        # Resolve the temporary directory itself so that the only
        # difference between raw and realpath'd paths below is the
        # deliberate `/../` detour, not e.g. a symlinked /tmp.
        root = os.path.realpath(self._tmpdir.name)
        pcdir = os.path.join(root, "pkgconfig")
        self.conda = os.path.join(root, "conda")
        self.prim_inc = os.path.join(root, "prim", "include")
        # Written with a detour that pkg-config does not normalize.
        self.dep_inc_raw = os.path.join(root, "dep", "..", "dep", "include")
        self.dep_inc = os.path.join(root, "dep", "include")
        self.prim_inc_file = os.path.join(root, "prim", "doc", "prim.inc")
        self.dep_tag = os.path.join(root, "dep", "doc", "dep.tag")
        for directory in (
            pcdir,
            os.path.join(self.conda, "include", "eigen3"),
            self.prim_inc,
            self.dep_inc,
        ):
            os.makedirs(directory)

        write_pc(
            pcdir,
            "lsst_prim",
            f"includedir={self.prim_inc}\n"
            "lsst_build_requires=boost_test pybind11\n"
            f"doxygen_tag={root}/prim/doc/prim.tag\n"
            f"doxygen_include={self.prim_inc_file}\n"
            "\n"
            "Name: lsst_prim\nDescription: x\nVersion: 1.0\n"
            "Requires: lsst_dep eigen3\n"
            "Cflags: -I${includedir}\n"
            "Libs: -lprim\n",
        )
        write_pc(
            pcdir,
            "lsst_dep",
            f"includedir={self.dep_inc_raw}\n"
            f"doxygen_tag={self.dep_tag}\n"
            "lsst_test_libs=-lboost_unit_test_framework\n"
            "\n"
            "Name: lsst_dep\nDescription: x\nVersion: 2.0\n"
            "Cflags: -I${includedir}\n"
            "Libs: -ldep\n",
        )
        write_pc(
            pcdir,
            "eigen3",
            f"Name: eigen3\nDescription: x\nVersion: 3.4\nCflags: -I{self.conda}/include/eigen3\nLibs:\n",
        )
        write_pc(
            pcdir,
            "boost_test",
            "lsst_test_libs=-lboost_unit_test_framework\n"
            "\n"
            f"Name: boost_test\nDescription: x\nVersion: 1.86\nCflags: -I{self.conda}/include\nLibs:\n",
        )
        write_pc(
            pcdir,
            "pybind11",
            "lsst_python_libs=-lpython_extra\n"
            "\n"
            f"Name: pybind11\nDescription: x\nVersion: 2.13\nCflags: -I{self.conda}/include\nLibs:\n",
        )
        write_pc(
            pcdir,
            "lsst_prim2",
            "lsst_build_requires=nonexistent_mod\n"
            "\n"
            "Name: lsst_prim2\nDescription: x\nVersion: 1.0\nCflags:\nLibs:\n",
        )
        self.pc = PkgConfig([pcdir], conda_prefix=self.conda)

    def test_modules_and_versions(self):
        r = resolve("prim", self.pc, self.conda)
        self.assertEqual(r.modules, ["lsst_prim", "lsst_dep", "eigen3", "boost_test", "pybind11"])
        self.assertEqual(set(r.versions), {"prim", "dep", "eigen3", "boost_test", "pybind11"})
        self.assertEqual(r.versions["dep"], "2.0")
        self.assertEqual(r.versions["eigen3"], "3.4")

    def test_include_routing(self):
        r = resolve("prim", self.pc, self.conda)
        # Guard: the detour really is there, so the assertion below fails
        # unless realpath normalization is applied.
        self.assertNotEqual(self.dep_inc_raw, os.path.realpath(self.dep_inc_raw))
        self.assertEqual(r.cpppath, [os.path.realpath(self.prim_inc), os.path.realpath(self.dep_inc_raw)])
        # <conda>/include is claimed by both boost_test and pybind11 but
        # must appear exactly once.
        self.assertEqual(
            r.xcpppath,
            [
                os.path.realpath(os.path.join(self.conda, "include", "eigen3")),
                os.path.realpath(os.path.join(self.conda, "include")),
            ],
        )

    def test_conda_include_always_external(self):
        # Even if an lsst_* module claims <conda>/include as its includedir
        # (the container case), it must still route to xcpppath.
        pcdir = os.path.join(os.path.dirname(self.conda), "pkgconfig")
        write_pc(
            pcdir,
            "lsst_inst",
            f"includedir={self.conda}/include\n"
            "\n"
            "Name: lsst_inst\nDescription: x\nVersion: 1.0\n"
            "Cflags: -I${includedir}\nLibs: -linst\n",
        )
        r = resolve("inst", self.pc, self.conda)
        self.assertEqual(r.cpppath, [])
        self.assertEqual(r.xcpppath, [os.path.realpath(os.path.join(self.conda, "include"))])

    def test_lib_categories(self):
        r = resolve("prim", self.pc, self.conda)
        self.assertEqual(r.libs["main"], ["prim", "dep"])
        # Review Focus 5: declared by both lsst_dep and boost_test.
        self.assertEqual(r.libs["test"], ["boost_unit_test_framework"])
        self.assertEqual(r.libs["python"], ["python_extra"])

    def test_doxygen(self):
        r = resolve("prim", self.pc, self.conda)
        # The primary's own tag is excluded.
        self.assertEqual(r.doxygen["tags"], [self.dep_tag])
        self.assertEqual(r.doxygen["includes"], [self.prim_inc_file])

    def test_missing_build_require_names_module(self):  # Review Focus 4
        with self.assertRaises(PkgConfigError) as cm:
            resolve("prim2", self.pc, self.conda)
        self.assertIn("nonexistent_mod", str(cm.exception))

    def test_missing_primary_names_module(self):
        with self.assertRaises(PkgConfigError) as cm:
            resolve("absent", self.pc, self.conda)
        self.assertIn("lsst_absent", str(cm.exception))

    def test_without_build_requires(self):
        r = resolve("prim", self.pc, self.conda, include_build_requires=False)
        self.assertEqual(r.modules, ["lsst_prim", "lsst_dep", "eigen3"])
        self.assertEqual(r.libs["python"], [])
        # lsst_dep still contributes its test libraries.
        self.assertEqual(r.libs["test"], ["boost_unit_test_framework"])
        self.assertEqual(r.xcpppath, [os.path.realpath(os.path.join(self.conda, "include", "eigen3"))])


class TemplateTestCase(unittest.TestCase):
    """Tests for template discovery and `.pc` generation."""

    def test_paths(self):
        self.assertEqual(template_path("/r", "afw"), "/r/lsst_afw.pc.in")
        self.assertEqual(cfg_path("/r", "afw"), "/r/ups/afw.cfg")
        self.assertEqual(output_path("/r", "afw"), "/r/lib/pkgconfig/lsst_afw.pc")

    def test_both_formats_is_error(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "ups"))
            with open(template_path(root, "afw"), "w") as f:
                f.write("Name: lsst_afw\n")
            with open(cfg_path(root, "afw"), "w") as f:
                f.write("")
            with self.assertRaises(PkgConfigError) as cm:
                check_single_format(root, "afw")
            self.assertIn("lsst_afw.pc.in", str(cm.exception))
            self.assertIn("afw.cfg", str(cm.exception))

    def test_neither_format_is_fine(self):
        with tempfile.TemporaryDirectory() as root:
            # Neither file exists; should not raise.
            check_single_format(root, "afw")

    def test_only_template_is_fine(self):
        with tempfile.TemporaryDirectory() as root:
            with open(template_path(root, "afw"), "w") as f:
                f.write("Name: lsst_afw\n")
            check_single_format(root, "afw")

    def test_only_cfg_is_fine(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "ups"))
            with open(cfg_path(root, "afw"), "w") as f:
                f.write("")
            check_single_format(root, "afw")

    @unittest.skipUnless(shutil.which("pkg-config"), "pkg-config is not available on PATH")
    def test_write_substitutes_version_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            tmpl = os.path.join(root, "lsst_x.pc.in")
            out = os.path.join(root, "lib", "pkgconfig", "lsst_x.pc")
            with open(tmpl, "w") as f:
                f.write("Name: lsst_x\nDescription: d\nVersion: @VERSION@\nCflags:\nLibs:\n")

            self.assertTrue(write_pc_from_template(tmpl, out, "g1234+5"))
            with open(out) as f:
                self.assertIn("Version: g1234+5\n", f.read())

            mtime_after_first_write = os.path.getmtime(out)

            self.assertFalse(write_pc_from_template(tmpl, out, "g1234+5"))
            self.assertEqual(os.path.getmtime(out), mtime_after_first_write)

            # And pkg-config reads it back correctly.
            self.assertEqual(
                PkgConfig([os.path.dirname(out)], "/c").modversion("lsst_x"),
                "g1234+5",
            )

    def test_unknown_version_is_written(self):
        with tempfile.TemporaryDirectory() as root:
            tmpl = os.path.join(root, "lsst_x.pc.in")
            out = os.path.join(root, "lib", "pkgconfig", "lsst_x.pc")
            with open(tmpl, "w") as f:
                f.write("Name: lsst_x\nDescription: d\nVersion: @VERSION@\nCflags:\nLibs:\n")

            self.assertTrue(write_pc_from_template(tmpl, out, "unknown"))
            with open(out) as f:
                self.assertIn("Version: unknown\n", f.read())

    def test_missing_token_fails(self):
        with tempfile.TemporaryDirectory() as root:
            tmpl = os.path.join(root, "lsst_x.pc.in")
            out = os.path.join(root, "lib", "pkgconfig", "lsst_x.pc")
            with open(tmpl, "w") as f:
                f.write("Name: lsst_x\nDescription: d\nVersion: 1\nCflags:\nLibs:\n")

            with self.assertRaises(PkgConfigError) as cm:
                write_pc_from_template(tmpl, out, "1")
            self.assertIn(tmpl, str(cm.exception))


@unittest.skipUnless(shutil.which("pkg-config"), "pkg-config is not available on PATH")
class ShimTestCase(unittest.TestCase):
    """Tests for `write_shims` and the console script `main`."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.target = os.path.join(self._tmpdir.name, "shims")

    def _pkg_config(self, *args):
        """Run the real ``pkg-config`` binary with no ``--define-variable``,
        so that a shim's own ``conda_prefix`` default is exercised."""
        env = dict(os.environ)
        env["PKG_CONFIG_PATH"] = self.target
        return subprocess.run(
            ["pkg-config", *args], env=env, capture_output=True, text=True, check=True
        ).stdout

    def _cflags(self, module):
        return self._pkg_config("--cflags", module)

    def _libs(self, module):
        return self._pkg_config("--libs", module)

    def _variable(self, module, name):
        return self._pkg_config(f"--variable={name}", module).strip()

    def test_static_shims_resolve_from_copy(self):
        written = write_shims(self.target, static_dir=_STATIC_SHIM_DIR)
        for name in (
            "boost",
            "boost_test",
            "boost_timer",
            "boost_math",
            "boost_regex",
            "boost_filesystem",
            "boost_system",
            "boost_thread",
            "boost_program_options",
            "boost_serialization",
            "minuit2",
            "ndarray",
        ):
            self.assertIn(os.path.join(self.target, f"{name}.pc"), written)

        self.assertEqual(self._cflags("minuit2").split(), ["-I" + self.target + "/../../include/Minuit2"])
        # boost_test.pc itself has an empty Libs:, but it Requires: boost,
        # and pkg-config propagates a required module's Libs, so the
        # effective link line still carries boost's own -lpthread.
        self.assertEqual(self._libs("boost_test").strip(), "-lpthread")
        self.assertEqual(self._variable("boost_test", "lsst_test_libs"), "-lboost_unit_test_framework")
        self.assertEqual(self._libs("boost_math").split(), ["-lboost_math_c99", "-lpthread"])
        self.assertEqual(self._libs("boost").strip(), "-lpthread")

    def test_generated_numpy(self):
        written = write_shims(self.target, static_dir=_STATIC_SHIM_DIR)
        self.assertIn(os.path.join(self.target, "numpy.pc"), written)
        inc = (
            subprocess.check_output(["python", "-c", "import numpy; print(numpy.get_include())"])
            .decode()
            .strip()
        )
        self.assertEqual(PkgConfig([self.target], "/c").cflags_only_I(["numpy"]), [inc])

    @unittest.skipUnless(shutil.which("ast_link"), "ast_link is not available on PATH")
    @unittest.skipUnless(os.environ.get("CONDA_PREFIX"), "CONDA_PREFIX is not set")
    def test_generated_starlink_ast(self):
        written = write_shims(self.target, static_dir=_STATIC_SHIM_DIR)
        self.assertIn(os.path.join(self.target, "starlink_ast.pc"), written)
        conda_prefix = os.environ["CONDA_PREFIX"]
        self.assertEqual(
            PkgConfig([self.target], conda_prefix).cflags_only_I(["starlink_ast"]),
            [os.path.join(conda_prefix, "include", "star")],
        )

    def test_rewrite_leaves_unchanged_file_untouched(self):
        write_shims(self.target, static_dir=_STATIC_SHIM_DIR)
        boost_pc = os.path.join(self.target, "boost.pc")
        mtime_after_first_write = os.path.getmtime(boost_pc)

        write_shims(self.target, static_dir=_STATIC_SHIM_DIR)
        self.assertEqual(os.path.getmtime(boost_pc), mtime_after_first_write)

    def test_no_static_dir_copies_nothing(self):
        # Simulate the container case, where SCONSUTILS_DIR is unset (or
        # unusable) and no static_dir is passed explicitly: static_shim_dir
        # falls back to None and nothing is copied.
        previous = os.environ.pop("SCONSUTILS_DIR", None)
        self.addCleanup(lambda: previous is not None and os.environ.__setitem__("SCONSUTILS_DIR", previous))
        written = write_shims(self.target, static_dir=None)
        self.assertFalse(os.path.exists(os.path.join(self.target, "boost.pc")))
        # numpy is still generated, since it does not depend on static_dir.
        self.assertIn(os.path.join(self.target, "numpy.pc"), written)

    def test_console_script(self):
        target2 = os.path.join(self._tmpdir.name, "shims2")
        self.assertEqual(main([target2]), 0)
        self.assertTrue(os.path.exists(os.path.join(target2, "boost.pc")))


def make_resolved() -> ResolvedDependencies:
    """Return a small `ResolvedDependencies` for environment tests."""
    return ResolvedDependencies(
        modules=["lsst_m"],
        cpppath=["/a"],
        xcpppath=["/b"],
        ccflags=["-DX"],
        libpath=["/l"],
        linkflags=["-Wl,-z"],
        libs={"main": ["m"], "python": [], "test": ["t"]},
        doxygen={"tags": [], "includes": []},
        versions={"m": "1"},
    )


class ApplyToEnvTestCase(unittest.TestCase):
    """Tests for `apply_to_env`."""

    def test_apply(self):
        env = SCons.Environment.Environment(tools=[])
        env["CPPPATH"] = ["/already"]
        env["XCPPPATH"] = []
        env["LIBPATH"] = []
        resolved = make_resolved()
        apply_to_env(env, resolved)
        self.assertEqual(env["CPPPATH"], ["/a", "/already"])
        self.assertEqual(env["XCPPPATH"], ["/b"])
        self.assertEqual(env["LIBPATH"], ["/l"])
        self.assertEqual(env["CCFLAGS"], ["-DX"])
        self.assertEqual(env["LINKFLAGS"], ["-Wl,-z"])
        self.assertEqual(env.libs, {"main": ["m"], "python": [], "test": ["t"]})
        self.assertEqual(env.doxygen, {"tags": [], "includes": []})
        # The environment gets its own copies of the library lists.
        env.libs["main"].append("extra")
        self.assertEqual(resolved.libs["main"], ["m"])


class PkgConfigDependenciesTestCase(unittest.TestCase):
    """Tests for `PkgConfigDependencies`."""

    def test_versions(self):
        resolved = make_resolved()
        d = PkgConfigDependencies("afw", resolved)
        self.assertEqual(d.name, "afw")
        self.assertIs(d.resolved, resolved)
        self.assertEqual(d.versions, {"m": "1"})


class RemoveGeneratedPcTestCase(unittest.TestCase):
    """Tests for `remove_generated_pc`."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.root = self._tmpdir.name
        self.output = output_path(self.root, "afw")
        self.pcdir = os.path.dirname(self.output)

    def test_removes_file_and_empty_directory(self):
        os.makedirs(self.pcdir)
        with open(self.output, "w") as f:
            f.write("x")
        self.assertTrue(remove_generated_pc(self.root, "afw"))
        self.assertFalse(os.path.exists(self.output))
        self.assertFalse(os.path.exists(self.pcdir))
        # lib/ itself is left alone.
        self.assertTrue(os.path.isdir(os.path.join(self.root, "lib")))

    def test_keeps_non_empty_directory(self):
        os.makedirs(self.pcdir)
        with open(self.output, "w") as f:
            f.write("x")
        other = os.path.join(self.pcdir, "other.pc")
        with open(other, "w") as f:
            f.write("y")
        self.assertTrue(remove_generated_pc(self.root, "afw"))
        self.assertFalse(os.path.exists(self.output))
        self.assertTrue(os.path.exists(other))

    def test_missing_file(self):
        self.assertFalse(remove_generated_pc(self.root, "afw"))
        os.makedirs(self.pcdir)
        self.assertFalse(remove_generated_pc(self.root, "afw"))
        # An empty directory not holding our file is left alone.
        self.assertTrue(os.path.isdir(self.pcdir))


if __name__ == "__main__":
    unittest.main()
