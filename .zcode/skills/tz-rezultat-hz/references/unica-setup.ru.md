# Unica (1С MCP plugin) — work-folder setup process

Lesson 2026-11-20 (sess_54d8495b / sess_eee3356c: without Unica a run stalled for hours). Preflight checks cache/config/network (check_unica); THIS file is the process: what the model does, when, and why.

## Launch chain (5 links; any broken → no `unica.*` tools in the session, while preflight stays GREEN: it runs unica.exe from cache directly, bypassing MCP — a handshake OK does not prove MCP works!)

1. `~/.zcode/cli/config.json` → `plugins.enabledPlugins."unica@unica": true`.
   WORKING METHOD (2026-11-21, plan B): the ZCode plugin resolver ignores MCP even inline — register the server DIRECTLY in `~/.zcode/cli/config.json` → mcp.servers.unica: command = the DIRECT unica.exe from runtimes (no sh/bootstrap — the bootstrap layer needs HOME/USERPROFILE which are missing in ZCode's stripped spawn env → «Connection closed»), env: WITHOUT UNICA_HOST_CONTEXT_REQUIRED (with it Unica expects host context Codex-style → «host did not supply workspace context»; without it it takes the workspace from cwd — ZCode spawns with the project workingDirectory; proven 2026-11-21: unica.check → «workspace is ready»), UNICA_PROVIDER_STATE_DIR=<data>/unica/provider-state, UNICA_RUNTIME_CACHE_DIR=<data>/runtimes. The path is pinned to version 0.13.0: after a plugin update, replace the version in the path (find unica.exe in runtimes/unica). Config backup — config.json.bak-unica.
2. `~/.zcode/cli/plugins/cache/unica/unica/<version>/.zcode-plugin/plugin.json` → key `mcpServers` — WHAT to run. IMPORTANT (defect 2026-11-20): ZCode supports only the INLINE mcpServers object; a file reference (`"mcpServers": "./.mcp.json"`, as in Unica's original) is silently ignored — the server is not registered and absent from logs. Fixed: inline with absolute paths (the author's stock launch — git alias + launch.sh — replaced by a direct launch.sh call via the absolute sh.exe of Git for Windows). Original backup — `plugin.json.bak`; a plugin update resets it → repeat.
3. `<plugin>/bootstrap/launch.sh` — picks the binary by OS/arch → `bootstrap/bin/win-x64/unica-bootstrap.exe run --plugin-root …`
4. `unica-bootstrap.exe` checks the pinned runtime and starts `unica.exe` — the stdio MCP server. Runtime cache: `~/.zcode/cli/plugins/data/unica@unica/runtimes/` (`unica/…`, `bsl-analyzer/…`, `v8-runner/…`).
5. Work folder: `unica.exe` reads `v8project.yaml` in the workspace ROOT (source paths — cf/cfe INSIDE the workspace only) — the link to a specific configuration. MCP isolation: workspace.

Is MCP alive? (not the same as preflight): log `~/.zcode/cli/log/zcode-YYYY-MM-DD.jsonl` → events `mcp.server.connected`/`mcp.server.failed` (`mcpServerName`), or a manual probe: initialize request over stdio in launch.sh → serverInfo.unica reply (2026-11-20: HANDSHAKE OK, v0.13.0).

## Operating conditions (all four mandatory)

1. **1С configuration INSIDE the work folder.** `v8project.yaml` outside does not work by design: `source-set[].path` must lie inside the workspace (no `..`, no absolute/symlinked paths outward — errors `invalid_source_root` / `source_set.path_unsafe`). Config outside the project → copy it into the work folder (e.g. `1c-shared/cf`, `1c-shared/cfe`).
2. **`v8project.yaml` in the work-folder root**, relative paths: `source-set: [{name: main, path: '1c-shared/cf'}, …]`. Created by `find_config.py` automatically after the config path is fixed (idempotent; cfe omitted when absent). The model NEVER creates it manually.
3. **Plugin enabled**: `~/.zcode/cli/config.json` → `plugins.enabledPlugins` → `"unica@unica": true` (explicit entry wins).
4. **A NEW ZCode session** in that folder: the MCP server connects ONLY at session start. A file/entry created mid-session is not picked up — find_config.py prints «Чтобы продолжить составление ТЗ, перезапустите {ХАРНЕСС}.» itself and exits with code 42 ({ХАРНЕСС} from --harness: ZCode / Claude Code / Codex). The model's reply at exit 42 — VERBATIM PASTE of that one line, nothing else (no retelling: zero explanations, analogies, «what is already ready» — 2026-11-20 lesson: a wall of text and «smart» analysis waste time and tokens).

## Model actions (by step)

1. Step 1: preflight — the Unica line of the report. `[ИСПРАВЛЕНО]`/`[OK]` → proceed; `[FAIL]`/`[ДЕЙСТВИЕ]` — follow the prescription.
2. Preflight pack §1: config path → `find_config.py` (writes the link into projects.yaml and generates `v8project.yaml` itself).
3. User asks «проверь Юник» mid-session: dig to the CAUSE, not the symptom — plugin in cache (`~/.zcode/cli/plugins/cache/unica`)? runtime in `data/unica@unica/runtimes` (`bin/win-x64/unica.exe`)? `v8project.yaml` in the root? paths INSIDE the workspace? process/handshake? An «unavailable» report without a cause is an error (E-56 style).
4. Network: direct HTTPS may be blocked (VPN/proxy, e.g. Clash `127.0.0.1:7897`). Preflight finds the proxy (env + Windows registry) and downloads the runtime through it ITSELF (`[ИСПРАВЛЕНО]`). Manual path — set `HTTPS_PROXY`/`HTTP_PROXY` before bootstrap.
5. After any «create file / enable plugin» — stop with one short message «Чтобы продолжить составление ТЗ, перезапустите {ХАРНЕСС}.» ({ХАРНЕСС} — the actual environment name, см. п.4); continuing without Unica is possible ONLY for business-ТЗ (tech-ТЗ = blocker, «уточнить по конфигурации» marks).

## Health check

- `unica.check` → `workspace is ready`, `sourceSelectionError: None`.
- `unica.view` on the config root → a task starts (`taskId`).
- Non-blocking warning `git.repository_absent` — does not affect reads (fixed by `git init` in the work-folder root, optional).

## Call discipline (2026-11-22, first-day run failures)

1. FIRST unica call — only after `[OK] Unica index` in preflight. Warm-up is a SCRIPT (`_check_unica_index`); if preflight prints `[WARN] Unica index` — scan by export with a note, do not poke Unica.
2. TOOL SCHEMA — BEFORE the call. Parameter limits come from the deferred tool's schema (defect 2026-11-22: waitMs 8000 with a max of 7000 — my call error, not the plugin's).
3. ASYNC is NORMAL, not a failure. `unica_docs`/`unica_search` may go «working» (the index is built in daemon memory, NOT on disk). Polling `unica.task_result` — MAX 2 polls × ≤7 s; longer → do not block: non-blocking fallback (see below), return to Unica later.
4. «deadline expired during invocation submit» = daemon busy/fresh — same fallback, retry after a minute, not immediately.
5. An expired async task expires by TTL (1 h) on its own; nothing to «clean» — indexes are not stored on disk (provider-state ~84 KB, task bookkeeping).

## Non-blocking fallback (2026-11-22, run ФР.000.00.00.0-59)

- On async «working» past the poll limit (2 × 7 s) — do NOT block the work: continue the scan by export (cf/cfe).
- A Unica task lives 1 h: after other work, return via `unica_task_result` (tool schema — BEFORE the call); if the task finished — use its result, the export scan counts as DRAFT (mark it in исследование.md).
- `unica.view` over metadata collections works synchronously and reliably — prefer it over global searches on the first scan.
