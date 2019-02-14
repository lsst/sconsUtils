# Explain what happens when you try to import outside scons
# When building documentation you want to force a SCons import
import os
import sys

if ("pydoc" in sys.modules or "sphinx" in sys.modules) and "SCONS_DIR" in os.environ:
    scons_path = os.path.join(os.environ["SCONS_DIR"], "lib", "scons")
    if scons_path not in sys.path:
        sys.path.append(scons_path)

try:
    import SCons.Script
except ImportError:
    raise ImportError("lsst.sconsUtils cannot be imported outside an scons script.")

# Try to import the generated version module.
try:
    from .version import *
except:
    __version__ = "unknown"

# Pull some names into the package namespace
from .dependencies import configure, Configuration, ExternalConfiguration
from .state import env, opts, log, targets
from .builders import ProductDir

# These inject methods into SConsEnviroment
from . import installation
from . import builders

# These should remain in their own namespaces
from . import scripts
from . import tests
