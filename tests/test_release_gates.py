# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise the actual workflow guards, including skipped builds on resumption."""

import ast
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit
WORKFLOW = Path(__file__).parents[1] / ".github/workflows/release.yml"


def evaluate_guard(expression, needs, cancelled):
    expression = expression.replace("!cancelled()", str(not cancelled))
    expression = expression.replace("&&", " and ").replace("||", " or ")

    def evaluate(node: ast.AST) -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id == "needs":
            return needs
        if isinstance(node, ast.Attribute):
            value = evaluate(node.value)
            if not isinstance(value, dict):
                raise TypeError("Workflow attributes require a job-state mapping")
            return value[node.attr]
        if isinstance(node, ast.BoolOp):
            values = (evaluate(value) for value in node.values)
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = evaluate(node.left), evaluate(node.comparators[0])
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        raise AssertionError(f"Unsupported workflow guard: {ast.dump(node)}")

    return evaluate(ast.parse(expression.strip(), mode="eval").body)


@pytest.mark.parametrize(
    "mode,checks,build,validation,cancelled,allowed",
    [
        ("new", "success", "success", "success", False, True),
        ("new", "failure", "skipped", "skipped", False, False),
        ("new", "success", "failure", "skipped", False, False),
        ("new", "success", "success", "failure", False, False),
        ("new", "success", "success", "cancelled", False, False),
        ("new", "success", "success", "success", True, False),
        ("resume", "success", "skipped", "success", False, True),
        ("resume", "failure", "skipped", "skipped", False, False),
        ("resume", "success", "skipped", "failure", False, False),
        ("published", "skipped", "skipped", "skipped", False, True),
        ("published", "skipped", "skipped", "skipped", True, False),
    ],
)
def test_publication_requires_checks_and_artifact_validation(
    mode, checks, build, validation, cancelled, allowed
):
    workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    guard = workflow["jobs"]["publish"]["if"]
    needs = {
        "resolve": {"result": "success", "outputs": {"mode": mode}},
        "checks": {"result": checks},
        "build": {"result": build},
        "validate": {"result": validation},
    }
    assert evaluate_guard(guard, needs, cancelled) is allowed
    needs["resolve"]["result"] = "failure"
    assert evaluate_guard(guard, needs, cancelled) is False
