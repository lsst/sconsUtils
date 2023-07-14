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


if __name__ == "__main__":
    unittest.main()
