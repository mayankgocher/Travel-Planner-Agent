# Progress and continuation

Updated 4 November 2026. Checkpoint 10 recovery revision: resume only failed Itinerary.

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
- User ran the rail check on Windows. Five HTTP 200 responses verified station
  lookup, two scheduled services, and train 12958/12015 operated classes/stops.
  Request 6, 12015 CC fare, returned 403 PLAN_UPGRADE_REQUIRED. Remaining monthly
  quota was 86; this was not key failure, rate limiting or bad parameters.
  Reviewed share_results(20261103-175535).zip. No repeat is needed to diagnose it.
- User then explicitly approved deterministic assumed train fares for interviews,
  including unseen combinations. This is a price-only mock mode, not fabricated
  schedule/class evidence or a subscription purchase.

## Implemented in checkpoint 09

- Small services/demo_fares.py hashes number|from|to|class with SHA-256, maps to
  arbitrary class-specific integer ranges and multiplies by adult count. No date
  or adults in the per-adult hash. Version sha256-class-v1; no per-train registry.
- Evidence guards require matching number, operated class, ordered unique stops
  and compatible source types. Unsupported/unconfirmed combinations stay unpriced.
- PriceQuote carries pricing_mode=demo, per_adult_amount and demo_rule_version.
  Real schedule Source metadata/timestamps stay unchanged. Taxes/payable fares
  remain unverified; complete cannot be true for assumed prices.
- TRAIN_FARE_MODE defaults to mock. Existing .env is preserved; absent new setting
  takes this default. Explicit live mode remains and has no automatic mock fallback.
- Mock searches check up to two shortlisted class-compatible trains without /fare;
  the fresh probe spends at most five calls. Live keeps at most one fare/six calls.
  Confirmed class is retained even if a paid fare request fails.
- Verified cost sums exclude assumed components. Separate illustrative fields can
  demonstrate budget arithmetic only with complete comparable remaining quotes.
  Real budget_status stays unknown. Other unknown live scope is not papered over.
- Agent notices/graph finalization disclose assumed prices and illustrative budget
  decisions. Existing source fixture separation remains; the explicit approved
  exception permits demo prices on confirmed real schedule metadata.
- check_rail.py --replay-report reads the saved JSON/ZIP and generates a new mock
  report with zero API calls, no keys loaded and unchanged historical timestamps.
  It does not mutate input or imply a fresh availability check.
- Actual saved-report replay passed: train 12015 CC INR 618/adult, INR 1,236 for two;
  12958 has no CC, so no mock quote. These amounts are invented, not market estimates.
- 209 offline tests passed on Linux Python 3.12.14, covering unseen keys, all
  supported class ranges, restart/hash-seed stability, scope/route guards, party
  math, no paid endpoint in mock mode, live failure without fallback, report replay
  and four-agent illustrative cost disclosure. No dependency changes/live calls.
- User verified all 209 tests on Windows (14.94s), then PASS_DEMO_CHECKS with zero
  calls/keys loaded. Reviewed share_results(20261104-150038).zip: 12015 CC INR
  618/adult, 1,236/two; 12958 unsupported CC remains unpriced. Original provider
  timestamps retained. Assumptions remain explicit and no real budget claim made.

## Implemented in checkpoint 10

- runtime.build_provider_workflow composes the same four LLM roles with existing
  SerpApi/RailRadar adapters using validated StructuredTool invoke callbacks.
  Retrieval sequence is Python-owned, not autonomous model tool selection. Native
  strict structured replies stay separate from tool calls; hosted tracing is off.
- TravelProviderSession owns lazy clients, per-execution budgets and safe failure
  gates. Explicit JourneyBindings supplied by the Delhi/Jaipur probe. General city/
  airport/station selection remains pending. No fixture fallback or separate cache.
- Train/flight/compare modes retrieve outbound and return legs independently.
  Mock train mode never calls /fare. First four normalized flight options per leg
  enter ranking; supplied price provenance is retained. Scope/completeness rules
  are unchanged; actual affordability cannot be inferred from assumed prices.
