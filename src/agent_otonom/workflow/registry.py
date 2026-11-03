"""Workflow registry — discovers built-in and generated modules."""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

logger = logging.getLogger(__name__)

RunFn = Callable[[Any], Awaitable[str | None]]


@dataclass
class WorkflowInfo:
    id: str
    title: str
    description: str
    module_path: Path
    entry: str = "run"
    builtin: bool = True


class WorkflowRegistry:
    def __init__(self, workflows_dir: Path) -> None:
        self.workflows_dir = workflows_dir
        self._infos: dict[str, WorkflowInfo] = {}
        self._handlers: dict[str, RunFn] = {}

    def load(self) -> None:
        self._infos.clear()
        registry_file = self.workflows_dir / "_registry.yaml"
        if registry_file.exists():
            data = yaml.safe_load(registry_file.read_text(encoding="utf-8")) or {}
            for item in data.get("workflows", []):
                wid = item["id"]
                path = self.workflows_dir / item["file"]
                self._infos[wid] = WorkflowInfo(
                    id=wid,
                    title=item.get("title", wid),
                    description=item.get("description", ""),
                    module_path=path,
                    entry=item.get("entry", "run"),
                    builtin=item.get("builtin", True),
                )

        # Auto-discover generated
        gen = self.workflows_dir / "_generated"
        if gen.is_dir():
            for py in sorted(gen.glob("*.py")):
                if py.name.startswith("_"):
                    continue
                wid = py.stem
                if wid not in self._infos:
                    self._infos[wid] = WorkflowInfo(
                        id=wid,
                        title=wid.replace("_", " ").title(),
                        description="Generated workflow",
                        module_path=py,
                        builtin=False,
                    )

        for info in self._infos.values():
            try:
                self._handlers[info.id] = self._load_handler(info)
            except Exception as exc:
                logger.error("Failed loading workflow %s: %s", info.id, exc)

    def _load_handler(self, info: WorkflowInfo) -> RunFn:
        spec = importlib.util.spec_from_file_location(
            f"agent_workflows.{info.id}", info.module_path
        )
        if not spec or not spec.loader:
            raise ImportError(f"Cannot load {info.module_path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        fn = getattr(mod, info.entry, None)
        if not callable(fn):
            raise AttributeError(f"{info.module_path} missing {info.entry}()")
        return fn  # type: ignore[return-value]

    def get(self, workflow_id: str) -> WorkflowInfo | None:
        return self._infos.get(workflow_id)

    def handler(self, workflow_id: str) -> RunFn | None:
        return self._handlers.get(workflow_id)

    def list(self) -> list[WorkflowInfo]:
        return list(self._infos.values())

    def register_generated(self, workflow_id: str, path: Path, title: str, description: str) -> None:
        info = WorkflowInfo(
            id=workflow_id,
            title=title,
            description=description,
            module_path=path,
            builtin=False,
        )
        self._infos[workflow_id] = info
        self._handlers[workflow_id] = self._load_handler(info)
