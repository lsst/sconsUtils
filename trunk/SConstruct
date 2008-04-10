# -*- python -*-
#
# Setup our environment
#
import glob
import sys

sys.path = ["python"] + sys.path # ensure that we use our copy of sconsLSST
import lsst.SConsUtils as scons

env = scons.MakeEnv("sconsUtils",
                    r"$HeadURL$")

#
# Install things
#
env['IgnoreFiles'] = r"(~$|\.pyc$|^\.svn$)"

Alias("install", env.Install(env['prefix'], "python"))
Alias("install", env.InstallEups(env['prefix'] + "/ups",
                                 glob.glob("ups/*.table"),
                                 dict([("sconsUtils", env['version'])])
                                 ))

env.Declare([None, "scons"])

env.Help("""
Support files for scons within LSST 
""")
