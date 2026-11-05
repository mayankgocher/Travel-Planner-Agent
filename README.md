# Multi-agent travel planner

Checkpoint 10 hotel ranking fix — connected provider-backed four-agent workflow, 5 November 2026.

**This is not yet a complete travel application.** The same four agents can now
run with real provider adapters through validated LangChain tools and LangGraph.
The connected probe uses explicit Delhi/Jaipur station/airport bindings. General
location selection, weather, FastAPI/Streamlit, locks, product versions and export
remain pending. Train prices default to labelled deterministic assumptions; real
rail fare access is still restricted. There are 240 offline tests. The older
check_agents.py deliberately retains its fully synthetic travel retrieval.

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
report. The rail live check then passed lookup/schedules/class checks but its fare
request returned HTTP 403 PLAN_UPGRADE_REQUIRED (86 monthly requests remained).
The user approved deterministic assumed fares for the interview demo. Checkpoint
09 passed all 209 tests on Windows and its zero-network replay passed: train
12015 CC had the assumed INR 618/adult / INR 1,236 for two; 12958 had no CC fare.
The original checkpoint 10 passed 221 tests on Windows Python 3.12.7. Its connected
run completed retrieval but Groq rate-limited Itinerary (details and recovery below).
The user ran the recovery revision after enabling UTF-8 mode on Windows. All
seven travel requests succeeded, but the Hotel Agent's ranking still failed ID
validation. This fix preserves eligible hotels and continues with a local order
when that happens. The fix passes 240 offline tests on Linux Python 3.12.14;
Windows and live verification of the fix remain pending. Source and assumed-price
labels are preserved; no real API calls were made in this build environment.
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

If you already installed checkpoint 09 successfully, keep the existing venv:
dependencies are unchanged. Run `venv\Scripts\python.exe -m pytest -q` and
`venv\Scripts\python.exe scripts\demo_workflow.py` after applying checkpoint 10.
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

## New: deterministic train demo fares

The prior RailRadar run confirmed station lookup, two scheduled trains and their
operated classes. Its fare call returned 403 PLAN_UPGRADE_REQUIRED. No subscription
was purchased. The user explicitly approved assumed train prices for the demo.

`TRAIN_FARE_MODE=mock` is now the default, including when this new variable is
absent from an existing .env. The installer preserves .env and venv. You may add
this setting locally; no new dependency, key or train-by-train fare table is needed.
`live` keeps real pricing separate and never falls back silently to mock after errors.

First verify using your already-saved report, with **zero API calls and no keys loaded**:

```powershell
.\venv\Scripts\python.exe scripts\check_rail.py --replay-report "D:\Projects\GenAI\Agentic AI\Travel Planning Agent\data\reports\rail_20261103_175413_908487_cb1234\share_results.zip"
```

The replay accepts a generated report.json or share_results.zip, validates stored
train/route/class evidence, and writes a new report folder. It never modifies the
input, renews historical source timestamps or calls the paid endpoint. Old data
remain old data: this is not a fresh seat/availability/schedule check. The reviewed
report prices train 12015 in CC; train 12958 does not operate CC, so it stays unpriced.
Read the new report.html and share only its share_results.zip if needed.

How the assumption works, in `backend/services/demo_fares.py`:

1. Confirm the train, operated class and uniquely ordered station pair from evidence.
2. Build `train_number|boarding_code|destination_code|class` and hash with SHA-256.
3. Map the integer to an arbitrary inclusive per-adult class range.
4. Multiply this invented unit amount by the stated adult count in Python.

Any new valid five-digit train/route/class combination works without a lookup table.
Same key/rule version gives the same per-adult amount across process restarts. Date
and passenger count are excluded from the hash; changing adult count changes only
the party total. Different keys may share a value. The ranges do not model distance,
season, real taxes or actual railway pricing. They are not market-price estimates.
For the hashing example `13240|NDLS|JP|3A`, the result is INR 897 per adult, 1,794 for
two adults. That example alone does not establish that train's route/class validity.
Rule version is sha256-class-v1; bump it if ranges/key rules change.

Each generated quote carries pricing_mode=demo, per_adult_amount, demo_rule_version
and an ASSUMED DEMO FARE notice. The schedule's Source remains unchanged; RailRadar
did not supply that price. Seats remain unverified. Actual schedule/place fixtures
are still kept separate from real evidence; the approved exception is price-only.

