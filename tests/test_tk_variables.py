"""Regression test for F1: a Tk variable created without `master=` binds to
`tkinter._default_root` -- the first Tk() in the process -- rather than to the
window that is actually using it. In this app that is app.py's hidden pump
root, so any widget bound to a master-less variable in a *different* window's
Tk() looks blank and its edits do not take.

Modelled on test_boundaries.py: mechanical AST inspection across every module,
so the next new window cannot reintroduce the bug and still pass a green
suite the way settingsui.py and firstrunui.py did.
"""

import ast
from pathlib import Path

import pytest

STFU_DIR = Path(__file__).parent.parent / "stfu"
# PhotoImage belongs here for exactly the same reason, learned the hard way
# after the variable fix: a master-less ImageTk.PhotoImage bound to the
# hidden pump root, and iconphoto on another window's interpreter raised
# "can't use pyimage1 as iconphoto", leaving a bare untitled window where
# the PIN prompt should have been.
TK_VARIABLE_NAMES = {
    "StringVar",
    "BooleanVar",
    "IntVar",
    "DoubleVar",
    "PhotoImage",
}


def _callee_name(node: ast.Call) -> str | None:
    """The simple name a call resolves to: `StringVar` for both `StringVar(...)`
    and `tk.StringVar(...)`."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _tk_variable_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node) in TK_VARIABLE_NAMES
    ]


def _stfu_modules() -> list[Path]:
    return sorted(STFU_DIR.glob("*.py"))


@pytest.mark.parametrize("module", _stfu_modules(), ids=lambda p: p.name)
def test_tk_variables_are_constructed_with_a_master(module):
    calls = _tk_variable_calls(module)
    offending_lines = [
        call.lineno
        for call in calls
        if not any(kw.arg == "master" for kw in call.keywords)
    ]
    assert not offending_lines, (
        f"{module.name} constructs a Tk variable without master= on line(s) "
        f"{offending_lines} -- it will bind to tkinter._default_root instead "
        "of the window that owns it"
    )
