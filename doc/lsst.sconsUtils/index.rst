.. py:currentmodule:: lsst.sconsUtils

.. _lsst.sconsUtils:

###############
lsst.sconsUtils
###############

The ``sconsUtils`` module provides tooling to support the building of standard LSST packages using SCons.

.. Add subsections with toctree to individual topic pages.

.. _lsst.sconsUtils-contributing:

Contributing
============

``lsst.sconsUtils`` is developed at https://github.com/lsst/sconsUtils.
You can find Jira issues for this module under the `sconsUtils <https://jira.lsstcorp.org/issues/?jql=project%20%3D%20DM%20AND%20component%20%3D%20sconsUtils>`_ component.

.. _lsst.sconsUtils-pyapi:

Python API reference
====================

.. note::

   Many of the methods defined in this package are injected directly into the base SConsEnvironment.
   The `~lsst.sconsUtils.installation.SConsUtilsEnvironment` class exists solely to allow these methods to be documented.
   The class will not be used when writing SCons files.

.. automodapi:: lsst.sconsUtils.scripts
   :no-main-docstr:
   :no-inheritance-diagram:
.. automodapi:: lsst.sconsUtils.dependencies
   :no-main-docstr:
.. automodapi:: lsst.sconsUtils.tests
   :no-main-docstr:
   :no-inheritance-diagram:
.. automodapi:: lsst.sconsUtils.installation
   :no-main-docstr:
.. automodapi:: lsst.sconsUtils.builders
   :no-main-docstr:
   :no-inheritance-diagram:
.. automodapi:: lsst.sconsUtils.utils
   :no-main-docstr:
   :no-inheritance-diagram:

Using ``sconsUtils`` without the ``conda`` Compilers
====================================================

If you would like to use ``sconsUtils`` without the ``conda`` compilers, then put
``SCONSUTILS_AVOID_CONDA_COMPILERS`` in your environment with a non-``None`` value.
This environment variable will instruct ``sconsUtils`` to use the default system
compilers and compiler flags.
