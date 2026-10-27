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

"""pkg-config support for sconsUtils.

This module knows how to construct the ``PKG_CONFIG_PATH`` search path
sconsUtils uses for every pkg-config invocation, and how to run
``pkg-config`` itself.  It is deliberately free of any SCons import so
that it can be unit tested with plain ``pytest`` and reused outside of
an SCons build.
"""

from __future__ import annotations

__all__ = (
    "GENERATED_SHIM_SUBDIR",
    "MODULE_PREFIX",
    "TEMPLATE_SUFFIX",
    "VERSION_TOKEN",
    "CyclicDependencyError",
    "PkgConfig",
    "PkgConfigDependencies",
    "PkgConfigError",
    "ResolvedDependencies",
    "apply_to_env",
    "build_search_path",
    "cfg_path",
    "check_single_format",
    "main",
    "module_name",
    "output_path",
    "remove_generated_pc",
    "resolve",
    "static_shim_dir",
    "template_path",
    "write_pc_from_template",
    "write_shims",
)

import argparse
import dataclasses
import glob
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

#: Prefix applied to an EUPS product name to get its pkg-config module name.
MODULE_PREFIX = "lsst_"

#: Suffix of a pkg-config template file, relative to a package's build root.
TEMPLATE_SUFFIX = ".pc.in"

#: Token substituted with the real version string in a template file.
VERSION_TOKEN = "@VERSION@"

#: Subdirectory, relative to a build root, holding configure-time shims.
GENERATED_SHIM_SUBDIR = os.path.join(".sconf_temp", "pkgconfig")

# Matches the same `<name>_DIR` / `<name>_DIR_EXTRA` environment variables
# that `state.py` scans when building the EUPS configuration search path.
_DIR_VAR_RE = re.compile(r"^(?P<name>\w+)_DIR(?P<extra>_EXTRA)?$")


class PkgConfigError(RuntimeError):
    """Raised when invoking pkg-config fails or is misconfigured."""


class CyclicDependencyError(PkgConfigError):
    """Raised when `PkgConfig.closure` finds a cycle in ``Requires``.

    The exception message lists the modules on the cycle, in path order,
    e.g. ``"a -> b -> a"``.
    """


def module_name(package_name: str) -> str:
    """Return the pkg-config module name for an EUPS package.

    Parameters
    ----------
    package_name : `str`
        The EUPS product name, e.g. ``"afw"``.

    Returns
    -------
    name : `str`
        The pkg-config module name, e.g. ``"lsst_afw"``.
    """
    return MODULE_PREFIX + package_name


def template_path(build_root: str, package_name: str) -> str:
    """Return the path of a package's pkg-config template file.

    Parameters
    ----------
    build_root : `str`
        Absolute path to the root of the package currently being built.
    package_name : `str`
        The EUPS product name, e.g. ``"afw"``.

    Returns
    -------
    path : `str`
        The path of the template, e.g. ``"<build_root>/lsst_afw.pc.in"``.
    """
    return os.path.join(build_root, module_name(package_name) + TEMPLATE_SUFFIX)


def cfg_path(build_root: str, package_name: str) -> str:
    """Return the path of a package's legacy ``ups/<name>.cfg`` file.

    Parameters
    ----------
    build_root : `str`
        Absolute path to the root of the package currently being built.
    package_name : `str`
        The EUPS product name, e.g. ``"afw"``.

    Returns
    -------
    path : `str`
        The path of the ``.cfg`` file, e.g. ``"<build_root>/ups/afw.cfg"``.
    """
    return os.path.join(build_root, "ups", package_name + ".cfg")


def output_path(build_root: str, package_name: str) -> str:
    """Return the path of a package's generated ``.pc`` file.

    Parameters
    ----------
    build_root : `str`
        Absolute path to the root of the package currently being built.
    package_name : `str`
        The EUPS product name, e.g. ``"afw"``.

    Returns
    -------
    path : `str`
        The path of the generated file, e.g.
        ``"<build_root>/lib/pkgconfig/lsst_afw.pc"``.
    """
    return os.path.join(build_root, "lib", "pkgconfig", module_name(package_name) + ".pc")


