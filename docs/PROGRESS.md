# Progress and continuation

Updated 3 November 2026. Checkpoint 08: RailRadar adapter and bounded check.

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
- User verified the flight live check on Windows: two HTTP 200 requests, 8
  outbound and 7 return options. Reviewed share_results(20261103-173349).zip.
  Inputs: DEL/JAI, 17/20 November 2026, two adults, Economy, sort 2, no cap.
  Every retained option had a quote and passed the listing filters. Three records
  were skipped; the older combined diagnostic cannot establish their exact causes.
  Multi-passenger/tax/baggage/fee completeness remains unverified. The 142-test
  Windows output was not provided; do not invent a test result from a live report.

## Implemented in checkpoint 08

- RailRadar HTTP boundary: fixed host and four endpoint shapes, Bearer header,
  timeout, no redirects/retries, per-probe request budget, safe audit and numeric
  quota headers. Stops before another request when reported remaining quota is zero.
- Station candidates keep nullable city and source evidence. The outbound probe
  explicitly selects NDLS/JP; general city/station choice is not implemented yet.
- Train schedule parser preserves boarding-station dates and relative overnight
  day differences; checks route/time/duration and supports five-digit train IDs.
- Python shortlists at most two trains by duration/departure. Timetables confirm
  operated coach classes and a unique ordered station pair before one fare query.
  availableClasses never means vacant seats. Explicit class required for pricing.
- Fare amounts and numeric components are retained without multiplying by adults
  or inventing tax/passenger completeness. Basis remains unverified. General
  RailRadar website links are source links, not verified booking/payment links.
- scripts/check_rail.py previews by default. --live enables at most six requests:
  two lookup, one between, up to two timetables, one fare. Default probe is CC,
  two adults, GN, NDLS->JP, departure +14 days. No LLM/SerpApi/seat/PNR calls.
- Unique reports save input parameters, station candidates, schedules, class/fare,
  components, timestamps and quota/audit records. HTTP/provider failures stop;
  completed schedule/detail evidence remains available. ZIP is created only once.
- Flight skipped records now have safe specific codes/validated airport IDs,
  never raw discarded data or exception strings. This cannot reconstruct the
  three omitted records in the already-passed flight report; no repeat needed.
- 178 offline tests passed on Linux Python 3.12.14. No fresh live travel-provider
  calls were made in this environment. No dependency changes.
- Offline saved-response replay: T02 20 schedules/no skips; T07 train 12952 classes
  and 222 stop codes; T05 INR 3,165 preserved as an unverified quote with 12 numeric
  components. Zero new quota consumption. check_rail.py preview passed, zero calls.
- Rail fare docs URL redirects to the docs index; indexed official docs/pricing
  and saved responses still describe the endpoint. Current access is unverified.
  A failed fare call must preserve schedules and unknown prices, not fake data.
- Checkpoint 08 Windows tests and the new bounded live rail check remain pending.

## Next actions

1. Install checkpoint 08, preserving .env/venv, and run 178 tests on Windows.
2. User fills RAILRADAR_API_KEY locally using the existing key. Run check_rail.py
   --live once, max six requests. Review share_results.zip, especially lookup,
   current fare access, ordered stops, class and partial results/quota headers.
   Do not repeat the passed Groq, hotel/Maps or flight live checks for this step.
3. Implement general city-to-airport/station candidate selection and connect real
   retrieval callbacks/tool definitions to agents. Clarify missing class/currency
   before pricing. Preserve independent provider quotas and source uncertainty.
   Derive hotel stay dates from actual arrival/departure, including overnight legs.
4. Add optional near-term Open-Meteo daily weather and geographic relevance checks.
   Missing hours and out-of-horizon forecasts stay unavailable, not invented.
5. Add selection/lock compatibility, serialized trip updates, numbered view-only
   snapshots, stale-version rejection and last-successful-plan preservation.
6. Add thin FastAPI, Streamlit, final Supervisor explanation and Markdown download.
   Finish representative evaluations, full live journeys and owner learning guide.

## Still pending in agreed scope

Weather, general location selection, graph live retrieval, LangChain tool-use integration,
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
