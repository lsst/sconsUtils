.. py:currentmodule:: lsst.sconsUtils

.. _lsst.sconsUtils-pkgconfig:

########################################
Describing dependencies with pkg-config
########################################

A package that ships C++ headers or a C++ library describes its build-time dependencies with a pkg-config template rather than a ``ups/<name>.cfg`` file.
This page describes the template format, how sconsUtils uses it, and the related shims and tooling.

Which packages need a template
===============================

A package needs a template if and only if it has an ``include/`` or ``src/`` directory.
Header-only packages count.
Pure-Python packages do not, and carry no C++ configuration file at all.

File name and location
=======================

The template is committed at the top level of the repository, next to ``SConstruct``, named ``lsst_<product>.pc.in``.
It is not placed in ``ups/`` because it is not EUPS metadata.
sconsUtils writes the generated file to ``lib/pkgconfig/lsst_<product>.pc`` during ``configure()``, before any pkg-config query is made.

A package may have a template or a ``ups/<name>.cfg``, never both.
If sconsUtils finds both files it fails with a message naming them.

Example
=======

The template for ``afw`` looks like this:

.. code-block:: text

   prefix=${pcfiledir}/../..
   includedir=${prefix}/include
   libdir=${prefix}/lib

   Name: lsst_afw
   Description: LSST Science Pipelines application framework
   Version: @VERSION@
   Requires: lsst_cpputils lsst_daf_base lsst_pex_exceptions lsst_geom lsst_log lsst_pex_config eigen3 fftw3 ndarray numpy minuit2 gsl cfitsio lsst_astshim lsst_sphgeom
   Cflags: -I${includedir}
   Libs: -L${libdir} -lafw
   lsst_build_requires=boost_test pybind11

Field rules
===========

``prefix`` is always ``${pcfiledir}/../..``, because the generated file lives in ``lib/pkgconfig/`` under the product root.
This makes one file correct both in a source tree declared to EUPS in place and in an installed product directory.

``includedir`` and ``libdir`` are always defined, even for a header-only package.
sconsUtils reads ``includedir`` to decide which include directories are dependency-scanned.

``Version`` is always the literal ``@VERSION@``.
sconsUtils substitutes it with the real version string when it writes the ``.pc`` file.
No other substitution is performed.

``Requires`` lists every C++ dependency, mapped to its pkg-config module name.
Only ``Requires`` is used; ``Requires.private`` is not, because LSST headers expose their dependencies and the stack links shared libraries.

``Libs`` names the package's own library.
A header-only package has ``Libs:`` with only ``-L${libdir}``, or omits the field.

``Cflags`` is ``-I${includedir}``.

Custom variables
=================

Five custom variables are recognized, all optional.

``lsst_build_requires``
   Space-separated modules needed only to build this package, not to link against it.
``lsst_python_libs``
   ``-l`` flags linked only into Python extension modules.
``lsst_test_libs``
   ``-l`` flags linked only into C++ test programs.
``doxygen_tag``
   Path of the Doxygen tag file this package produces, normally ``${prefix}/doc/<name>.tag``.
``doxygen_include``
   Path of the Doxygen include file this package provides, normally ``${prefix}/doc/<name>.inc``.

Generation
==========

sconsUtils writes ``lib/pkgconfig/lsst_<product>.pc`` from the template during ``configure()``, substituting ``@VERSION@`` with ``env["version"]``.
This happens synchronously rather than as a deferred SCons target, because sconsUtils queries the package's own ``.pc`` file to configure its own include and library paths before the SCons build graph exists.
The file is written only if its content would change, so an unchanged build does not touch it.
It is not written when SCons is run with ``--clean`` and no explicit targets, or with ``--help``.

Running ``scons --clean`` with no explicit targets removes the generated ``lib/pkgconfig/lsst_<name>.pc`` file, and removes the ``lib/pkgconfig/`` directory too if it is left empty.
``*.pc`` is not part of the default ``cleanExt`` pattern, so this removal is specific to the one generated file and does not touch ``.pc`` files tracked in a repository, such as sconsUtils's own static shims.

