"""Sandbox validation for dynamically generated workflow modules."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass


FORBIDDEN_IMPORTS = {
    "os",
    "subprocess",
    "socket",
    "ctypes",
    "multiprocessing",
    "pickle",
    "pathlib",
    "shutil",
    "sys",
    "importlib",
    "builtins",
    "requests",
    "urllib",
    "http",
    "ftplib",
    "paramiko",
}

FORBIDDEN_NAMES = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "breakpoint",
}

ALLOWED_TOP_LEVEL = {"asyncio", "json", "re", "math", "typing", "dataclasses"}


@dataclass
class SandboxResult:
    ok: bool
    errors: list[str]
    warnings: list[str]


class WorkflowSandbox:
    def validate_source(self, source: str) -> SandboxResult:
        errors: list[str] = []
        warnings: list[str] = []

        if len(source) > 80_000:
            errors.append("Source too large (>80KB)")

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return SandboxResult(ok=False, errors=[f"SyntaxError: {exc}"], warnings=[])

        has_run = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in FORBIDDEN_IMPORTS:
                        errors.append(f"Forbidden import: {alias.name}")
                    elif root not in ALLOWED_TOP_LEVEL:
                        warnings.append(f"Uncommon import: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    if root in FORBIDDEN_IMPORTS:
                        errors.append(f"Forbidden import from: {node.module}")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_NAMES:
                    errors.append(f"Forbidden call: {node.func.id}()")
            elif isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "run":
                    has_run = True

        if not has_run:
            errors.append("Missing async/sync function run(ctx)")

        # Soft pattern checks
        if re.search(r"\b(rm\s+-rf|curl\s+|wget\s+)\b", source):
            errors.append("Suspicious shell-like patterns detected")

        return SandboxResult(ok=not errors, errors=errors, warnings=warnings)
