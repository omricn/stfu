"""Every module that logs must define its logger.

`audio.py` gained `log.warning(...)` calls in an exception handler without a
`log` in the module. The handler existed precisely to turn a failed microphone
into a graceful message -- instead it raised `NameError: name 'log' is not
defined`, masking the original error and killing the calibration thread.

Nothing caught it: the tests exercise `candidate_devices` and `FakeSource`,
never `MicSource.open()`'s except path, and that path only runs when real
audio hardware refuses to open.
"""

import ast
from pathlib import Path

import pytest

STFU_DIR = Path(__file__).parent.parent / "stfu"
MODULES = sorted(p.name for p in STFU_DIR.glob("*.py"))


def uses_log(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "log"
        for node in ast.walk(tree)
    )


def defines_log(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "log" for target in node.targets
        ):
            return True
    return False


@pytest.mark.parametrize("module", MODULES)
def test_a_module_that_logs_defines_its_logger(module):
    tree = ast.parse((STFU_DIR / module).read_text(encoding="utf-8"))
    if not uses_log(tree):
        pytest.skip(f"{module} does not log")
    assert defines_log(tree), (
        f"{module} calls log.* but never assigns `log` -- every call site will "
        f"raise NameError, and the ones in exception handlers will do it while "
        f"already handling a failure"
    )
