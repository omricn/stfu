"""Regression test: "Start over" relaunched into a crash.

A frozen one-file build unpacks itself into a temp _MEI directory and records
that path in the environment. The relaunched child inherited it, looked for
its runtime in the *parent's* directory, and the parent deleted that directory
as it exited -- so the child died before drawing anything:

    Failed to execute script '__main__' due to unhandled exception:
    Can't find a usable init.tcl in {...\\Temp\\_MEI00008ce82\\_tcl_data}

Which left the state wiped and no app running: the exact bricked outcome the
spawn-before-reset ordering was meant to prevent.
"""

from stfu.app import _child_environment


def test_it_strips_the_unpack_directory():
    env = {"_PYI_APPLICATION_HOME_DIR": r"C:\Temp\_MEI00008ce82", "PATH": "/usr/bin"}
    assert "_PYI_APPLICATION_HOME_DIR" not in _child_environment(env)


def test_it_strips_every_pyinstaller_variable():
    env = {
        "_PYI_ARCHIVE_FILE": "stfu.exe",
        "_PYI_APPLICATION_HOME_DIR": r"C:\Temp\_MEI1",
        "_PYI_PARENT_PROCESS_LEVEL": "1",
    }
    assert _child_environment(env) == {}


def test_it_strips_the_older_name_too():
    # PyInstaller 5 and earlier used this one; a build on an older toolchain
    # would otherwise still hand the child a doomed path.
    assert _child_environment({"_MEIPASS2": r"C:\Temp\_MEI2"}) == {}


def test_it_keeps_everything_else():
    env = {
        "PATH": "/usr/bin",
        "LOCALAPPDATA": r"C:\Users\someone\AppData\Local",
        "_PYI_ARCHIVE_FILE": "stfu.exe",
    }
    cleaned = _child_environment(env)
    assert cleaned == {"PATH": "/usr/bin", "LOCALAPPDATA": env["LOCALAPPDATA"]}


def test_an_unfrozen_environment_is_untouched():
    env = {"PATH": "/usr/bin", "HOME": "/home/someone"}
    assert _child_environment(env) == env


def test_it_does_not_mutate_what_it_was_given():
    env = {"_PYI_ARCHIVE_FILE": "stfu.exe", "PATH": "/usr/bin"}
    _child_environment(env)
    assert "_PYI_ARCHIVE_FILE" in env


def test_a_variable_merely_containing_pyi_survives():
    # Prefix match, not substring: something like COMPYIDE should not be eaten.
    env = {"COMPYIDE": "x", "MY_PYI_THING": "y"}
    assert _child_environment(env) == env
