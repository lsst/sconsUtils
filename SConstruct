# -*- python -*-
#
# Setup our environment
#
import sys
sys.path = ["python"] + sys.path # ensure that we use our copy of sconsUtils
from lsst.sconsUtils import scripts, targets, env

scripts.BasicSConstruct.initialize(
    packageName="sconsUtils",
    versionString=r"$HeadURL$",
    )

targets["python"] = env.VersionModule("python/lsst/sconsUtils/version.py")

scripts.BasicSConstruct.finish()
