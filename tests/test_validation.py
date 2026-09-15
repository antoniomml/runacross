from __future__ import annotations

import ast
from pathlib import Path

KIT = Path(__file__).resolve().parents[1] / "validation"


def test_validation_scripts_are_valid_python() -> None:
    scripts = sorted(KIT.glob("*.py"))

    assert scripts
    for script in scripts:
        ast.parse(script.read_text(encoding="utf-8"), filename=str(script))


def test_validation_readme_documents_both_scripts() -> None:
    readme = (KIT / "README.md").read_text(encoding="utf-8")

    assert "role_consumer.py" in readme
    assert "profile_consumer.py" in readme
    assert "readiness-1.0.md" in readme
