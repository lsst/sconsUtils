##
#  @file utils.py
#
#  Internal utilities for sconsUtils.
##

import sys
import warnings

import SCons.Script

##
#  @brief A dead-simple logger for all messages.
#
#  This simply centralizes decisions about whether to throw exceptions or print user-friendly messages
#  (the traceback variable) and whether to print extra debug info (the verbose variable).
#  These are set from command-line options in state.py.
##
class Log(object):

    def __init__(self):
        self.traceback = False
        self.verbose = True

    def info(self, message):
        if self.verbose:
            print message

    def warn(self, message):
        if self.traceback:
            warnings.warn(message, stacklevel=2)
        else:
            sys.stderr.write(message + "\n")

    def fail(self, message):
        if self.traceback:
            raise RuntimeError(message)
        else:
            sys.stderr.write(message + "\n")
            SCons.Script.Exit(1)

    def flush(self):
        sys.stderr.flush()

##
#  @brief A Python decorator that injects functions into a class.
#
#  For example:
#  @code
#  class test_class(object):
#      pass
#
#  @memberOf(test_class):
#  def test_method(self):
#      print "test_method!"
#  @endcode
#  ...will cause test_method to appear as as if it were defined within test_class.
#
#  The function or method will still be added to the module scope as well, replacing any
#  existing module-scope function with that name; this appears to be unavoidable.
##
def memberOf(cls, name=None):
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
