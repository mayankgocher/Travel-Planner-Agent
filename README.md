# Multi-agent travel planner

Checkpoint 06 — real hotel/place retrieval adapters and bounded checks, 3 November 2026.

**This is not yet a complete travel application.** The Supervisor, Transportation,
Hotel and Itinerary LLM roles are connected through LangGraph. Their existing
four-role check still uses explicitly synthetic fixture data. Separate real
SerpApi hotel and Maps adapters are now implemented and tested offline; they
are not wired into the graph yet. Flight/rail/weather adapters, UI, selection
locks, numbered versions and export remain pending. There are 108 offline tests.

Target: Python **3.12.7**, Windows, project root
`D:\Projects\GenAI\Agentic AI\Travel Planning Agent`. The user verified checkpoint
01 dependency installation and graph smoke check on Windows Python 3.12.7.
Checkpoint 02's 20 tests also passed on Windows Python 3.12.7. The user reported
the checkpoint 03 demo completed after the test-discovery fix. The corrected Supervisor passed its live check on the user's Windows machine
(801 input + 360 output = 1,161 tokens). The corrected checkpoint 05 passed all
79 tests on Windows Python 3.12.7. Its four-role live check also passed: five
Groq requests including one itinerary repair, 6,845 reported tokens, synthetic
INR 20,100 subtotal and no unresolved validation errors. This does not establish
live travel accuracy. Checkpoint 06 has 108 passing offline tests on Linux Python
3.12.14; its Windows and real SerpApi checks remain pending.

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

If you already installed checkpoint 05 successfully, keep the existing venv:
dependencies are unchanged. Run `venv\Scripts\python.exe -m pytest -q` and
`venv\Scripts\python.exe scripts\demo_workflow.py` after applying checkpoint 06.
Tests use temporary fixture keys and do not load your real .env. No live API
calls occur. The demo uses in-memory checkpoints only; a test separately verifies
SQLite persistence across graph rebuilds. Demo results are not travel offers.

## Optional live Supervisor check

After offline tests pass, add your Groq key locally to GROQ_API_KEY in .env.
Keep GROQ_MODEL=openai/gpt-oss-120b. This Supervisor check needs no other key. Run:

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

## New: hotel and places retrieval check

After offline tests pass, fill `SERPAPI_API_KEY` in your local `.env` using your
existing SerpApi key. Keep all other keys as they are. Do not paste keys in chat.
There are no dependency changes and no need to recreate your venv.

```powershell
.\venv\Scripts\python.exe scripts\check_providers.py
.\venv\Scripts\python.exe scripts\check_providers.py --live --category all
```

The first command previews without keys or network calls. The second makes
at most **two SerpApi requests**: one Jaipur hotel search and one Maps search.
No Groq, flight, rail, weather, property-detail, pagination or booking requests.
There are no automatic retries. An error on the first request stops the second.
Rerunning `--live` makes fresh requests; it does not deduplicate earlier runs.
You may run just `--category hotels` or `--category places` (one request each).

Default stay: 14 days after execution, three nights, two adults, exactly 3 stars,
INR 2,000–4,000 nightly and guest rating at least 4.2/5. A future `--check-in
YYYY-MM-DD` overrides the default date. These are probe inputs, not saved user
preferences. Provider rating code 8 requests 4+; Python applies the exact 4.2
threshold. Currency defaults to INR for this adapter if absent; monetary user
preferences still require explicit currency before complete app integration.

Read `data/reports/providers_<unique run>/report.html`: input parameters,
hotel/place tables, filter results, warnings, source IDs/links and timestamps.
Only `report.json` and `report.html` are included in `share_results.zip`. Share
that ZIP only. No keys, private reasoning or raw response payloads are saved.

`PASS_CHECKS` means selected categories returned normalized results and at least
one hotel passed the requested filters. It does not confirm room occupancy,
private room type, tax completeness, seat availability or a complete trip price.
`NO_HOTELS_MATCH_FILTERS` is a valid restrictive-search outcome, not proof the
API failed. Empty/error results require review rather than invented replacements.
No stay total is manufactured by multiplying a nightly average. These adapters
keep unknown evidence explicit; the graph's synthetic fixtures are unchanged.

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
