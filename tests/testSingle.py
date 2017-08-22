"""
Very simple tests to show that the test running infrastructure can run tests
standalone in a separate pytest process when required. There is nothing
scons-specific about these tests.
"""

import unittest


class SimplestPossibleSingleTestCase(unittest.TestCase):
    """Tests that don't rely on any external code."""

    def testSimple(self):
        self.assertEqual(2 + 2, 4)


if __name__ == "__main__":
    unittest.main()
