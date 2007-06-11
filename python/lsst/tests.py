"""Control which tests run, and how"""

import glob, os, re, sys
from SCons.Script import *              # So that this file has the same namespace as SConstruct/SConscript

class Control(object):
    _IGNORE = "IGNORE"
    
    def __init__(self, env, ignoreList=None, args=None, tmpDir=".tests", verbose=False):

        env.AppendENVPath('PYTHONPATH', os.environ['PYTHONPATH'])
        #env['ENV']['LD_LIBRARY_PATH'] = os.environ['LD_LIBRARY_PATH']

        self._env = env

        if not re.search(r"/$", tmpDir):
            tmpDir += "/"
        self._tmpDir = tmpDir
        self._cwd = os.path.abspath(os.path.curdir)

        self._verbose = verbose

        self._info = {}                 # information about processing targets
        if ignoreList:
            for f in ignoreList:
                self._info[f] = self._IGNORE

        if args:
            self._args = args           # arguments for tests
        else:
            self._args = {}

    def args(self, test):
        try:
            return self._args[test]
        except KeyError:
            return ""

    def ignore(self, test):
        try:
            if not (
                re.search(r"\.py$", test) or
                (os.stat(test).st_mode & 01) # file exists and is executable
                ):
                return True
        except OSError:
            return True

        ignoreFile = self._info.has_key(test) and self._info[test] == self._IGNORE

        if self._verbose and ignoreFile:
            print >> sys.stderr, "Skipping", test

        return ignoreFile

    def run(self, fileGlob):
        targets = []
        for f in glob.glob(fileGlob):
            interpreter = ""            # interpreter to run test, if needed

            if re.search(r"\.cc", f):   # look for executable
                f = os.path.splitext(f)[0]
            else:
                interpreter = "python"

            if self.ignore(f):
                continue

            target = os.path.join(self._tmpDir, f)
            targets += [target]

            args = []
            for a in self.args(f).split(" "):
                # if a is a file, make it an absolute name as scons runs from the root directory
                filePrefix = "file:"
                if re.search(r"^" + filePrefix, a): # they explicitly said that this was a file
                    a = os.path.join(self._cwd, a[len(filePrefix):])
                else:
                    try:                # see if it's a file
                        os.stat(a)
                        a = os.path.join(self._cwd, a)
                    except OSError:
                        pass

                args += [a]

            self._env.Command(target, f, """
            @rm -f ${TARGET}.failed;
            @echo -n 'running ${SOURCES}... ';
            @if %s $SOURCES %s > $TARGET 2>&1; then \
               echo passed; \
            else \
               mv $TARGET ${TARGET}.failed; \
               echo failed; \
            fi;
            """ % (interpreter, " ".join(args)))

            self._env.Clean(target, self._tmpDir)
        
        return targets