Search path
===========

sconsUtils constructs ``PKG_CONFIG_PATH`` for every pkg-config invocation, in this order:

1. ``<build root>/lib/pkgconfig``, so the package being built finds its own freshly written file.
2. ``<value>/lib/pkgconfig`` for every environment variable matching ``^\w+_DIR$``, in the same way ``cfgPath`` is built in ``state.py``.
3. ``$SCONSUTILS_DIR/pkgconfig``, the static shims, when that variable is set.
4. ``<build root>/.sconf_temp/pkgconfig``, the configure-time generated shims.
5. Whatever ``PKG_CONFIG_PATH`` the user already had.

pkg-config appends its compiled-in default path after all of these, which is how an EUPS-less container finds dependencies that are not set up.
Because ``*_DIR`` entries come before the defaults, a product set up by EUPS always wins over the same product installed in the conda tree.

Builds without a conda environment are unsupported on this path: sconsUtils fails with a clear message if no conda prefix can be found, rather than attempting a fallback.

Include routing
================

An ``-I`` directory is routed to ``CPPPATH``, and so is dependency-scanned, if it equals the ``includedir`` of some ``lsst_*`` module in the dependency closure.
Every other directory is routed to ``XCPPPATH`` and treated as a system header directory with ``-isystem``.
``<conda_prefix>/include`` always goes to ``XCPPPATH``, regardless of which module claims it.
Both sides of the comparison are passed through ``os.path.realpath`` first, because pkg-config does not normalize ``${pcfiledir}/../..``.

Migration changes for a converting package
=============================================

A package converting from a ``.cfg`` file adds ``lib/pkgconfig/`` to its ``.gitignore``, because the ``.pc`` file there is generated at configure time.
It also passes ``noCfgFile=True`` to ``configure()``, even though the pkg-config template is what actually selects the pkg-config path regardless of ``noCfgFile``.

A converted package may only depend on other converted packages, because pkg-config resolves ``Requires`` itself and fails outright on a missing module.
Conversion therefore proceeds bottom-up through the dependency graph.
A ``.cfg`` package, by contrast, may depend on a converted package: when ``PackageTree._tryImport`` finds no ``<dep>.cfg`` file, it looks for a ``lsst_<dep>`` pkg-config module on the search path above.
This fallback applies only to dependencies; the package being built still needs its own ``ups/<name>.cfg``.
If no ``lsst_<dep>.pc`` file is on the search path or on pkg-config's default path, the dependency is treated as an optional package that was not found.
If the file is there but its own ``Requires`` cannot be satisfied, the build fails with pkg-config's explanation rather than treating the dependency as absent.
This holds under both pkg-config and pkgconf.

Shims
=====

A shim is a ``.pc`` file sconsUtils ships for a third-party library that conda does not provide one for, so that a ``Requires:`` naming it still resolves.
The static shims live in sconsUtils's top-level ``pkgconfig/`` directory, covering Boost, Minuit2, and ndarray.
Two further shims, for NumPy and Starlink AST, cannot be static because they depend on the Python interpreter or the installed AST library, and are generated at configure time into ``.sconf_temp/pkgconfig/``.

The console script ``sconsUtils-write-pkgconfig-shims DIRECTORY`` writes every shim, static and generated, into the given directory.
sconsUtils does the same itself at configure time with ``<build root>/.sconf_temp/pkgconfig/`` as the target, both for a package with a template and for a ``.cfg`` package the first time it falls back to pkg-config for a dependency.
A container install runs the script with ``$CONDA_PREFIX/lib/pkgconfig`` so that the shims are available with no sconsUtils involvement at all.
A generated shim that cannot be written, because ``numpy`` is not importable or ``ast_link`` is not on ``PATH``, is skipped rather than treated as an error, and sconsUtils logs why with ``--verbose``.