- SearchResult is a shared boundary, preserving provider warnings through agents
  into graph results. Auth/quota/network/server errors stop further calls to that
  provider; compare can continue with the independent provider. Completed train
  schedule/class evidence survives a later fare failure.
- Real-provider intake clarifies missing mode/currency and train class when needed,
  and rejects past departure dates before search. Legacy fixture graphs retain
  their original simpler intake contract.
- Hotel stay dates derive from ranked transport arrival/return departure in the
  destination zone. Original trip preferences are preserved. Transport changes
  that invalidate held hotel dates trigger hotel refresh; compatible places remain.
- Compact LLM candidate payloads omit long source URLs/provenance notes, while
  complete evidence remains in returned normalized offers/reports.
- scripts/check_connected.py previews without keys/calls. Explicit --live starts
  <=5 Groq, <=4 SerpApi, <=6 rail calls for mock fares (<=8 only explicit live fare).
  Default train probe typically uses 2 SerpApi queries. No seats/PNR/payments/retries.
- 221 offline tests passed on Linux Python 3.12.14. Intercepted-HTTP tests exercise
  all four real agent classes and actual provider parsers/tool wrappers for train,
  flight and compare; overnight stays, hotel invalidation, source/assumption labels,
  clarification, provider stops/partial alternatives and sanitized report/usage.
- Preview passed with zero calls. No real Groq/travel API requests were made here.
  No dependency changes. Windows and connected live verification remain pending.

## Checkpoint 10 live result and recovery revision

- User verified 221 tests on Windows Python 3.12.7. A stale effective GROQ_MODEL
  first stopped the connected probe; setting openai/gpt-oss-120b corrected it.
- Reviewed connected_20261104_184653_663713_8be319, attachment
  share_results(20261104-184805).zip. Eight travel HTTP 200 responses: SerpApi 2,
  RailRadar 6. Supervisor/Transportation/Hotel completed; known usage 7,120 tokens.
  Itinerary failed with Groq HTTP 429, effective 8,000 TPM (used 5,586/requested
  2,584). Billing state is not established by this error. No full draft exists.
- Both real CC schedules and 16 hotels survived. The older itinerary worker lost
  fetched places when the model failed. Fixed by retaining places immediately
  and returning them through the graph error branch.
- Rankings use compact H01/T01 aliases with strict round-trip validation, omit
  repeated hotel scope and keep whole-trip budget decisions in Python. Assumed/
  incomplete-price explanations cannot claim verified budget fit. Old resumed
  explanations are replaced by safe scope notices; order/evidence stay unchanged.
- Added connected_recovery.py and check_connected.py --resume-report. It validates
  saved normalized evidence before loading keys, seeds LangGraph after the completed
  hotel node and resumes itinerary/finalization. No Supervisor/transport/hotel
  worker executes. At most 2 Groq calls, <=1 Maps (zero with saved places), zero
  rail/hotel/flight searches. No automatic retries, fixed waits or new dependency.
- Original run lacks saved places, so it needs one fresh Maps query. Reused source
  timestamps remain historical. Source report stays unchanged. New token/request
  counters are separate from previous-run counters. Failed unknown usage stays
  unknown. Visible model failures no longer print misleading node "completed";
  a 429 reports MODEL_RATE_LIMITED.
- 237 offline tests passed on Linux Python 3.12.14 (5.39 seconds). Includes full
  intercepted-HTTP recovery, place retention, one-correction bound, no duplicated
  searches, missing travel keys with retained places, safe ranking ID mapping,
  invalid report/option rejection and usage/source preservation. No fresh live
  requests were made here. Actual saved-report validation also passed offline:
  two train offers, 16 hotels, zero retained places, previous usage 7,120.
- This revision's Windows and resumed-live verification remain pending. The four
  agent architecture, dependencies, .env/venv and product scope are unchanged.

## 5 November hotel ranking fix

- Windows recovery tests initially had two report-encoding failures, which the
  user worked around with UTF-8 mode before the live probe. Tests now explicitly
  read UTF-8 reports.
- Live run connected_20261105_144353_861241_1918ca returned seven travel HTTP
  200 responses. Groq returned a Hotel Agent reply, but its local ID list failed
  validation. No 429 was recorded. Itinerary did not run and the report has no
  saved hotel offers, so Itinerary-only resumption is not applicable.
