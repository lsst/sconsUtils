##
#  @file tests.py
#
#  Control which tests run, and how.
##
from __future__ import print_function, absolute_import
import glob
import os
import re
import sys
from SCons.Script import *    # So that this file has the same namespace as SConstruct/SConscript
from . import state
from . import utils


##
#  @brief A class to control unit tests.
#
#  This class is unchanged from previous versions of sconsUtils, but it will now generally
#  be called via scripts.BasicSConscript.tests().
##
class Control(object):
    _IGNORE = "IGNORE"
    _EXPECT_FAILURE = "EXPECT_FAILURE"

    ##
    #  @brief Create an object to run tests
    #
    #  @param env           An SCons Environment (almost always lsst.sconsUtils.env).
    #  @param ignoreList    A list of tests that should NOT be run --- useful in conjunction
    #                       with glob patterns.  If a file is listed as "@fileName", the @ is stripped and
    #                       we don't bother to check if fileName exists (useful for machine-generated files).
    #  @param expectedFalures   A dictionary; the keys are tests that are known to fail; the values
    #                           are strings to print.
    #  @param args          A dictionary with testnames as keys, and argument strings as values.
    #                       As scons always runs from the top-level directory, tests has to fiddle with
    #                       paths.  If an argument is a file this is done automatically; if it's e.g.
    #                       just a basename then you have to tell tests that it's really (part of a)
    #                       filename by prefixing the name by "file:".
    #
    #  @param tmpDir        The location of the test outputs.
    #  @param verbose       How chatty you want the test code to be.
    #
    #  @code
    #  tests = lsst.tests.Control(
    #      env,
    #      args={
    #           "MaskIO_1" :      "data/871034p_1_MI_msk.fits",
    #           "MaskedImage_1" : "file:data/871034p_1_MI foo",
    #      },
    #      ignoreList=["Measure_1"],
    #      expectedFailures={"BBox_1": "Problem with single-pixel BBox"}
    # )
    # @endcode
    ##
    def __init__(self, env, ignoreList=None, expectedFailures=None, args=None,
                 tmpDir=".tests", verbose=False):
        if 'PYTHONPATH' in os.environ:
            env.AppendENVPath('PYTHONPATH', os.environ['PYTHONPATH'])

        self._env = env

        self._tmpDir = tmpDir
        self._cwd = os.path.abspath(os.path.curdir)

        self._verbose = verbose

        self._info = {}                 # information about processing targets
        if ignoreList:
            for f in ignoreList:
                if re.search(r"^@", f):    # @dfilename => don't complain if filename doesn't exist
                    f = f[1:]
                else:
                    if not os.path.exists(f):
                        state.log.warn("You're ignoring a non-existent file, %s" % f)
                self._info[f] = (self._IGNORE, None)

        if expectedFailures:
            for f in expectedFailures:
                self._info[f] = (self._EXPECT_FAILURE, expectedFailures[f])

        if args:
            self._args = args           # arguments for tests
        else:
            self._args = {}

        self.runExamples = True                      # should I run the examples?
        try:
            # file is user read/write/executable
            self.runExamples = (os.stat(self._tmpDir).st_mode & 0o700) != 0
        except OSError:
            pass

        if not self.runExamples:
            print("Not running examples; \"chmod 755 %s\" to run them again" % self._tmpDir,
                  file=sys.stderr)

    def args(self, test):
        try:
            return self._args[test]
        except KeyError:
            return ""

    def ignore(self, test):
        if not re.search(r"\.py$", test) and \
           len(self._env.Glob(test)) == 0:  # we don't know how to build it
            return True

        ignoreFile = test in self._info and self._info[test][0] == self._IGNORE

        if self._verbose and ignoreFile:
            print("Skipping", test, file=sys.stderr)

        return ignoreFile

    def messages(self, test):
        """Return the messages to be used in case of success/failure; the logicals
        (note that they are strings) tell whether the test is expected to pass"""

        if test in self._info and self._info[test][0] == self._EXPECT_FAILURE:
            msg = self._info[test][1]
            return "false", "Passed, but should have failed: %s" % msg, \
                   "true",  "Failed as expected: %s" % msg
        else:
            return "true",  "passed", \
                   "false", "failed"

    def run(self, fileGlob):
        if not isinstance(fileGlob, basestring):  # env.Glob() returns an scons Node
            fileGlob = str(fileGlob)
        targets = []
        if not self.runExamples:
            return targets
        for f in glob.glob(fileGlob):
            interpreter = ""            # interpreter to run test, if needed

            if re.search(r"\.cc", f):   # look for executable
                f = os.path.splitext(f)[0]
            else:
                interpreter = "python"

            if self.ignore(f):
                continue

            target = os.path.join(self._tmpDir, f)

            args = []
            for a in self.args(f).split(" "):
                # if a is a file, make it an absolute name as scons runs from the root directory
                filePrefix = "file:"
                if re.search(r"^" + filePrefix, a):  # they explicitly said that this was a file
                    a = os.path.join(self._cwd, a[len(filePrefix):])
                else:
                    try:                # see if it's a file
                        os.stat(a)
                        a = os.path.join(self._cwd, a)
                    except OSError:
                        pass

                args += [a]

            (should_pass, passedMsg, should_fail, failedMsg) = self.messages(f)

            libpathstr = ""

            # If we have an OS X with System Integrity Protection enabled or similar we need
            # to pass through DYLD_LIBRARY_PATH to the test execution layer.
            pass_through_var = utils.libraryPathPassThrough()
            if pass_through_var is not None:
                for varname in (pass_through_var, "LSST_LIBRARY_PATH"):
                    if varname in os.environ:
                        libpathstr = '{}="{}"'.format(pass_through_var, os.environ[varname])
                        break

            # The TRAVIS environment variable is set to allow us to disable
            # the matplotlib font cache. See ticket DM-3856.
            # TODO: Work out better way of solving matplotlib issue in build.
            expandedArgs = " ".join(args)
            result = self._env.Command(target, f, """
            @rm -f ${TARGET}.failed;
            @printf "%%s" 'running ${SOURCES}... ';
            @echo $SOURCES %s > $TARGET; echo >> $TARGET;
            @if %s TRAVIS=1 %s $SOURCES %s >> $TARGET 2>&1; then \
               if ! %s; then mv $TARGET ${TARGET}.failed; fi; \
               echo "%s"; \
            else \
               if ! %s; then mv $TARGET ${TARGET}.failed; fi; \
               echo "%s"; \
            fi;
            """ % (expandedArgs, libpathstr, interpreter, expandedArgs, should_pass,
                   passedMsg, should_fail, failedMsg))

            targets.extend(result)

            self._env.Alias(os.path.basename(target), target)

            self._env.Clean(target, self._tmpDir)

        return targets
