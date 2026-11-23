# This file is part of sconsUtils.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Tests for `lsst.sconsUtils.utils`."""

import os
import unittest
from unittest import mock

from lsst.sconsUtils.utils import conda_compilers


class CondaCompilersTestCase(unittest.TestCase):
    """Test the choice of compilers when using conda compilers."""

    def test_environment_is_used(self):
        with mock.patch.dict(os.environ, {"CC": "conda-cc", "CXX": "conda-c++"}):
            self.assertEqual(conda_compilers(), ("conda-cc", "conda-c++"))

    def test_defaults_without_environment(self):
        for platform, expected in (("linux", ("gcc", "g++")), ("darwin", ("clang", "clang++"))):
            with (
                self.subTest(platform=platform),
                mock.patch.dict(os.environ),
                mock.patch("sys.platform", platform),
            ):
                os.environ.pop("CC", None)
                os.environ.pop("CXX", None)
                self.assertEqual(conda_compilers(), expected)

    def test_each_variable_falls_back_independently(self):
        with mock.patch.dict(os.environ, {"CC": "my-cc"}), mock.patch("sys.platform", "linux"):
            os.environ.pop("CXX", None)
            self.assertEqual(conda_compilers(), ("my-cc", "g++"))


if __name__ == "__main__":
    unittest.main()
