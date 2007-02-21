try:
    import fw                           # set sys.meta_path
except ImportError:
    pass                                # fw wasn't set up; just running scons
