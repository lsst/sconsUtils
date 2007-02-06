# -*- python -*-
#
# Setup our environment
#
import glob
import sys

sys.path = ["python"] + sys.path        # ensure that we use our copy of sconsLSST
import lsst.SConsUtils as scons

env = scons.makeEnv("scons",
                    r"$HeadURL$")
#
# Install things
#
env['IgnoreFiles'] = r"(~$|\.pyc$|^\.svn$)"

Alias("install", env.Install(env['prefix'], "python"))
Alias("install", env.InstallEups(env['prefix'] + "/ups", glob.glob("ups/*.table")))

env.Declare()
env.Help("""
Support files for scons within LSST 
""")
