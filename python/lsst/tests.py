"""Control which tests run, and how"""

import glob, os, re, sys
from SCons.Script import *              # So that this file has the same namespace as SConstruct/SConscript

class Control(object):
    _IGNORE = "IGNORE"
    _EXPECT_FAILURE = "EXPECT_FAILURE"
    
    def __init__(self, env, ignoreList=None, expectedFailures=None, args=None, tmpDir=".tests", verbose=False):
        """Create an object to run tests

        env should be an environment from scons;

        ignoreList is a list of tests that should Not be run --- useful in conjunction
        with glob patterns;

        expectedFalures is a dictionary; the keys are tests that are
        known to fail; the values are strings to print.

        args is a dictionary with testnames as keys, and argument strings as values.
        As scons always runs from the top-level directory, tests has to fiddle with
        paths.  If an argument is a file this is done automatically; if it's e.g.
        just a basename then you have to tell tests that it's really (part of a)
        filename by prefixing the name by "file:".

        tmpDir is the location of the test outputs;

        verbose is how chatty you want the test code to be.

        E.g.
tests = lsst.tests.Control(env,
                           args={
                           "MaskIO_1" :      "data/871034p_1_MI_msk.fits",
                           "MaskedImage_1" : "file:data/871034p_1_MI foo",
                           }),
                           ignoreList=["Measure_1"],
                           expectedFailures={"BBox_1": "Problem with single-pixel BBox"}
                           )
        """
        env.AppendENVPath('PYTHONPATH', os.environ['PYTHONPATH'])

        self._env = env

        self._tmpDir = tmpDir
        self._cwd = os.path.abspath(os.path.curdir)

        self._verbose = verbose

        self._info = {}                 # information about processing targets
        if ignoreList:
            for f in ignoreList:
                if not os.path.exists(f):
                    print >> sys.stderr, "You're ignoring a non-existent file, %s" % f
                self._info[f] = (self._IGNORE, None)

        if expectedFailures:
            for f in expectedFailures.keys():
                self._info[f] = (self._EXPECT_FAILURE, expectedFailures[f])

        if args:
            self._args = args           # arguments for tests
        else:
            self._args = {}

        self.runExamples = True                      # should I run the examples?
        try:
            self.runExamples = (os.stat(self._tmpDir).st_mode & 0x5) # file is world read/executable
        except OSError:
            pass

        if not self.runExamples:
            print >> sys.stderr, "Not running examples; \"chmod 755 %s\" to run them again" % self._tmpDir

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

        ignoreFile = self._info.has_key(test) and self._info[test][0] == self._IGNORE

        if self._verbose and ignoreFile:
            print >> sys.stderr, "Skipping", test

        return ignoreFile

    def messages(self, test):
        """Return the messages to be used in case of success/failure; the logicals
        (note that they are strings) tell whether the test is expected to pass"""

        if self._info.has_key(test) and self._info[test][0] == self._EXPECT_FAILURE:
            msg = self._info[test][1]
            return "false", "Passed, but should have failed: %s" % msg, \
                   "true",  "Failed as expected: %s" % msg
        else:
            return "true",  "passed", \
                   "false", "failed"

    def run(self, fileGlob):
        if not self.runExamples:
            return
        
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

            (should_pass, passedMsg, should_fail, failedMsg) = self.messages(f)

            expandedArgs = " ".join(args)
            self._env.Command(target, f, """
            @rm -f ${TARGET}.failed;
            @echo -n 'running ${SOURCES}... ';
            @echo $SOURCES %s > $TARGET; echo >> $TARGET;
            @if %s $SOURCES %s >> $TARGET 2>&1; then \
               if ! %s; then mv $TARGET ${TARGET}.failed; fi; \
               echo "%s"; \
            else \
               if ! %s; then mv $TARGET ${TARGET}.failed; fi; \
               echo "%s"; \
            fi;
            """ % (expandedArgs, interpreter, expandedArgs, should_pass, passedMsg, should_fail, failedMsg))

            self._env.Alias(os.path.basename(target), target)

            self._env.Clean(target, self._tmpDir)
        
        return targets
