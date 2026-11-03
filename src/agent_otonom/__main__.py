"""CLI entry: agent-otonom <command>."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="agent-otonom",
        description="AGENT OTONOM — local autonomous AI agent",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Start WebGUI + API")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)

    sub.add_parser("doctor", help="Probe hardware & engines")

    p_chat = sub.add_parser("chat", help="Send one prompt via pipeline (headless)")
    p_chat.add_argument("message", nargs="+", help="Natural language prompt")
    p_chat.add_argument("--confirm-dynamic", action="store_true")
    p_chat.add_argument("--input-video", default=None)

    sub.add_parser("workflows", help="List registered workflows")

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        _cmd_serve(args.host, args.port)
    elif args.cmd == "doctor":
        asyncio.run(_cmd_doctor())
    elif args.cmd == "chat":
        asyncio.run(_cmd_chat(" ".join(args.message), args.confirm_dynamic, args.input_video))
    elif args.cmd == "workflows":
        _cmd_workflows()
    else:
        parser.print_help()
        sys.exit(1)


def _cmd_serve(host: str | None, port: int | None) -> None:
    import uvicorn

    from agent_otonom.config import get_settings

    settings = get_settings()
    h = host or settings.agent_host
    p = port or settings.agent_port
    console.print(f"[bold]AGENT OTONOM[/bold] → http://{h}:{p}")
    uvicorn.run(
        "agent_otonom.app:app",
        host=h,
        port=p,
        reload=False,
        log_level=settings.log_level.lower(),
    )


async def _cmd_doctor() -> None:
    from agent_otonom.capability import probe
    from agent_otonom.config import get_settings
    from agent_otonom.logging_setup import setup_logging

    settings = get_settings()
    setup_logging(settings.logs_dir, settings.log_level)
    cap = await probe(settings)

    table = Table(title="AGENT OTONOM — Doctor")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("OS", cap.os_name)
    table.add_row("CPU", str(cap.cpu_count))
    table.add_row("RAM (GB)", str(cap.ram_gb))
    table.add_row("GPU", f"{cap.gpu_vendor}: {cap.gpu_name}")
    table.add_row("Quality", cap.quality_profile)
    table.add_row("Encoder", cap.video_encoder)
    for name, ok in cap.tools.items():
        table.add_row(f"tool:{name}", "OK" if ok else "MISSING")
    for name, info in cap.engines.items():
        flag = "OK" if info.get("available") else ("OPTIONAL" if not info.get("required") else "FAIL")
        table.add_row(f"engine:{name}", flag)
    console.print(table)
    for n in cap.notes:
        console.print(f"• {n}")

    required_fail = [
        k
        for k, v in cap.engines.items()
        if v.get("required") and not v.get("available")
    ]
    if not cap.tools.get("ffmpeg"):
        required_fail.append("ffmpeg")
    if required_fail:
        console.print(f"[red]Doctor FAILED[/red]: {', '.join(required_fail)}")
        sys.exit(1)
    console.print("[green]Doctor OK[/green]")


async def _cmd_chat(message: str, confirm_dynamic: bool, input_video: str | None) -> None:
    from agent_otonom.capability import probe
    from agent_otonom.config import get_settings
    from agent_otonom.engines.registry import build_engines
    from agent_otonom.logging_setup import setup_logging
    from agent_otonom.memory.db import Database
    from agent_otonom.queue.events import bus
    from agent_otonom.queue.worker import JobQueue
    from agent_otonom.workflow.manager import WorkflowManager
    from agent_otonom.workflow.registry import WorkflowRegistry

    settings = get_settings()
    setup_logging(settings.logs_dir, settings.log_level)
    db = Database(settings.db_path)
    await db.connect()
    cap = await probe(settings)
    engines = build_engines(settings, cap)
    queue = JobQueue(db, bus, concurrency=1, timeout_sec=settings.job_timeout_sec)
    queue.engines = engines
    queue.capability = cap
    queue.settings = settings
    registry = WorkflowRegistry(settings.workflows_dir)
    registry.load()
    manager = WorkflowManager(settings, engines, registry, queue)
    await queue.start()

    q = bus.subscribe()
    meta = {}
    if input_video:
        meta["input_video"] = input_video
        meta["upload_path"] = input_video

    result = await manager.handle_prompt(message, meta=meta, confirm_dynamic=confirm_dynamic)
    console.print(json.dumps(result, indent=2, ensure_ascii=False))

    if result.get("needs_confirm"):
        console.print("[yellow]Butuh konfirmasi dynamic workflow. Jalankan ulang dengan --confirm-dynamic[/yellow]")
        await queue.stop()
        await db.close()
        return

    job_id = result.get("job_id")
    if not job_id:
        await queue.stop()
        await db.close()
        sys.exit(1)

    while True:
        event = await q.get()
        if event.job_id and event.job_id != job_id:
            continue
        console.print(f"[{event.kind}] {event.message}")
        if event.kind in {"done", "error"} and event.job_id == job_id:
            break

    await queue.stop()
    await db.close()


def _cmd_workflows() -> None:
    from agent_otonom.config import get_settings
    from agent_otonom.workflow.registry import WorkflowRegistry

    settings = get_settings()
    reg = WorkflowRegistry(settings.workflows_dir)
    reg.load()
    table = Table(title="Workflows")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Builtin")
    for w in reg.list():
        table.add_row(w.id, w.title, "yes" if w.builtin else "no")
    console.print(table)


if __name__ == "__main__":
    main()
