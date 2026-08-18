"""Regression test for Part 1 of the Tk refactor: every window in this app
used to build its own `tk.Tk()` and call `.mainloop()` on it, nested inside
app.py's hidden pump root's event loop. That produced five separate field
bugs (see app.py's module docstring) -- settings rendering blank, the PIN
prompt opening as a bare untitled window, a deadlocked capture thread, a
desktop message whose re-entry guard never cleared, and a PIN-gated tray item
whose window never appeared. Patching each instance individually never held.

The fix is exactly one `tk.Tk()` in the whole running app (app.py's hidden
pump root) plus one sanctioned exception (firstrunui.py's wizard, which runs
and is destroyed before that root exists) -- everything else is a
`tk.Toplevel()` of it, and nothing but app.py calls `.mainloop()`.

Modelled on test_boundaries.py and test_tk_variables.py: mechanical AST
inspection across every module, so a window patched carelessly in the future
cannot reintroduce a second interpreter and still pass a green suite -- the
suite never once caught any of the five bugs above on its own.
"""

import ast
from pathlib import Path

import pytest

STFU_DIR = Path(__file__).parent.parent / "stfu"

# app.py is the one sanctioned owner of the hidden pump root and its
# mainloop() -- that is the entire point of this refactor ("app.py owns the
# only tk.Tk()").
#
# firstrunui.py runs before app.py's root exists at all (first-run setup,
# with nothing else running yet) and is the one place a fresh Tk() is
# genuinely the first and only root in the process at that moment. It is
# destroyed before App() ever constructs its own root (see app.py's main()).
ALLOWED_TK_ROOT_MODULES = {"app.py", "firstrunui.py"}
ALLOWED_MAINLOOP_MODULES = {"app.py", "firstrunui.py"}


def _stfu_modules() -> list[Path]:
    return sorted(STFU_DIR.glob("*.py"))


def _call_lines(path: Path, predicate) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and predicate(node)
    ]


def _is_tk_root_call(node: ast.Call) -> bool:
    """`tk.Tk(...)` or a bare `Tk(...)` -- never `Toplevel`, which is the
    whole point: every window but the wizard must be one of those instead."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "Tk"
    if isinstance(func, ast.Name):
        return func.id == "Tk"
    return False


def _is_mainloop_call(node: ast.Call) -> bool:
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr == "mainloop"


@pytest.mark.parametrize("module", _stfu_modules(), ids=lambda p: p.name)
def test_only_app_and_firstrun_construct_a_tk_root(module):
    if module.name in ALLOWED_TK_ROOT_MODULES:
        pytest.skip(f"{module.name} is a sanctioned tk.Tk() owner")

    lines = _call_lines(module, _is_tk_root_call)
    assert not lines, (
        f"{module.name} constructs tk.Tk() on line(s) {lines} -- every "
        "window but the first-run wizard must be a tk.Toplevel() of app.py's "
        "one root, or it binds to the wrong Tk interpreter (see app.py's "
        "module docstring for the five field bugs that caused)"
    )


@pytest.mark.parametrize("module", _stfu_modules(), ids=lambda p: p.name)
def test_only_app_and_firstrun_call_mainloop(module):
    if module.name in ALLOWED_MAINLOOP_MODULES:
        pytest.skip(f"{module.name} owns its own mainloop()")

    lines = _call_lines(module, _is_mainloop_call)
    assert not lines, (
        f"{module.name} calls mainloop() on line(s) {lines} -- a second "
        "mainloop() nested inside app.py's pump root has caused real field "
        "bugs (see app.py's module docstring); if a caller genuinely needs "
        "to block until a window closes, use master.wait_window(toplevel) "
        "instead"
    )