- A rejected hotel ID list now triggers a local sort of the same eligible
  candidates (comparable nightly price, higher guest rating, stable ID). No
  additional model/search call or unsupported affordability claim. Valid model
  ranks still apply and genuine provider/model call errors remain visible.
- 240 offline tests passed on Linux Python 3.12.14. New cases inject missing,
  duplicate and unknown IDs and verify itinerary completion with hard filters,
  warnings, usage and request bounds preserved. No live API calls were made here.

## Checkpoint 11: saved-trip app

- The user's resumed 5 November Jaipur run passed the connected checks. It reused
  saved trains, hotel options and places, with zero new travel-provider calls.
- `frontend/app.py` is a local Streamlit screen with a **Load sample trip** button.
  `frontend/jaipur_sample.json` is a display-only projection of the successful
  report: two train legs, one hotel, nine activities, and six opening-hours warnings.
  It retains quote labels and source timestamps and omits model notes, prompts,
  raw responses and API credentials. Historical quotes and availability are not
  refreshed; the ₹25,000 budget fit remains unknown.
- Custom sorting stays out of scope. Existing agents, filters, ranking, dependencies
  and provider behavior are byte-for-byte unchanged from Checkpoint 10 Hotel Fix.
- Verified on Linux Python 3.12.14 with pinned Streamlit 1.66.1: 241 offline
  tests passed (5.34 seconds). The new test loads the actual Streamlit screen and
  clicks the sample button with socket connections blocked. The local CLI launch
  returned HTTP 200 from Streamlit's loopback health endpoint. No new model or
  travel-provider requests were made. Windows UI launch remains to be checked.

## Checkpoint 12: live planning from Streamlit

- The user confirmed the Checkpoint 11 screen on Windows and reported one fresh
  uninterrupted live CLI pass: 10,968 reported model tokens, two SerpApi requests,
  six RailRadar requests. This tested the Delhi/Jaipur train route with demo fares.
- Streamlit now offers a live form next to the offline sample. It posts once to
  local FastAPI and shows the existing workflow's selected transport, hotel,
  validated activities, quote provenance and warnings. Incomplete results remain
  labeled. The backend keeps keys server-side and does not contact providers on
  startup or health checks. Existing agent, provider and ranking code is unchanged.
- The browser route is fixed, with one to seven nights and up to six adults.
  Transport can be train, flight or comparison; rail prices remain labeled demo.
  Structured intake needs no model call to extract the form fields. Natural-language
  Supervisor intake remains available through the CLI.
- Linux Python 3.12.14: all 246 offline tests passed (6.31 seconds). New tests
  cover Streamlit submission through FastAPI and the existing graph, flight and
  comparison routing, partial output on model rate limits, and validation before
  credential loading. FastAPI and Streamlit loopback launches both returned HTTP
  200 on their health endpoints. No live provider calls were made. The Windows
  browser live submission still needs verification.

## Checkpoint 13: trip chat and Markdown

- User verified the Checkpoint 12 live browser train flow: outbound and return
  trains, a hotel quote, and eight planned activities. An earlier request hit
  Groq's rate limit; the later successful run was after restarting FastAPI.
- The primary Streamlit tab is now conversational. `POST /chat` uses the same
  Supervisor and remembers pending answers and applied planning state. It asks
  about missing details and applies complete changes through the graph. Hotel-only
  changes reuse trains and place candidates; a failed revision can retain the
  previous usable plan. Browser scope stays fixed Delhi/Jaipur. No permanent locks,
  database or multi-city routing is introduced by this checkpoint.
- Markdown download uses the displayed result, including demo fare, incomplete
  quote, opening-hours and budget caveats. No model or provider calls on download.
- All 249 offline tests passed on Linux Python 3.12 (9.57 seconds). No live
  provider calls were made. Windows chat verification is pending. Tests simulate the complete chat
  interaction and check travel call counts, route guard, previous plan retention,
  expired session handling and export disclosures.

## Next actions

1. Install Checkpoint 13 preserving .env/venv. Restart FastAPI and Streamlit using
   the two README commands.
