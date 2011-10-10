import sys
import warnings

try:
    import SCons.Script
    abort = SCons.Script.Exit
except ImportError:
    abort = sys.exit

class Logger(object):

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

    def finish(self):
        for message in self.messages:
            sys.stderr.write(message)
            sys.stderr.write("\n")
            sys.stderr.flush()
        if self.hasFailed:
            abort(1)

log = Logger()
