# Security — Dynamic Workflow Sandbox

Generated Python is powerful and dangerous. AGENT OTONOM applies defenses:

1. **Confirmation gate** — first run of a new dynamic workflow asks the user (WebGUI dialog / CLI `--confirm-dynamic`).
2. **AST sandbox** — rejects `os`, `subprocess`, `socket`, `eval`, `exec`, `open`, etc.
3. **Size limit** — source > 80KB rejected.
4. **Audit file** — `workflows/_generated/<id>.audit.txt` stores idea + warnings.
5. **Safe stub fallback** — if LLM output fails validation, a read-only text stub is written instead of executing unsafe code.
6. **Job timeout** — `JOB_TIMEOUT_SEC` (default 3600).
7. **Media path check** — `/api/media` only serves files under the project root.

## Recommendations

- Keep `REQUIRE_CONFIRM_NEW_WORKFLOW=true` on shared machines.
- Review `_generated/*.py` before re-running untrusted prompts.
- Do not expose port `8790` to the public internet without auth/TLS (v1 is localhost-first).