def check_single_format(build_root: str, package_name: str) -> None:
    """Check that a package uses at most one dependency-description format.

    Parameters
    ----------
    build_root : `str`
        Absolute path to the root of the package currently being built.
    package_name : `str`
        The EUPS product name, e.g. ``"afw"``.

    Raises
    ------
    PkgConfigError
        Raised if both `template_path` and `cfg_path` exist for
        `package_name`, naming both paths.  Nothing is raised if zero or
        one of the two files exists.
    """
    template = template_path(build_root, package_name)
    cfg = cfg_path(build_root, package_name)
    if os.path.exists(template) and os.path.exists(cfg):
        raise PkgConfigError(
            f"Package {package_name!r} has both a pkg-config template ({template}) and a "
            f"legacy configuration file ({cfg}); a package must use only one of the two formats."
        )


def write_pc_from_template(template: str, output: str, version: str) -> bool:
    """Write a ``.pc`` file from a template, substituting the version.

    Parameters
    ----------
    template : `str`
        Path of the template file to read.  Every occurrence of
        `VERSION_TOKEN` is replaced with `version`; no other substitution
        is performed.
    output : `str`
        Path of the ``.pc`` file to write.  Its parent directory is
        created if it does not already exist.
    version : `str`
        The version string to substitute for `VERSION_TOKEN`.

    Returns
    -------
    wrote : `bool`
        `True` if `output` was written or overwritten, `False` if its
        content already matched the substituted template and it was left
        untouched.

    Raises
    ------
    PkgConfigError
        Raised if `VERSION_TOKEN` does not appear anywhere in `template`,
        naming `template`.
    """
    with open(template) as f:
        contents = f.read()
    if VERSION_TOKEN not in contents:
        raise PkgConfigError(f"Template {template} does not contain the {VERSION_TOKEN} token")
    new_contents = contents.replace(VERSION_TOKEN, version)

    if os.path.exists(output):
        with open(output) as f:
            existing_contents = f.read()
        if existing_contents == new_contents:
            return False

    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w") as f:
        f.write(new_contents)
    return True


def remove_generated_pc(build_root: str, package_name: str) -> bool:
    """Remove a package's generated ``.pc`` file, as ``scons --clean`` does.

    Parameters
    ----------
    build_root : `str`
        Absolute path to the root of the package currently being built.
    package_name : `str`
        The EUPS product name, e.g. ``"afw"``.

    Returns
    -------
    removed : `bool`
        `True` if `output_path` existed and was removed, `False` if there
        was nothing to remove.  When the file is removed and its
        ``lib/pkgconfig`` directory is left empty, that directory is
        removed too; ``lib/`` itself is never touched.

    Notes
    -----
    Only this one file is removed, rather than every ``*.pc`` file in the
    tree, so that ``.pc`` files tracked in a package's repository (such as
    sconsUtils's own static shims) survive a clean.
    """
    output = output_path(build_root, package_name)
    if not os.path.exists(output):
        return False
    os.remove(output)
    directory = os.path.dirname(output)
    if not os.listdir(directory):
        os.rmdir(directory)
    return True


def _dedup_preserve_order(entries: list[str]) -> list[str]:
    """Remove duplicate entries, keeping the first occurrence of each."""
    seen: set[str] = set()
    result: list[str] = []
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        result.append(entry)
    return result


