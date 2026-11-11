#include "pybind11/pybind11.h"

#include "testPkgConfig/hello.h"

PYBIND11_MODULE(_testPkgConfig, mod) { mod.def("hello", &testPkgConfig::hello); }
