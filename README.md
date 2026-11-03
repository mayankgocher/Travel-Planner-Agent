# Multi-agent travel planner

Checkpoint 05 — four LLM roles and validated draft recommendations, 3 November 2026.

**This is not yet a complete travel application.** The Supervisor, Transportation,
Hotel and Itinerary LLM roles are connected through LangGraph. Retrieval uses
explicitly synthetic fixture data; real provider adapters, UI, selection locks,
numbered versions and export remain to be connected. There are 79 offline tests.
Do not present fixture recommendations as live offers.

Target: Python **3.12.7**, Windows, project root
`D:\Projects\GenAI\Agentic AI\Travel Planning Agent`. The user verified checkpoint
01 dependency installation and graph smoke check on Windows Python 3.12.7.
Checkpoint 02's 20 tests also passed on Windows Python 3.12.7. The user reported
the checkpoint 03 demo completed after the test-discovery fix. The corrected Supervisor passed its live check on the user's Windows machine
(801 input + 360 output = 1,161 tokens). User verified the original checkpoint 05
suite of 64 tests on Windows. Its live run stopped at Supervisor hotel_class
normalization. The corrected revision has 79 passing tests on Linux Python
3.12.14; revised Windows/live four-role verification remains pending.

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

If you already installed checkpoint 04 successfully, keep the existing venv:
dependencies are unchanged. Run `venv\Scripts\python.exe -m pytest -q` and
`venv\Scripts\python.exe scripts\demo_workflow.py` after applying checkpoint 05.
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

## Live four-role check

After offline tests pass, with GROQ_API_KEY set locally and the effective model
openai/gpt-oss-120b, run:

```powershell
.\venv\Scripts\python.exe scripts\check_agents.py --live
```

Four Groq calls normally occur: Supervisor, transport ranking, hotel ranking,
itinerary scheduling. At most one extra scheduling call can correct conflicts.
A model/parse/grounding error stops subsequent model work. Zero automatic HTTP
retries. The graph may make fewer calls for missing details or empty results.

All flight/train/hotel/place evidence is synthetic. No travel API is contacted.
This validates the LLM integration, not live price/availability accuracy. Review
ranking reasons and notes as well as automated checks. The unique JSON report
under data/reports/ includes per-role usage, recommendations, validation and
cost checks. Share only that JSON. Unknown failed-call usage is not counted as
known consumption. Without --live, the script is a zero-request preview.

Numeric-input revision: valid numeric strings such as "3"/"3.0" and explicit
hotel labels such as "3-star" normalize to an integer. Fractions, ranges and
ambiguous labels remain invalid. Rejected Supervisor decisions retain their
parsed values and reported usage; parser/truncation failures also retain available
usage. Unavailable usage is null/unknown, never inferred as zero consumption.

The historical Supervisor schema integer/number overlap has been fixed and
verified live. The original Supervisor-only check is retained for diagnosis and
need not be rerun if already passed.

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
