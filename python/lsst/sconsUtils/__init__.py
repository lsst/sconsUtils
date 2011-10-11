# Pull some names into the package namespace
from .dependencies import Configuration, configure
from .state import env, opts, log

# These inject methods into SConsEnviroment
from . import installation
from . import builders

# These should remain in their own namespaces
from . import scripts
from . import tests
