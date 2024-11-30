# lsst-sconsUtils

[![codecov](https://codecov.io/gh/lsst/sconsUtils/branch/main/graph/badge.svg?token=2BUBL8R9RH)](https://codecov.io/gh/lsst/sconsUtils)

sconsUtils is a package in the [LSST Science Pipelines](https://pipelines.lsst.io/).

This package contains utility scripts for building pipelines packages with 
[SCons](https://scons.org/), and is required to build most pipelines packages.
SCons can be used to build C++ and Python (with pybind11 bindings) packages;
see the [stack package templates](https://github.com/lsst/templates/tree/main/project_templates/stack_package)
if this is of interest.

This is a **Python 3 only** package (we assume Python 3.10 or higher).

This software is dual licensed under the GNU General Public License
(version 3 of the License, or (at your option) any later version,
and also under a 3-clause BSD license. Recipients may choose which of these 
licenses to use; please see the files gpl-3.0.txt and/or bsd_license.txt,
respectively.

This package can only be imported through a SCons script; as a result, it is
generally not possible to inspect the docstrings interactively. Refer to the
locally-built documentation or at https://pipelines.lsst.io/, or read the 
source code instead.