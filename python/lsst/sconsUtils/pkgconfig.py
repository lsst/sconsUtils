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
    "PkgConfigError",
    "build_search_path",
    "module_name",
)

import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Mapping, Sequence

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
