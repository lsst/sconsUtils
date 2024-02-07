"""
Very simple tests to show that the test running
infrastructure can run more than one test file.
There is nothing scons-specific about these tests.
"""

import os
import unittest


class SimplestPossibleTestCase(unittest.TestCase):
    """Tests that don't rely on any external code."""

    def testSimple(self):
        self.assertEqual(2 + 2, 4)

    def testEnvironment(self):
        """Test the environment. The test will fail if the tests are run
        by anything other than SCons."""
        envVar = "XDG_CACHE_HOME"
        self.assertIn(envVar, os.environ)
        self.assertTrue(os.path.exists(os.environ[envVar]), f"Check path {os.environ[envVar]}")

    def testNoImplicitMultithreading(self):
        """Test that the environment has turned off implicit
        multithreading.
        """
        envVar = "OMP_NUM_THREADS"
        self.assertIn(envVar, os.environ)
        self.assertEqual(os.environ[envVar], "1")

        try:
            import numexpr
        except ImportError:
            numexpr = None

        if numexpr:
            self.assertEqual(numexpr.utils.get_num_threads(), 1)


if __name__ == "__main__":
    unittest.main()
