try:
    import lsstimport  # sets dlopen flags
except ImportError:
    pass               # oh well, lsst/base wasn't set up; no worries
import pkgutil
__path__ = pkgutil.extend_path(__path__, __name__)
