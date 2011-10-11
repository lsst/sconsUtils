import sys
import warnings

try:
    import SCons.Script
    abort = SCons.Script.Exit
except ImportError:
    abort = sys.exit

class Log(object):

    def __init__(self):
        self.traceback = False
        self.hasFailed = False
        self.messages = []
        self.verbose = True

    def info(self, message):
        if self.verbose:
            print message

    def warn(self, message):
        if self.traceback:
            warnings.warn(message, stacklevel=2)
        else:
            self.messages.append(message)

    def fail(self, message):
        if self.traceback:
            raise RuntimeError(message)
        else:
            self.messages.append(message)
            self.hasFailed = True

    def flush(self):
        for message in self.messages:
            sys.stderr.write(message)
            sys.stderr.write("\n")
            sys.stderr.flush()
        self.messages = []
        if self.hasFailed:
            abort(1)

def memberOf(cls, name=None):
    """A parametrized descriptor that adds a method or nested class to a class outside the class
    definition scope.  Example:

    class test_class(object):
        pass

    @memberOf(test_class):
    def test_method(self):
        print "test_method!"

    The function or method will still be added to the module scope as well, replacing any
    existing module-scope function with that name; this appears to be an
    unavoidable side-effect.
    """
    if isinstance(cls, type):
        classes = (cls,)
    else:
        classes = tuple(cls)
    kw = {"name": name}
    def nested(member):
        if kw["name"] is None: kw["name"] = member.__name__
        for scope in classes:
            setattr(scope, kw["name"], member)
        return member
    return nested