Verified totals exclude demo prices. `budget_status` stays unknown and
`complete_subtotal` stays null if any selected price is assumed. When all required
components otherwise have complete comparable scope, `illustrative_subtotal` and
`illustrative_budget_status` demonstrate budget reasoning under the assumptions.
Missing fares, currency mismatch or incomplete live room/passenger/tax scope still
prevent a full illustrative affordability decision. No assumed amount is a real
payment quote. Unknown provider amounts are never turned into demo values implicitly.

### Optional fresh retrieval — not required for this checkpoint

```powershell
.\venv\Scripts\python.exe scripts\check_rail.py --live --fare-mode mock
```

This explicitly spends at most FIVE RailRadar requests: two station lookups, one
NDLS-to-JP service search and up to two timetables. Confirmed shortlist matches
receive assumed fares locally; /fare is never called. Default test inputs are two
adults, CC, departure +14 days, GN context. --date YYYY-MM-DD / --class-code 3A
change probe inputs. Only the bounded shortlist is checked; other services stay
unpriced. These are probe choices, not default end-user preferences or a general
metro-station resolver. No Groq, SerpApi, seats, PNR, bookings or payments.

`--live --fare-mode live` explicitly requests the paid fare endpoint (at most SIX
requests, one fare). It is retained for future paid access; do not rerun it with
this restricted key. Failures preserve confirmed class and schedule evidence, keep
price unknown and never switch to mock. Return direction has offline coverage;
the fresh probe remains outbound only. Existing four-role check_agents.py still
uses synthetic retrieval. The connected provider-backed graph is described below.

## New: connected four-agent live check

After offline tests pass, use the existing local GROQ_API_KEY, SERPAPI_API_KEY and
RAILRADAR_API_KEY. No new account or dependency is needed. Keep the existing venv.
The earlier replay/individual provider/Groq checks do not need repeating.

```powershell
.\venv\Scripts\python.exe scripts\check_connected.py
.\venv\Scripts\python.exe scripts\check_connected.py --live
```

Preview is zero-network and loads no keys. **The --live command makes real API
calls.** Default probe: Delhi to Jaipur, leaving +14 days, returning three days
later, two adults, train CC, exactly 3-star hotel, INR 2,000–4,000/night, guest
rating >=4.2, INR 25,000 budget, history interests and relaxed pace. Dates can be
set with --departure YYYY-MM-DD. These are explicit test inputs, not silent
end-user defaults.

Limits per execution: up to FIVE Groq calls (four roles plus one itinerary
correction), FOUR SerpApi calls, and SIX RailRadar calls in mock fare mode. The
train probe normally needs only TWO SerpApi searches (hotel + Maps). Rail performs
separate outbound/return schedule searches and up to two timetables per leg; no
paid fare endpoint in mock mode. There are no automatic HTTP retries, quota waits,
booking/payment/seat/PNR calls or fabricated schedule/place fallback.

--transport-mode flight or compare is available for explicit separate tests;
flights use up to two SerpApi searches, leaving two for hotels/Maps. Only the first
four normalized flight options per leg enter ranking. --fare-mode live explicitly
requests paid RailRadar pricing (up to EIGHT rail calls); do not use it with the
restricted key. The probe explicitly defaults to mock regardless of an old .env
fare setting. Each live rerun spends fresh requests; no duplicate-aware cache.

The Supervisor extracts preferences, Python clarifies missing mode/currency/class,
Transportation retrieves and ranks, Hotel searches the derived stay dates and
ranks, and Itinerary organizes real place candidates. Python validates IDs,
classes, dates, known hours, buffers and costs. Tools are invoked by the graph's
Python callbacks, not by an autonomous model tool loop. Native structured replies
remain separate from tool execution.

Hotel check-in comes from the ranked outbound arrival date in the destination
zone; checkout comes from the ranked return departure date. Original user trip
dates stay unchanged. A transport replan that changes the stay invalidates held
hotels and refreshes them; compatible hotels and places remain retained. Missing
transport coverage leaves requested-date hotel quotes explicitly unconfirmed.

Station/airport selections are deliberately explicit here (NDLS/JP, DEL/JAI,
Asia/Kolkata), not an arbitrary city resolver. Mismatched bindings do not silently
search a different destination. Authentication/quota/network failures stop further
calls to that provider in the run; independent supported alternatives can continue
when compare was requested. No separate search cache is introduced.

Read data/reports/connected_<run>/report.html and share only share_results.zip.
It contains workflow outputs, matching request parameters, provider errors,
assumption labels, token counters and checks. Keys, raw model responses/private
reasoning and authorization headers are excluded. Reports save after graph nodes;
the share ZIP is created once. Hosted tool/model tracing is disabled for this path.

