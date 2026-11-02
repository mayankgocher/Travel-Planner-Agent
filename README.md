# Multi-agent travel planner

Checkpoint 02 — configuration and domain rules, 3 November 2026.

**This checkpoint is not yet a working travel application.** It contains the
agreed design, environment templates, dependency pins, an offline environment
check, validated domain models, configuration, cost/lock/replanning rules and
20 offline tests. Agents, graph orchestration, API routes and frontend follow in
later checkpoints. Do not present those planned features as completed.

Target: Python **3.12.7**, Windows, project root
`D:\Projects\GenAI\Agentic AI\Travel Planning Agent`. The user verified checkpoint
01 dependency installation and graph smoke check on Windows Python 3.12.7.
Checkpoint 02 domain tests passed on Linux Python 3.12.14; running those tests
on the user's Windows environment is the next verification step.

## Read first

1. [Architecture](docs/ARCHITECTURE.md)
2. [API findings](docs/API_FINDINGS.md)
3. [Progress and handoff](docs/PROGRESS.md)
4. [Code walkthrough](docs/CODE_WALKTHROUGH.md)

## Environment setup

Extract this checkpoint into the project root. Never overwrite an existing
`.env` when installing a later checkpoint. The included `.env` is blank of keys;
`.env.example` is the version-controlled template.

In PowerShell, verify the interpreter before creating the environment:

```powershell
Set-Location -LiteralPath "D:\Projects\GenAI\Agentic AI\Travel Planning Agent"
py -3.12 -c "import sys; print(sys.version); assert sys.version_info[:3] == (3,12,7), 'Use your Python 3.12.7 executable'"
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe scripts\check_environment.py
.\venv\Scripts\python.exe -m pytest -q
```

If the version check fails, use the absolute path of your installed Python
3.12.7 executable in place of `py -3.12` in both commands. Do not recreate an
existing venv without checking its version first. Activation is optional; using
the venv's Python directly avoids PowerShell activation-policy problems.

The environment check sends **no network requests** and does not read API keys.
It prints package versions and verifies a tiny LangGraph can execute. No server
or Streamlit app launch command exists yet.

If you already installed checkpoint 01 successfully, keep the existing venv:
dependencies are unchanged. Run only `venv\Scripts\python.exe -m pytest -q`
after applying checkpoint 02. Tests use temporary fixture keys and do not load
your real .env. No live API calls occur.

Add keys locally only when live integration testing begins. Never paste them in
chat, commit `.env`, or upload a project ZIP containing populated credentials.
When sharing the folder, use a clean export excluding `.env`, `venv/`, `data/`
and logs. `.gitignore` does not sanitize arbitrary ZIPs or untrack existing files.

## Planned product

Four agents (Supervisor, Transportation, Hotel, Itinerary); single-destination
trips; flight/train comparison; preference clarification; grounded daily plans;
simple conflict correction; selective replanning; user selection locks; numbered
plan snapshots; Markdown download; systematic evaluation. No booking or payment
automation. No separate search cache.
