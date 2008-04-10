try:
    import lsstimport  # sets sys.meta_path
except ImportError:
    pass               # oh well, lsst core wasn't set up; no worries