PASS_CONNECTED_CHECKS means the tested four-role draft has grounded sources and
no remaining timing errors. It does not prove worldwide coverage, verified payable
prices or full application readiness. Unknown hotel/flight passenger/tax scope
continues to make actual affordability unknown. Assumed fares are excluded from
verified totals; illustrative comparisons also require complete remaining scope.
Warnings and unknown totals are expected when evidence is incomplete.

## Recover the 4 November connected run

The reviewed connected_20261104_184653_663713_8be319 report contains eight successful
travel HTTP responses: two SerpApi and six RailRadar. Supervisor/Transportation/
Hotel completed, with 7,120 known reported tokens. Groq rejected Itinerary with
HTTP 429: effective limit 8,000 TPM, used 5,586, requested 2,584. This establishes
the limit applied to that key/organization, not whether billing was activated.
The unfinished draft was a model-quota failure, not missing train fares or failed
hotel/Maps access. Failed-call consumption is unknown.

This revision reduces ranking messages and output by using short local IDs such
as H01/T01, mapping them back to the complete original records with strict ID
checks. Repeated hotel dates/adults and unused source notes stay out of ranking
messages. Python owns the whole-trip budget decision. Incomplete/assumed-price
rankings use explicit scope notices instead of unsupported affordability prose.

Successful place retrieval now survives a following model failure. The older
report did not retain those places, so **that particular recovery needs one new
Maps search**. Saved train/hotel rankings and source timestamps remain unchanged,
apart from replacing unsafe old explanations with scope notices.

After installing the recovery revision and passing offline tests, run this instead
of repeating --live:

```powershell
$env:GROQ_MODEL = "openai/gpt-oss-120b"
.\venv\Scripts\python.exe scripts\check_connected.py --resume-report "D:\Projects\GenAI\Agentic AI\Travel Planning Agent\data\reports\connected_20261104_184653_663713_8be319\share_results.zip"
```

**--resume-report is a live continuation**, not a zero-network replay. It validates
the saved normalized evidence before loading keys, restores only the completed
steps using LangGraph update_state(as_node="hotels"), then resumes Itinerary and
finalization. It makes at most **two Groq requests** (one schedule plus one optional
correction), **one Maps request** if places are missing, and **zero train, hotel or
flight searches**. With retained places it needs no travel-provider key/request.
There are no automatic retries or fixed waits. A repeated 429 saves the evidence
again and reports MODEL_RATE_LIMITED rather than pretending the node succeeded.

Do not combine --resume-report with --live, --departure, --fare-mode or
--transport-mode; the saved preferences/fare mode must be preserved. Only a failed
Itinerary model step in this connected Delhi/Jaipur probe is supported. Invalid
or past-date evidence is rejected; this is not general product version restore.
The source report is never changed. The new report separates previous-run token/
request counters from new execution counters. Old source timestamps stay old;
resumption does not refresh hotel quotes, timetables or seat availability.

The .env, venv and dependencies are unchanged. The PowerShell environment variable
above sets the selected model for that terminal; keep GROQ_MODEL in .env correct
for future terminals too. Read the new report and share only its share_results.zip.
The resume command above is specific to the earlier Itinerary failure. The 5
November hotel failure has no saved hotel offers and cannot use that command.

## Verify the hotel ranking fix

The Hotel Agent still uses valid model rankings. If the returned list omits,
duplicates or invents an ID, the agent discards the entire ranking and explanation.
Python sorts the original eligible hotels by quoted nightly price in the trip
currency (unknown/incomparable quotes last), then by higher guest rating, with a
stable ID tie-breaker. The report warns when this local sort is used. No model
retry, hotel re-search, invented hotel or affordability claim is introduced.

Install `Travel_Project_Checkpoint_10_Hotel_Fix.zip` using its existing installer
and run the offline suite (240 tests). Tests explicitly decode reports as UTF-8,
so setting `PYTHONUTF8` is no longer necessary for report comparisons. Keep the
existing venv and keys. Once tests pass, run a fresh connected probe:

```powershell
$env:GROQ_MODEL = "openai/gpt-oss-120b"
.\venv\Scripts\python.exe scripts\check_connected.py --live --fare-mode mock
```

This makes fresh requests with the same existing request bounds. Share the new
report if needed. This revision was tested offline only.

## Planned product

Four agents (Supervisor, Transportation, Hotel, Itinerary); single-destination
trips; flight/train comparison; preference clarification; grounded daily plans;
simple conflict correction; selective replanning; user selection locks; numbered
plan snapshots; Markdown download; systematic evaluation. No booking or payment
automation. No separate search cache.
