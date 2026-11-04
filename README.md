# Multi-agent travel planner

Checkpoint 08 — RailRadar retrieval and bounded live check, 3 November 2026.

**This is not yet a complete travel application.** The Supervisor, Transportation,
Hotel and Itinerary LLM roles are connected through LangGraph. Their existing
four-role check still uses explicitly synthetic fixture data. Separate real
SerpApi hotel and Maps adapters passed a real retrieval check on Windows. Separate
flight retrieval also passed its real two-direction check on Windows. The rail
adapter is now implemented and offline-tested. Real providers are not wired into
the graph yet. Weather, general location selection, UI, locks, numbered versions
and export remain pending. There are 178 offline tests.

Target: Python **3.12.7**, Windows, project root
`D:\Projects\GenAI\Agentic AI\Travel Planning Agent`. The user verified checkpoint
01 dependency installation and graph smoke check on Windows Python 3.12.7.
Checkpoint 02's 20 tests also passed on Windows Python 3.12.7. The user reported
the checkpoint 03 demo completed after the test-discovery fix. The corrected Supervisor passed its live check on the user's Windows machine
(801 input + 360 output = 1,161 tokens). The corrected checkpoint 05 passed all
79 tests on Windows Python 3.12.7. Its four-role live check also passed: five
Groq requests including one itinerary repair, 6,845 reported tokens, synthetic
INR 20,100 subtotal and no unresolved validation errors. This does not establish
live travel accuracy. The user then verified the hotel/Maps live check: two HTTP
200 responses, 18 hotels (14 matching all filters), 20 places. Occupancy, room
type, taxes and unreturned weekday hours remain unverified. The flight live check
then returned 8 outbound and 7 return options in two HTTP 200 requests. Three
records were skipped; their precise reasons were not captured in that older
report. Checkpoint 08 adds safe specific skip diagnostics. Its 178 offline tests
pass on Linux Python 3.12.14; Windows tests and new rail retrieval remain pending.
Dependencies are unchanged.

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

If you already installed checkpoint 07 successfully, keep the existing venv:
dependencies are unchanged. Run `venv\Scripts\python.exe -m pytest -q` and
`venv\Scripts\python.exe scripts\demo_workflow.py` after applying checkpoint 08.
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

This check already passed on the user's Windows machine. No repeat is needed
for installing checkpoint 07. The commands below remain available for diagnosis.

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

## New: outbound and return flight retrieval check

This live check has now passed on Windows. No repeat is needed for checkpoint 08.
The commands remain available for diagnosis; the default next check is rail.

Use the existing local SERPAPI_API_KEY. Do not recreate the venv or rerun the
already-passed hotel/Maps/Groq checks for this step.

```powershell
.\venv\Scripts\python.exe scripts\check_providers.py --category flights
.\venv\Scripts\python.exe scripts\check_providers.py --live --category flights
```

Preview makes zero calls. Live makes at most two SerpApi requests: Delhi DEL to
Jaipur JAI, then JAI to DEL, as independent one-way searches, two adults, Economy,
price sorting. Departure defaults to 14 days after execution; return three days
later. A future `--check-in YYYY-MM-DD` sets the departure date. These are explicit
probe inputs, not preferences inferred from a user. Existing `--category all`
still means only hotels and places (two requests), not flights.

The checker saves the same HTML/JSON/share ZIP format, with each leg's own input
parameters, airlines, flight numbers, segment times, quotes and source timestamps.
Stop on an error, no automatic retries, no Groq/rail/booking/airport-lookup calls.
Share only the printed `share_results.zip`. Each live rerun makes fresh requests.

Automatic city-to-airport resolution is pending. The adapter requires explicit
airport/city/timezone bindings. The probe supplies DEL/JAI and known timezone
bindings for 15 possible Indian connecting airports. Unknown airport timezones,
airport-change transfers, inconsistent segment sequences and ambiguous DST times
are skipped with warnings, not guessed. This is not worldwide flight support.

One-way results are kept separate; the program does not divide a round-trip quote
or claim that two one-way tickets are an airline round-trip bundle. Quoted fares
are not multiplied by passenger count. Multi-passenger coverage, taxes, baggage
and booking fees remain unverified unless evidence establishes them. Complete
budget feasibility therefore remains unknown. Explicit flight caps map to API
max_price, but Python cannot claim a total cap is met with an incomplete quote.
The default probe has no price cap. Flight sorting is validated as codes 1–6.

Checkpoint 07 also rejects hotel website links with explicitly conflicting stay
parameters, using a general source link when available. Source links are never
claimed as checkout/payment URLs. Nearby likely stepwell aliases are flagged;
the itinerary validator prevents scheduling both and keeps their hours unverified.
This heuristic does not automatically merge nearby distinct attractions. Partial
weekday schedules now have an explicit missing-hours warning.

## New: outbound rail retrieval check

After offline tests pass, fill `RAILRADAR_API_KEY` in the project's local `.env`
using your existing RailRadar key. Preserve the other entries. No key belongs in
chat. No dependency installation or venv recreation is needed.

```powershell
.\venv\Scripts\python.exe scripts\check_rail.py
.\venv\Scripts\python.exe scripts\check_rail.py --live
```

Preview makes zero calls. Live makes **at most six RailRadar requests**, outbound
Delhi NDLS to Jaipur JP only: two exact-code station lookups, one Trains Between,
up to two shortlisted train timetables, and at most one fare. It stops on HTTP/
provider errors, an exhausted reported quota or the local request budget. There
are no automatic retries, sleeps, seat/PNR/live-running requests, Groq or SerpApi
calls. Each live rerun makes fresh requests; this is not a duplicate-aware ledger.

The fixed probe requests two adults, General quota GN, class CC (Chair Car),
departure 14 days after execution. `--date YYYY-MM-DD` and `--class-code 3A` can
override the test inputs. These are not default end-user preferences. The return
date in the preferences is unused by this outbound-only probe; return rail is
covered offline but not yet live-tested. The station choices are explicit probe
bindings, not automatic city/metro resolution. Class must be clarified before a
fare search in the later full application; it will not silently choose CC.

Python sorts the schedule shortlist by duration then departure. Timetables are
needed here to confirm operated coach classes and ordered stops before fetching
a fare. `availableClasses` means coach classes, not vacant seats. A train that
does not confirm the requested class is skipped; at most one more is inspected.
Remaining services stay unpriced. No usable quote yields REVIEW_REQUIRED, rather
than scanning every service or pretending the journey is free.

The parser preserves boarding-station dates and overnight day differences. It
supports standard five-digit train identifiers. Rail prices remain INR; missing
totals stay null. Fare components such as GST are retained, but traveler scope,
tax completeness and all payable charges remain unverified. Amounts are not
multiplied by adults. A passing probe does not establish complete affordability.
Source URLs point to RailRadar's general website, not a verified booking page.

Read `data/reports/rail_<unique run>/report.html`: preferences, station candidates,
scheduled trains, quote/class, timetables, numeric fare components, quota headers
and exact request inputs. A failed fare request preserves retrieved schedules.
Only HTML/JSON go into `share_results.zip`; share that ZIP. No keys, raw response
bodies, private reasoning or authorization headers are saved. The fare docs URL
currently redirects, while earlier saved fare responses succeeded; this explicit
live check is needed to establish current endpoint access. Do not infer a missing
fare as zero, or switch providers silently.

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
