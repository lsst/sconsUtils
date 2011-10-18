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