def build_search_path(build_root: str, environ: Mapping[str, str]) -> list[str]:
    """Build the ``PKG_CONFIG_PATH`` search path sconsUtils uses.

    Parameters
    ----------
    build_root : `str`
        Absolute path to the root of the package currently being built.
    environ : `~collections.abc.Mapping` [`str`, `str`]
        Environment variables to scan, in the style of `os.environ`.

    Returns
    -------
    search_path : `list` [`str`]
        Directories to search, in priority order, with duplicates removed
        (the first occurrence of a given directory wins).  The order is:

        1. ``<build_root>/lib/pkgconfig``, so the package being built finds
           its own freshly written file.
        2. ``<value>/lib/pkgconfig`` for every environment variable matching
           ``^\\w+_DIR$`` whose directory exists, in the same way ``cfgPath``
           is built today in `state.py`.
        3. ``$SCONSUTILS_DIR/pkgconfig``, the static shims, when that
           variable is set and the directory exists.
        4. ``<build_root>/.sconf_temp/pkgconfig``, the configure-time
           generated shims.
        5. Whatever ``PKG_CONFIG_PATH`` the user already had.
    """
    search_path: list[str] = [os.path.join(build_root, "lib", "pkgconfig")]

    for key, value in environ.items():
        match = _DIR_VAR_RE.match(key)
        if not match or match.group("extra"):
            continue
        candidate = os.path.join(value, "lib", "pkgconfig")
        if os.path.isdir(candidate):
            search_path.append(candidate)

    sconsutils_dir = environ.get("SCONSUTILS_DIR")
    if sconsutils_dir:
        candidate = os.path.join(sconsutils_dir, "pkgconfig")
        if os.path.isdir(candidate):
            search_path.append(candidate)

    search_path.append(os.path.join(build_root, GENERATED_SHIM_SUBDIR))

    existing = environ.get("PKG_CONFIG_PATH")
    if existing:
        search_path.extend(existing.split(os.pathsep))

    return _dedup_preserve_order(search_path)


