from __future__ import annotations

import ast
from pathlib import Path


def test_examples_are_valid_python() -> None:
    examples = Path(__file__).resolve().parents[1] / "examples"
    scripts = sorted(examples.glob("*.py"))

    assert scripts
    for script in scripts:
        ast.parse(script.read_text(), filename=str(script))
