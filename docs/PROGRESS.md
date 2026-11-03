# Progress and continuation

Updated 3 November 2026. Checkpoint 07: flight adapter and source-quality fixes.

## Verified through checkpoint 05

- User verified dependency installation on Windows Python 3.12.7 and graph smoke
  execution. Backup test discovery was fixed by pytest.ini.
- Supervisor live structured extraction passed with 1,161 tokens. Groq integer/
  number schema overlap and strict whole-number normalization were fixed.
- Four roles are connected through LangGraph: Supervisor, Transportation, Hotel,
  Itinerary. Current graph retrieval uses explicitly synthetic fixtures.
- User verified 79 offline tests and the four-role live synthetic check on Windows:
  PASS_CHECKS, five Groq calls including one itinerary repair, 6,845 total tokens.
  Reviewed report: agents_20261103_164619_957128_4b9fa4.json.
- Per-role totals: Supervisor 1,089; transport 944; hotel 928; itinerary 3,884.
  Synthetic recommendations cost INR 20,100 against INR 25,000, with no remaining
  timing errors. This is one successful scenario, not an accuracy score.
- Ranking IDs, hard filters, schedule bounds/buffers/hours and Decimal subtotals
  are validated in Python. Model failures stop further model work. Missing usage
  stays unknown, and available rejected-call usage is retained.
- One transport explanation described 3A as requested despite train_class=null.
  Checkpoint 06 tightens that prompt; semantic quality still requires review.

## Implemented in checkpoint 06

- Fixed-host SerpApi HTTP client: 30-second timeout, zero retries/redirects,
  redacted request audit, safe provider errors, accepted response size limit.
- Hotel search maps date/adults/currency, nightly bounds, exact/at-least stars and
  rating buckets. Python retains exact thresholds. Typed normalization preserves
  missing totals, tax evidence, timestamps and source links. Occupancy/room type
  remain unverified because the source fields do not establish them.
- Maps search normalizes place IDs, address, coordinates, rating and weekday
  hours from search/detail shapes. Ambiguous hours remain unknown. Exact IDs
  deduplicate; nearby aliases and geographic relevance still need review.
- scripts/check_providers.py previews without keys or calls. Explicit --live
  --category all enables at most two SerpApi requests, one hotel and one Maps,
  stopping on an error. It makes no LLM/flight/rail/weather/booking requests.
- Unique HTML/JSON reports pair query parameters with results and limitations;
  a share ZIP is created once after report writes finish. Keys and raw provider
  responses are excluded. Rerunning live spends fresh requests; no dedup ledger.
- 108 offline tests passed on Linux Python 3.12.14. Tests intercept HTTP, block
  sockets and verify normalization, hard filters, errors, bounds and reporting.
  Dependencies unchanged. No real API calls were made in this build environment.
- Existing sanitized response replay also passed offline: H02 normalized 18 hotels
  (all occupancy-unverified); M01 normalized 20 places, all with parsed hours.
  check_environment.py passed imports/conditional graph execution, and provider
  preview confirmed zero calls. No fresh live retrieval was attempted here.
- User verified the real hotel/Maps check on Windows: two HTTP 200 responses,
  18 hotels (14 eligible), 20 places. Run providers_20261103_171503_728051_43edf0;
  reviewed share_results(20261103-171636).zip. The 108-test Windows output was
  not supplied; the latest explicitly confirmed Windows suite remains 79 tests.
- Hotel room occupancy/type/taxes remain unverified. The report exposed a stale
  date-bearing hotel URL, likely stepwell aliases and only three parsed weekdays
  per place. These are source-quality boundaries, not proof the retrieval failed.

## Implemented in checkpoint 07

- FlightAdapter searches separate outbound/return one-way legs with explicit
  AirportLocation bindings. No airport discovery or round-trip token workflow yet.
- Typed FlightSegment data preserves carriers, flight numbers, IATA codes and
  timezone-aware segment timestamps. Parser checks route, dates, chronology and
  connections; unknown zones/airport-change transfers/ambiguous DST are skipped.