class PkgConfig:
    """A runner for the ``pkg-config`` executable.

    Parameters
    ----------
    search_path : `~collections.abc.Sequence` [`str`]
        Directories to place on ``PKG_CONFIG_PATH``, in priority order.
    conda_prefix : `str` or `None`
        The active conda prefix, as returned by
        `lsst.sconsUtils.utils.get_conda_prefix`.  Every invocation passes
        this as ``--define-variable=conda_prefix=<conda_prefix>``.  Builds
        without a conda environment are unsupported, so `None` is rejected.
    executable : `str`, optional
        Path to the ``pkg-config`` executable.  Defaults to the first
        ``pkg-config`` found on ``PATH``.

    Raises
    ------
    PkgConfigError
        Raised if `executable` is not given and no ``pkg-config`` can be
        found on ``PATH``, or if `conda_prefix` is `None`.
    """

    def __init__(
        self,
        search_path: Sequence[str],
        conda_prefix: str | None,
        executable: str | None = None,
    ) -> None:
        if conda_prefix is None:
            raise PkgConfigError("sconsUtils requires a conda environment; CONDA_PREFIX is not set")
        if executable is None:
            executable = shutil.which("pkg-config")
            if executable is None:
                raise PkgConfigError("pkg-config was not found on PATH")
        self.executable: str = executable
        self._search_path = list(search_path)
        self._conda_prefix = conda_prefix

    def _invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run ``pkg-config`` with `args` and return the completed process.

        The ``--define-variable=conda_prefix=...`` argument is always
        prepended.  This never raises on a non-zero exit status; callers
        decide how to interpret the result.
        """
        env = dict(os.environ)
        env["PKG_CONFIG_PATH"] = os.pathsep.join(self._search_path)
        env["PKG_CONFIG_ALLOW_SYSTEM_CFLAGS"] = "1"
        env["PKG_CONFIG_ALLOW_SYSTEM_LIBS"] = "1"
        command = [
            self.executable,
            f"--define-variable=conda_prefix={self._conda_prefix}",
            *args,
        ]
        return subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
        )

    def run(self, *args: str) -> str:
        """Run ``pkg-config`` with the given arguments and return its output.

        Parameters
        ----------
        *args : `str`
            Arguments to pass to ``pkg-config``, after the
            ``--define-variable=conda_prefix=...`` argument that is always
            prepended.

        Returns
        -------
        stdout : `str`
            The standard output of the command, as text.

        Raises
        ------
        PkgConfigError
            Raised if ``pkg-config`` exits with a non-zero status.  The
            exception message includes the command's standard error.
        """
        result = self._invoke(*args)
        if result.returncode != 0:
            raise PkgConfigError(
                f"pkg-config {' '.join(args)} failed with exit status {result.returncode}: "
                f"{result.stderr.strip()}"
            )
        return result.stdout

    def exists(self, module: str) -> bool:
        """Return whether `module` can be found on the search path.

        Parameters
        ----------
        module : `str`
            The pkg-config module name to look up.

        Returns
        -------
        exists : `bool`
            `True` if the module exists, `False` otherwise.  This never
            raises, even if `module` cannot be found.
        """
        return self._invoke("--exists", module).returncode == 0

    def modversion(self, module: str) -> str:
        """Return the version of `module`.

        Parameters
        ----------
        module : `str`
            The pkg-config module name to look up.

        Returns
        -------
        version : `str`
            The module's version, as reported by ``pkg-config
            --modversion``.
        """
        return self.run("--modversion", module).strip()

    def variable(self, module: str, name: str) -> str | None:
        """Return the value of a pkg-config variable.

        Parameters
        ----------
        module : `str`
            The pkg-config module name to look up.
        name : `str`
            The name of the variable.

        Returns
        -------
        value : `str` or `None`
            The variable's value, or `None` if it is unset or empty.
        """
        value = self.run(f"--variable={name}", module).strip()
        return value or None

    def requires(self, module: str) -> list[str]:
        """Return the modules `module` directly requires.

        Parameters
        ----------
        module : `str`
            The pkg-config module name to look up.

        Returns
        -------
        requires : `list` [`str`]
            The module names listed in `module`'s ``Requires`` field, in
            order, with any version constraint (e.g. ``"foo >= 1.2"``)
            stripped down to just the module name.
        """
        requires = []
        for line in self.run("--print-requires", module).splitlines():
            line = line.strip()
            if not line:
                continue
            requires.append(line.split()[0])
        return requires

    def closure(self, modules: Sequence[str]) -> list[str]:
        """Return the transitive closure of `modules` under ``Requires``.

        Parameters
        ----------
        modules : `~collections.abc.Sequence` [`str`]
            The pkg-config module names to start from.

        Returns
        -------
        closure : `list` [`str`]
            Every module reachable from `modules`, depth-first, in
            first-visit order, with each module appearing only once.

        Raises
        ------
        CyclicDependencyError
            Raised if a cycle is found in the ``Requires`` graph.  The
            exception message lists the modules on the cycle, in path
            order (e.g. ``"a -> b -> a"``).
        """
        result: list[str] = []
        visited: set[str] = set()
        requires_cache: dict[str, list[str]] = {}

        def visit(module: str, path: list[str]) -> None:
            if module in path:
                cycle = path[path.index(module) :] + [module]
                raise CyclicDependencyError(" -> ".join(cycle))
            if module in visited:
                return
            visited.add(module)
            result.append(module)
            if module not in requires_cache:
                requires_cache[module] = self.requires(module)
            for dependency in requires_cache[module]:
                visit(dependency, path + [module])

        for module in modules:
            visit(module, [])
        return result

    def cflags_only_I(self, modules: Sequence[str]) -> list[str]:
        """Return the ``-I`` include directories for `modules`.

        Parameters
        ----------
        modules : `~collections.abc.Sequence` [`str`]
            The pkg-config module names to query.

        Returns
        -------
        directories : `list` [`str`]
            Include directories, in pkg-config's order, with the ``-I``
            prefix stripped.
        """
        return self._split_flags("--cflags-only-I", modules, "-I")

    def cflags_only_other(self, modules: Sequence[str]) -> list[str]:
        """Return the non-``-I`` compiler flags for `modules`.

        Parameters
        ----------
        modules : `~collections.abc.Sequence` [`str`]
            The pkg-config module names to query.

        Returns
        -------
        flags : `list` [`str`]
            Compiler flags other than ``-I``, in pkg-config's order.
        """
        return self._split_flags("--cflags-only-other", modules)

    def libs_only_L(self, modules: Sequence[str]) -> list[str]:
        """Return the ``-L`` library directories for `modules`.

        Parameters
        ----------
        modules : `~collections.abc.Sequence` [`str`]
            The pkg-config module names to query.

        Returns
        -------
        directories : `list` [`str`]
            Library search directories, in pkg-config's order, with the
            ``-L`` prefix stripped.
        """
        return self._split_flags("--libs-only-L", modules, "-L")

    def libs_only_l(self, modules: Sequence[str]) -> list[str]:
        """Return the ``-l`` library names for `modules`.

        Parameters
        ----------
        modules : `~collections.abc.Sequence` [`str`]
            The pkg-config module names to query.

        Returns
        -------
        names : `list` [`str`]
            Library names, in pkg-config's order, with the ``-l`` prefix
            stripped.
        """
        return self._split_flags("--libs-only-l", modules, "-l")

    def libs_only_other(self, modules: Sequence[str]) -> list[str]:
        """Return the non-``-L``/``-l`` linker flags for `modules`.

        Parameters
        ----------
        modules : `~collections.abc.Sequence` [`str`]
            The pkg-config module names to query.

        Returns
        -------
        flags : `list` [`str`]
            Linker flags other than ``-L`` and ``-l``, in pkg-config's
            order.
        """
        return self._split_flags("--libs-only-other", modules)

    def _split_flags(self, query: str, modules: Sequence[str], prefix: str | None = None) -> list[str]:
        """Run `query` over `modules` and split the result into tokens.

        Parameters
        ----------
        query : `str`
            The pkg-config flag query to run, e.g. ``"--cflags-only-I"``.
        modules : `~collections.abc.Sequence` [`str`]
            The pkg-config module names to query.  If empty, pkg-config is
            not invoked and an empty list is returned.
        prefix : `str` or `None`, optional
            A two-character prefix (e.g. ``"-I"``) to strip from each
            token.  If `None`, tokens are returned unchanged.

        Returns
        -------
        tokens : `list` [`str`]
            The split, optionally unprefixed, tokens.
        """
        if not modules:
            return []
        tokens = shlex.split(self.run(query, *modules))
        if prefix is None:
            return tokens
        return [token[len(prefix) :] for token in tokens]


@dataclasses.dataclass
class ResolvedDependencies:
    """The result of resolving a package's dependencies through pkg-config.

    This is a plain description of what the build needs; it holds no SCons
    objects, so it can be used both to populate an SCons environment and to
    synthesize a legacy configuration.
    """

    modules: list[str]
    """Transitive closure of the module set, primary module first."""

    cpppath: list[str]
    """Include directories belonging to ``lsst_*`` modules in the closure,
    normalized with `os.path.realpath`; these are dependency-scanned."""

    xcpppath: list[str]
    """All other include directories, normalized with `os.path.realpath`;
    these are treated as system headers."""

    ccflags: list[str]
    """Compiler flags other than ``-I``."""

    libpath: list[str]
    """Library search directories, with the ``-L`` prefix stripped."""

    linkflags: list[str]
    """Linker flags other than ``-L`` and ``-l``."""

    libs: dict[str, list[str]]
    """Library names without the ``-l`` prefix, keyed by category
    (``"main"``, ``"python"``, ``"test"``)."""

    doxygen: dict[str, list[str]]
    """Doxygen tag files (``"tags"``) and include files (``"includes"``)."""

    versions: dict[str, str]
    """Version of every module in the closure, keyed by module name with a
    leading `MODULE_PREFIX` stripped."""


def _strip_module_prefix(module: str) -> str:
    """Return `module` with a leading `MODULE_PREFIX` removed, if present."""
    return module[len(MODULE_PREFIX) :] if module.startswith(MODULE_PREFIX) else module


def _variable_values(pkgconfig: PkgConfig, modules: Sequence[str], name: str) -> list[str]:
    """Return the set values of variable `name` over `modules`, in order."""
    values = []
    for module in modules:
        value = pkgconfig.variable(module, name)
        if value is not None:
            values.append(value)
    return values


def _library_union(pkgconfig: PkgConfig, modules: Sequence[str], name: str) -> list[str]:
    """Return the de-duplicated union of a library-list variable.

    Each value is split on whitespace; tokens starting with ``-l`` have
    that prefix stripped and any other token is kept unchanged.
    """
    libraries = []
    for value in _variable_values(pkgconfig, modules, name):
        for token in value.split():
            libraries.append(token[2:] if token.startswith("-l") else token)
    return _dedup_preserve_order(libraries)


def _route_includes(
    pkgconfig: PkgConfig, flag_modules: Sequence[str], modules: Sequence[str], conda_prefix: str
) -> tuple[list[str], list[str]]:
    """Split the ``-I`` directories of `flag_modules` into internal and
    external include paths.

    A directory is internal if its realpath equals the realpath of the
    ``includedir`` of some ``lsst_*`` module in `modules`, except that
    ``<conda_prefix>/include`` is always external.  Every other directory
    is external.  Both returned lists hold realpath'd directories, in
    pkg-config's order, with duplicates removed.
    """
    lsst_includes = {
        os.path.realpath(includedir)
        for includedir in _variable_values(
            pkgconfig, [m for m in modules if m.startswith(MODULE_PREFIX)], "includedir"
        )
    }
    conda_include = os.path.realpath(os.path.join(conda_prefix, "include"))
    cpppath: list[str] = []
    xcpppath: list[str] = []
    for directory in pkgconfig.cflags_only_I(flag_modules):
        resolved = os.path.realpath(directory)
        if resolved != conda_include and resolved in lsst_includes:
            cpppath.append(resolved)
        else:
            xcpppath.append(resolved)
    return _dedup_preserve_order(cpppath), _dedup_preserve_order(xcpppath)


def resolve(
    package_name: str, pkgconfig: PkgConfig, conda_prefix: str, include_build_requires: bool = True
) -> ResolvedDependencies:
    """Resolve a package's dependencies through pkg-config.

    Parameters
    ----------
    package_name : `str`
        The EUPS product name of the primary package, e.g. ``"afw"``.
    pkgconfig : `PkgConfig`
        The runner used for every pkg-config query.
    conda_prefix : `str`
        The active conda prefix.  ``<conda_prefix>/include`` is always
        routed to `ResolvedDependencies.xcpppath`.
    include_build_requires : `bool`, optional
        If `True` (the default), the module set also includes every module
        named in the primary module's ``lsst_build_requires`` variable.

    Returns
    -------
    resolved : `ResolvedDependencies`
        The resolved dependencies.  Flag queries are run once over the
        module set (the primary plus any build requirements), letting
        pkg-config expand ``Requires`` itself; per-module variables and
        versions are read for every module in the closure.

    Raises
    ------
    PkgConfigError
        Raised if the primary module or any of its build requirements
        cannot be found, naming the missing module.
    CyclicDependencyError
        Raised if the ``Requires`` graph contains a cycle.
    """
    primary = module_name(package_name)
    if not pkgconfig.exists(primary):
        raise PkgConfigError(f"pkg-config module {primary} for package {package_name!r} was not found")
    module_set = [primary]
    if include_build_requires:
        for required in (pkgconfig.variable(primary, "lsst_build_requires") or "").split():
            if not pkgconfig.exists(required):
                raise PkgConfigError(
                    f"pkg-config module {required}, listed in lsst_build_requires of {primary}, was not found"
                )
            module_set.append(required)
    module_set = _dedup_preserve_order(module_set)

    modules = pkgconfig.closure(module_set)
    lsst_modules = [m for m in modules if m.startswith(MODULE_PREFIX)]
    cpppath, xcpppath = _route_includes(pkgconfig, module_set, modules, conda_prefix)

    return ResolvedDependencies(
        modules=modules,
        cpppath=cpppath,
        xcpppath=xcpppath,
        ccflags=pkgconfig.cflags_only_other(module_set),
        libpath=_dedup_preserve_order(pkgconfig.libs_only_L(module_set)),
        linkflags=pkgconfig.libs_only_other(module_set),
        libs={
            "main": pkgconfig.libs_only_l(module_set),
            "python": _library_union(pkgconfig, modules, "lsst_python_libs"),
            "test": _library_union(pkgconfig, modules, "lsst_test_libs"),
        },
        doxygen={
            "tags": _variable_values(pkgconfig, [m for m in lsst_modules if m != primary], "doxygen_tag"),
            "includes": _variable_values(pkgconfig, lsst_modules, "doxygen_include"),
        },
        versions={_strip_module_prefix(m): pkgconfig.modversion(m) for m in modules},
    )


def apply_to_env(env: Any, resolved: ResolvedDependencies) -> None:
    """Update an SCons environment with a package's resolved dependencies.

    Parameters
    ----------
    env : `SCons.Environment.Environment`
        The environment to update.  Its ``CPPPATH``, ``XCPPPATH`` and
        ``LIBPATH`` have the resolved directories prepended, and its
        ``CCFLAGS`` and ``LINKFLAGS`` have the resolved flags appended,
        skipping entries already present.  Its ``libs`` and ``doxygen``
        attributes are replaced with copies of the resolved values.
    resolved : `ResolvedDependencies`
        The resolved dependencies, as returned by `resolve`.

    Notes
    -----
    Unlike the ``.cfg`` path, the library lists are not reversed, because
    pkg-config already emits a dependent's libraries before those of the
    modules it depends on.
    """
    env.PrependUnique(CPPPATH=resolved.cpppath, XCPPPATH=resolved.xcpppath, LIBPATH=resolved.libpath)
    env.AppendUnique(CCFLAGS=resolved.ccflags, LINKFLAGS=resolved.linkflags)
    env.libs = {k: list(v) for k, v in resolved.libs.items()}
    env.doxygen = {k: list(v) for k, v in resolved.doxygen.items()}


class PkgConfigDependencies:
    """The dependencies of a package configured through pkg-config.

    This is stored as ``env.dependencies`` in place of a
    `~lsst.sconsUtils.dependencies.PackageTree` when the package being
    built has a pkg-config template.

    Parameters
    ----------
    package_name : `str`
        The EUPS product name of the package being built.
    resolved : `ResolvedDependencies`
        The resolved dependencies of that package.
    """

    def __init__(self, package_name: str, resolved: ResolvedDependencies) -> None:
        self.name = package_name
        self.resolved = resolved

    @property
    def versions(self) -> dict[str, str | None]:
        """Version of every module in the dependency closure, keyed by
        module name with a leading `MODULE_PREFIX` stripped
        (`dict` [`str`, `str` or `None`])."""
        return dict(self.resolved.versions)


def _write_if_changed(output: str, contents: str) -> bool:
    """Write `contents` to `output` unless it already has that content.

    Parameters
    ----------
    output : `str`
        Path of the file to write.  Its parent directory is created if it
        does not already exist.
    contents : `str`
        The full content to write.

    Returns
    -------
    wrote : `bool`
        `True` if `output` was written or overwritten, `False` if its
        content already matched `contents` and it was left untouched.
    """
    if os.path.exists(output):
        with open(output) as f:
            if f.read() == contents:
                return False
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w") as f:
        f.write(contents)
    return True


def static_shim_dir() -> str | None:
    """Return the directory of sconsUtils' static pkg-config shims.

    Returns
    -------
    directory : `str` or `None`
        ``$SCONSUTILS_DIR/pkgconfig`` if the ``SCONSUTILS_DIR`` environment
        variable is set and that directory exists, otherwise `None`.  The
        `None` case is normal in the container, where the static shims
        have already been copied into ``$CONDA_PREFIX/lib/pkgconfig`` and
        sconsUtils is not set up by EUPS at all.
    """
    sconsutils_dir = os.environ.get("SCONSUTILS_DIR")
    if not sconsutils_dir:
        return None
    candidate = os.path.join(sconsutils_dir, "pkgconfig")
    if not os.path.isdir(candidate):
        return None
    return candidate


def _write_numpy_shim(directory: str) -> str | None:
    """Generate ``numpy.pc`` in `directory`, or return `None` if skipped.

    Runs the ``python`` found on ``PATH`` once to read both
    ``numpy.__version__`` and ``numpy.get_include()``.  If that invocation
    fails, for example because ``numpy`` is not importable, nothing is
    written and `None` is returned; this is silent because an environment
    without numpy simply has no use for the shim.
    """
    try:
        output = subprocess.check_output(
            [
                "python",
                "-c",
                "import numpy; print(numpy.__version__); print(numpy.get_include())",
            ],
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    lines = output.splitlines()
    if len(lines) < 2:
        return None
    version, include = lines[0].strip(), lines[1].strip()
    contents = f"Name: numpy\nDescription: NumPy C API\nVersion: {version}\nCflags: -I{include}\nLibs:\n"
    output_file = os.path.join(directory, "numpy.pc")
    _write_if_changed(output_file, contents)
    return output_file


def _write_starlink_ast_shim(directory: str) -> str | None:
    """Generate ``starlink_ast.pc`` in `directory`, or `None` if skipped.

    Runs the ``ast_link`` script found on ``PATH`` through ``sh``, exactly
    as ``configs/starlink_ast.cfg`` did, to learn the library list.  If
    ``ast_link`` cannot be found, nothing is written and `None` is
    returned.
    """
    ast_link = shutil.which("ast_link")
    if ast_link is None:
        return None
    try:
        libs = subprocess.check_output(["sh", ast_link], text=True)
    except (subprocess.CalledProcessError, OSError):
        return None
    libs = " ".join(libs.split())
    contents = (
        "conda_prefix=${pcfiledir}/../..\n\n"
        "Name: starlink_ast\n"
        "Description: Starlink AST world coordinate system library\n"
        "Version: unknown\n"
        "Cflags: -I${conda_prefix}/include/star\n"
        f"Libs: {libs}\n"
    )
    output_file = os.path.join(directory, "starlink_ast.pc")
    _write_if_changed(output_file, contents)
    return output_file


def write_shims(directory: str, static_dir: str | None = None) -> list[str]:
    """Write every pkg-config shim sconsUtils knows about into `directory`.

    Parameters
    ----------
    directory : `str`
        Directory to write into.  Created if it does not already exist.
    static_dir : `str` or `None`, optional
        Directory holding the static shims to copy, e.g. the repository's
        top-level ``pkgconfig/`` directory.  Defaults to
        `static_shim_dir`.  If that is also `None`, no static shims are
        copied; this is the container case, where they have already been
        installed directly into the conda tree.

    Returns
    -------
    written : `list` [`str`]
        The paths, under `directory`, of every shim that exists there
        after this call: every ``*.pc`` copied from `static_dir`, plus
        ``numpy.pc`` and ``starlink_ast.pc`` if they could be generated.
        This list is returned regardless of whether a given file's
        content actually changed; a file already present with identical
        content is still included, and its modification time is left
        untouched.
    """
    os.makedirs(directory, exist_ok=True)
    if static_dir is None:
        static_dir = static_shim_dir()

    written: list[str] = []
    if static_dir is not None:
        for source in sorted(glob.glob(os.path.join(static_dir, "*.pc"))):
            output_file = os.path.join(directory, os.path.basename(source))
            with open(source) as f:
                contents = f.read()
            _write_if_changed(output_file, contents)
            written.append(output_file)

    numpy_shim = _write_numpy_shim(directory)
    if numpy_shim is not None:
        written.append(numpy_shim)

    starlink_ast_shim = _write_starlink_ast_shim(directory)
    if starlink_ast_shim is not None:
        written.append(starlink_ast_shim)

    return written


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``sconsUtils-write-pkgconfig-shims`` console script.

    Parameters
    ----------
    argv : `~collections.abc.Sequence` [`str`] or `None`, optional
        Command-line arguments, not including the program name.  Defaults
        to `sys.argv[1:]`.

    Returns
    -------
    status : `int`
        Always ``0``.
    """
    parser = argparse.ArgumentParser(description="Write sconsUtils' pkg-config shims into a directory.")
    parser.add_argument("directory", help="Directory to write the shims into.")
    args = parser.parse_args(argv)
    write_shims(args.directory)
    return 0
