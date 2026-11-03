# Multi-agent travel planner

Checkpoint 04 — LangChain/Groq Supervisor intake, 3 November 2026.

**This checkpoint is not yet a working travel application.** It contains the
agreed design, environment templates, dependency pins, an offline environment
check, validated domain models, configuration, cost/lock/replanning rules and
45 offline tests, real LangGraph orchestration, and an optional Groq Supervisor
that interprets natural-language requests. The three downstream workers remain
synthetic; their live LLM agents, provider adapters, API routes and frontend
follow later. Do not present those planned features as completed.

Target: Python **3.12.7**, Windows, project root
`D:\Projects\GenAI\Agentic AI\Travel Planning Agent`. The user verified checkpoint
01 dependency installation and graph smoke check on Windows Python 3.12.7.
Checkpoint 02's 20 tests also passed on Windows Python 3.12.7. The user reported
the checkpoint 03 demo completed after the test-discovery fix. Checkpoint 04's
45 tests passed on Linux Python 3.12.14; its Windows and live Groq checks remain
pending.

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
.\venv\Scripts\python.exe scripts\demo_workflow.py
```

If the version check fails, use the absolute path of your installed Python
3.12.7 executable in place of `py -3.12` in both commands. Do not recreate an
existing venv without checking its version first. Activation is optional; using
the venv's Python directly avoids PowerShell activation-policy problems.

The environment check sends **no network requests** and does not read API keys.
It prints package versions and verifies a tiny LangGraph can execute. No server
or Streamlit app launch command exists yet.

`pytest.ini` restricts default test discovery to tests/ and excludes backup_*/.
Keep installer backups for recovery; they are not additional active test suites.

If you already installed checkpoint 03 successfully, keep the existing venv:
dependencies are unchanged. Run `venv\Scripts\python.exe -m pytest -q` and
`venv\Scripts\python.exe scripts\demo_workflow.py` after applying checkpoint 04.
Tests use temporary fixture keys and do not load your real .env. No live API
calls occur. The demo uses in-memory checkpoints only; a test separately verifies
SQLite persistence across graph rebuilds. Demo results are not travel offers.

## Optional live Supervisor check

After offline tests pass, add your Groq key locally to GROQ_API_KEY in .env.
Keep GROQ_MODEL=openai/gpt-oss-120b. No other keys are needed yet. Run:

```powershell
.\venv\Scripts\python.exe scripts\check_supervisor.py --live
```

This enables one Groq request, zero automatic retries and a 45-second HTTP timeout.
A fixed request feeds the real Supervisor then synthetic downstream workers.
This is not a complete multi-agent live travel demo. A unique JSON report under
ignored data/reports/ contains parsed preferences, checks and token counters,
not keys/raw responses/private reasoning. Share that JSON only. Missing usage
after failure is unknown consumption; do not repeat failures blindly. Without
--live, the script is a zero-request preview and loads no key.

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
