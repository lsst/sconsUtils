# The original version of this file was obtained from
# https://github.com/melver/scons-bare/blob/master/site_scons/site_tools/compile_commands.py
# where it is licensed as CC0 (effectively public domain).
#
# Minor modifications have been made to integrate it with the rest of the
# sconsUtils package.

"""
SCons logic to emit compile_commands.json for files compiled in current
invocation.
"""

__all__ = ["compile_commands"]

import json
import os
import SCons


def make_strfunction(strfunction):
    def _strfunction(target, source, env, **kwargs):
        cwd = os.getcwd()
        cmd = strfunction(target, source, env, **kwargs)
        env._compile_commands.append({
            'directory': cwd,
            'command': cmd,
            'file': source[0].rstr()
        })
        return cmd
    return _strfunction


def write_compile_commands(target, source, env):
    with open(str(target[0]), 'w') as f:
        json.dump(env._compile_commands, f, indent=2, sort_keys=True)


def compile_commands(env, outdir):
    if hasattr(env, '_compile_commands'):
        return
    env._compile_commands = []

    c_strfunction = make_strfunction(SCons.Defaults.CAction.strfunction)
    SCons.Defaults.CAction.strfunction = c_strfunction
    cxx_strfunction = make_strfunction(SCons.Defaults.CXXAction.strfunction)
    SCons.Defaults.CXXAction.strfunction = cxx_strfunction
    shcxx_strfunction = make_strfunction(SCons.Defaults.ShCXXAction.strfunction)
    SCons.Defaults.ShCXXAction.strfunction = shcxx_strfunction

    compile_commands_path = env.Dir(outdir).File("compile_commands.json")
    env.AlwaysBuild(env.Command(target=compile_commands_path,
                                source=[],
                                action=env.Action(write_compile_commands,
                                                  "writing %s" % compile_commands_path)))
