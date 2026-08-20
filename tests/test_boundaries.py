import ast
from pathlib import Path

import pytest

PURE_MODULES = [
    "levels",
    "config",
    "detector",
    "strikes",
    "logstore",
    "engine",
    "clock",
    "schedule",
]
FORBIDDEN = {"sounddevice", "tkinter", "ctypes", "pystray", "matplotlib", "miniaudio"}


def imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("module", PURE_MODULES)
def test_pure_modules_have_no_io_dependencies(module):
    path = Path(__file__).parent.parent / "stfu" / f"{module}.py"
    leaked = imported_names(path) & FORBIDDEN
    assert not leaked, f"{module}.py imports {leaked}, breaking the layering rule"