- Explicit class/sort/max_price mapping. Sort codes restricted to 1–6; Supervisor
  prompt includes the mapping. No fare multiplication, no invented all-traveler
  coverage or included taxes, no automatic booking/booking-options requests.
- --category flights makes at most two requests. --category all still means the
  original hotel/Maps pair. Both use the same report writer and HTTP boundary;
  each flight case keeps only its own request parameters. No new dependency.
- Known conflicting hotel date/night/guest URL parameters now discard that link
  in favor of a general source URL when available; a warning explains the change.
- Nearby matching-name/stepwell candidates are flagged as possible aliases, not
  merged. Schedule validation prevents visiting both and leaves their hours
  unverified. Partial weekday hours now have an explicit warning.
- 142 offline tests passed on Linux Python 3.12.14. Includes live-report regression
  cases, flight direction/params/scope, segments, overnight and cross-zone times,
  DST rejection, error-stop limits and safe reports. No fresh live calls here.
- Saved-response replay normalized F04:56, F05:22, F06:14, F07:19 and F08:13
  one-way offers. Respectively 0/2/3/0/8 records were skipped where airport
  timezone bindings were unavailable. F02 round-trip and F03 child-passenger
  scope were deliberately excluded from this adult-only one-way adapter check.
  These are offline replays, not fresh provider requests or new availability.
- --category flights preview passed with zero calls. No dependency changes.
- Checkpoint 07 Windows tests and new live flight retrieval remain pending.

## Next actions

1. Install checkpoint 07 preserving .env/venv; run 142 tests on Windows.
2. With the existing local SERPAPI_API_KEY, run check_providers.py --live --category
   flights once (at most two requests). Review share_results.zip. Do not repeat
   hotel/Maps/Groq checks merely to install this checkpoint. Flight quote scope,
   carrier/segment details, source links and unknown taxes need review.
3. Implement RailRadar adapter and bounded check: station lookup -> Trains Between
   -> Python shortlist -> fares -> optional timetable. Fare docs routing needs
   rechecking; do not infer removal from a redirect. Availability stays unverified.
4. Implement city-to-airport discovery/candidate selection and connect real
   providers to agent retrieval callbacks/tool definitions. Derive hotel stay
   dates from actual transport arrival/departure, including overnight legs.
   Keep fixtures separate; never substitute them after a live provider failure.
5. Add geographic validation and optional near-term Open-Meteo daily weather.
   Missing/partial hours and unavailable future forecasts stay visible. Navigation
   route-time verification and extra attraction-fee research are not promised.
6. Add selection/lock compatibility, serialized trip updates, numbered view-only
   snapshots, stale-version rejection and last-successful-plan preservation.
7. Add thin FastAPI, Streamlit, final Supervisor explanation and Markdown download.
   Finish representative evaluations, live journeys and owner learning guide.

## Still pending in agreed scope

Rail/weather adapters, airport resolution, graph live retrieval, LangChain tool-use integration,
user selection controls/locks, durable application lifecycle, plan snapshots,
FastAPI, Streamlit, export and systematic evaluation. Graph checkpoints are not
product versions. No full application readiness claim is supported yet.

## Preserve decisions

Four agents; one destination; Python 3.12.7; LangGraph/LangChain, Groq, FastAPI,
Streamlit. Windows root: D:\Projects\GenAI\Agentic AI\Travel Planning Agent.
No automated booking/payment, separate search cache, vector database or RAG.
Current trip results stay in graph state. Core subtotal is intercity transport
plus hotels, excluding food/local transport/attractions. No extra attraction fee
research. Selective replanning, minimal repair, locks, versions and download stay
in scope. Groq pay-as-you-go chosen, activation/actual limits unverified; provider
quotas remain independent. No old five-request/day cap or fixed 65-second pacing.

Keep keys server-side. Unknown price is null, not zero. Missing occupancy/taxes/
currency prevent complete affordability claims. Monetary preferences without an
explicit currency still need clarification before full app integration. Search
links are not payment guarantees. Keep source/fetch timestamps and warnings.

Read AGENTS.md, README, architecture, API findings and walkthrough before edits.
Run offline tests before extending. Preserve the user's environment and backups.
