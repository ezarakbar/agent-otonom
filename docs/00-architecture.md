# Architecture — AGENT OTONOM

## Purpose

Local-first autonomous AI agent controlled via chat (WebGUI / CLI).  
Natural-language prompts are routed to existing workflows or used to **generate** new Python workflow modules dynamically.

## Layers

1. **Interface** — FastAPI REST + WebSocket + static WebGUI (`web/`), CLI (`agent-otonom`).
2. **Intent Analyzer** — heuristic + Ollama JSON classification → workflow id.
3. **Dynamic Workflow Manager** — catalog lookup → enqueue, or generate+sandbox+register.
4. **Job Queue** — asyncio workers + SQLite persistence; UI never blocks on long renders.
5. **Engine Adapters** — LLM (Ollama) · **Vision (ComfyUI)** · **Voice (GPT-SoVITS)** · FFmpeg.
6. **Capability Probe** — detects OS, RAM, GPU, encoders, and **requires** ComfyUI + GPT-SoVITS unless `ALLOW_ENGINE_FALLBACK=true`.

## Data flow

```
User prompt → /api/chat → IntentAnalyzer → WorkflowManager
    → JobQueue → workflow.run(ctx) → engines → outputs/<job_id>/
    → EventBus → WebSocket → clean status lines in chat
```

## Key packages

| Path | Role |
|------|------|
| `src/agent_otonom/app.py` | HTTP/WS gateway |
| `src/agent_otonom/capability.py` | Hardware & engine probe |
| `src/agent_otonom/intent/` | Router |
| `src/agent_otonom/workflow/` | Registry, generator, sandbox, manager |
| `src/agent_otonom/queue/` | Jobs + event bus |
| `src/agent_otonom/engines/` | Adapters |
| `workflows/` | Built-in + generated modules |

## Non-goals (v1)

- No automatic upload to YouTube/social platforms.
- No hard dependency on CUDA / NVENC (AMD AMF and libx264 remain valid).
- ComfyUI and GPT-SoVITS **are** first-class media engines (not optional slideshow/TTS toys).
- No Celery/Redis required (portable asyncio + SQLite).