2. Test one chat: start with train/class/adults but no dates, answer the
   clarification, ask for a hotel-only change, and download the displayed plan.
   Offline mode is still available through **Load sample trip**.
3. Add general location candidate discovery/selection and optional daily weather,
   retaining ambiguity and out-of-horizon warnings. The fixed probe is not general
   city coverage. Keep verified schedule and assumed price provenance separate.
4. Add selection/locks, serialized trip lifecycle, numbered view-only snapshots,
   stale-update rejection and last-successful-plan preservation.
5. Add final Supervisor explanation and layout polish,
   representative evaluations/full live user journeys and owner learning guide.

## Checkpoint 13 itinerary place ID patch

If the scheduling model still returns unknown or repeated IDs after one
correction, try omitting those rows and revalidate the remaining visits.
Even after omission, empty schedules and timing conflicts still need review.
All 253 offline tests passed under Python 3.12 on Linux, including four added
regression cases. The patch has not been tested against live providers.

## Checkpoint 14 route selection

- Browser chat and form accept one round trip between two distinct cities from
  Delhi, Jaipur, Bengaluru, and Mysuru. Routes involving Mysuru are train only.
- Ran `python -m pytest -q --tb=short` on Linux with Python 3.12. The 260 tests
  cover both directions of the new train and flight examples, chat clarification,
  route changes, destination queries and rejected inputs. No live requests were made.
- On Windows, install the overlay, run the offline suite and restart both
  processes. In a fresh chat, try one Bengaluru–Mysuru trip with future dates.
  Compare returned station codes and disclosures; share only sanitized warnings
  if there is no validated plan. The legacy connected CLI remains fixed route.

### Checkpoint 14 chat clarification patch

- The Windows live Bengaluru–Mysuru trip returned both legs, a hotel and an
  itinerary after a redundant CC question. A hotel cap change then kept both
  trains visible and returned a quote below INR 2,000 per night.
- Reproduced the missing class update with intercepted model output and fixed
  explicit class handling in chat. Ran `python -m pytest -q --tb=short` on Linux
  Python 3.12: 267 tests passed, including omission, redundant and unrelated
  questions, alternatives, negatives and no class. No live calls were made.
- Install the small overlay on Checkpoint 14 and restart FastAPI. A fresh chat
  can verify that “by CC train” no longer prompts for the class when all other
  required details are present. No new dependencies, API keys or route changes.

### Checkpoint 14 itinerary transfer buffer patch

- A Windows live chat recognized “by CC train” immediately, found rail and hotel
  options, but the Itinerary Agent's draft failed the 30-minute transfer gap.
- After one model correction, Python can omit conflicting visits if that is the
  only remaining scheduling error. Dates, visit times, transport and lodging
  are left alone. The usual validator approves the shortened schedule, and the
  app shows how many visits were dropped.
- All 272 tests passed on Linux Python 3.12 (offline). Cases cover overlapping
  visits, too-short gaps, a gap of exactly 30 minutes, a mixed unknown-ID
  conflict, and a known opening-hours error that still blocks the draft.
- Install over Checkpoint 14 with the previous patches applied, rerun pytest,
  and restart FastAPI. A live rerun is optional; no existing trip data or
  provider settings require changes.

### Checkpoint 15 station discovery in train chat

- Added exact and ambiguous station resolution outside the four-city catalog.
  Confirmed codes survive later chat turns and cannot be set by the Supervisor.
- Ran `python -m pytest -q --tb=short` on Linux Python 3.12: 276 tests passed.
  New tests cover exact code/name, choice and invalid confirmation, same-city
  station revision, hotel-only reuse, no match and lookup quota failure. No
  live calls were made.
- On Windows, install the overlay, run pytest and restart both servers. Use
  a fresh chat with a train route outside the catalog; for an ambiguous city,
  reply with an offered station code. Live provider coverage remains unverified.

### Checkpoint 15 chat intake recovery

- The Windows Kanpur Central–Lucknow prompt returned the chat intake's generic
  reply before station lookup. The exact live model decision is unavailable.
- Reproduced that reply with both empty question and empty unsupported
  decisions. A narrow, explicit round-trip template can now recover the input
  without another model call. No station or service is guessed.
- Ran `python -m pytest -q --tb=short` on Linux Python 3.12: 280 tests passed.
  The tests confirmed station choice, completion, and no provider search for
  multi-city or booking requests in this fallback. No live calls were made.
- Install over Checkpoint 15, restart FastAPI, then test the original wording
  in a new chat. The station options still depend on live provider data.

### Checkpoint 15.1: direct train intake

- A Windows retry with the same complete request showed the intake's
  model-error reply, which bypassed the earlier recovery for empty decisions.
- The documented complete template now goes straight to Python validation
  and station lookup. Groq is initialized only for free-form intake or
  subsequent trip planning. The intent rules for other messages are unchanged.
- Offline tests replayed the exact screenshot prompt with the clock fixed at
  19 November 2026 and Groq unavailable, and ran a separate complete
  station-choice workflow with fake provider responses. No live calls made.
  All 280 tests passed via `python -m pytest -q --tb=short` on Linux Python 3.12.
- Install the cumulative Checkpoint 15.1 intake overlay on Checkpoint 15.
  Restart FastAPI, click New chat, and test the input once.

### Checkpoint 15.2: class-aware train shortlist

- Live Kanpur Central–Lucknow chat reached station lookup and accepted CNB and
  LKO. It returned a CC train for the return and a hotel, but neither of the
  two outbound timetables checked confirmed the requested class.
- The browser now prioritizes likely CC/EC train types, then checks one extra
  candidate if neither of the first two produces a usable option. Type does
  not verify class. Station choices and fare mode are unchanged.
- Ran `python -m pytest -q --tb=short` on Linux Python 3.12: 283 passed.
  New cases cover priority, third-candidate recovery and an exhausted
  shortlist. No live calls were made.
- Install over Checkpoint 15.1 and restart FastAPI. The original request in a
  new chat can recheck the route once; live dates and availability may differ.

### Checkpoint 16: airport lookup in Trip chat

- Added airport lookup by Indian city, airport name or IATA code for flights
  and flight/train comparisons. Ambiguous results wait for a code reply.
  Flight-only requests do not use RailRadar. Comparison station resolution
  stays tied to the airport's resolved city. The form still uses the catalog.
- Ran `python -m pytest -q --tb=short` on Linux Python 3.12: 288 tests passed.
  Offline cases cover airport choice, changing a same-city airport, the
  comparison flow, non-Indian matches, an empty result and a quota error.
  No live calls were made.
- Install over 15.2 and restart both servers. Try a domestic economy round
  trip in Trip chat between cities outside the original flight catalog.

### Checkpoint 16.1: comparison recovery

- The Delhi–Lucknow CC comparison searched both modes live. No CC option was
  confirmed in the limited rail shortlist, so the final plan used flights.
  A 3A revision reached both providers but returned a model HTTP 400, leaving
  the previous plan visible. Its pasted warning did not identify the role.
- Added comparison ranking fallback, conditional reuse of the validated
  activity schedule, stage-specific warnings, and direct intake for the
  documented comparison request. No additional provider requests were added.
- Ran `python -m pytest -q --tb=short` on Linux Python 3.12: 292 passed.
  Offline coverage includes both modes appearing in the ranking candidates,
  ranking rejection, compatible and incompatible old itinerary after
  itinerary rejection, and a rate-limit failure without unsafe recovery.
- Install over Checkpoint 16 and restart FastAPI. In a new chat try the full
  comparison template with 3A; select a listed airport or station if prompted.
  No live calls were made for the patch itself.

## Still pending in agreed scope

Weather,
user selection controls/locks, durable application lifecycle, plan snapshots,
systematic evaluation. Graph checkpoints are not
product versions. No full application readiness claim is supported yet.

## Preserve decisions

Four agents; one destination; Python 3.12.7; LangGraph/LangChain, Groq, FastAPI,
Streamlit. Windows root: D:\Projects\GenAI\Agentic AI\Travel Planning Agent.
No automated booking/payment, separate search cache, vector database or RAG.
Approved exception: deterministic, clearly labelled assumed train prices for demos;
real schedule/class evidence is still required and real affordability stays unverified.
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
