# Checkpoint 09 walkthrough

Four LLM roles, graph orchestration and draft schedule/cost checks are implemented
using synthetic graph retrieval. Separate hotel/Maps/flight/rail adapters are implemented;
graph wiring, weather, general location selection, locks, plan versions and UI remain
pending. Earlier sections describe foundation modules;
the checkpoint 05 section below describes the current specialist path.

## Read in order

1. `backend/schemas.py`: preferences, sources, normalized offers and prices.
2. `backend/services/costs.py`: deterministic budget arithmetic.
3. `backend/services/replanning.py`: dependencies and selection-lock protection.
4. `backend/config.py`: explicit server-side configuration and secret handling.
5. `tests/test_domain.py`: examples of accepted/rejected behavior.

## A request example

TripPreferences with Delhi, Jaipur and two adults leaves dates, budget, class and
currency unknown. missing_required() identifies dates for future clarification.
Pydantic rejects reversed dates, negative prices, invalid ratings, empty cities
and unexpected fields. Natural-language extraction now lives in agents/supervisor.py.

Source requires an aware timestamp. Optional URLs must be HTTP(S); that does not
prove a URL is a valid booking link. synthetic=True distinguishes fixtures.
HotelOffer separates nightly and stay amounts. TransportOffer requires aware
departure/arrival times and does not assert seat availability. Adapters must
verify traveler coverage, tax completeness and totals; these are not inferred.

## Prices

The initial return-trip product requires outbound, return and hotel-stay quotes.
summarize_costs() uses Decimal: 1000.10 + 1000.20 + 4000 = exactly 6000.30.
If any required component is missing, unverified, in another currency, does not
cover all travelers or has unknown taxes, complete_subtotal is null and budget
status is unknown. known_subtotal contains comparable reported amounts only;
it is not a complete payable trip price. No currency conversion is assumed.
Food, local transport and attractions remain excluded. Even a complete subtotal
is a timestamped quote, not a reservation or price guarantee.

## Replanning and locks

affected_components(before, after) compares validated preference fields. A
hotel-price change invalidates hotels, itinerary and costs; interests change
invalidates places and itinerary. Dates also invalidate weather. The future
graph must execute the returned work, deciding whether to search or rerank held
offers. The dependency function itself makes no calls and changes no state.

enforce_selection_locks(current, proposed) identifies replacement, removal or
unlocking of a locked selection without mutating it. The future graph must also
validate whether retained offers are compatible with changed dates/route/occupancy
and ask the user when incompatible. This extra enforcement is still pending.

## Configuration and verification

Settings() explicitly loads the project's .env; imports do not. Environment
variables take precedence. Keys use SecretStr, are excluded from repr and dumps,
and are only required at an explicitly requested live boundary. Do not log
complete settings/errors in future handlers: this is not a universal scrubber.
Relative data_dir resolves from project root. Provider clients are created only
at explicitly invoked live boundaries, never automatically during imports.

Run `venv\Scripts\python.exe -m pytest -q` from the Windows project root.
Tests disable socket connections and use temporary fixture keys, not real .env.
The separate environment script verifies imports and a tiny graph, not the
travel graph. Offline tests passing do not prove live integrations work.

## Follow the actual workflow

Read backend/graph/state.py, then builder.py. TripState defines the JSON-compatible
fields nodes share; credentials never enter it. prepare merges a structured
request patch into existing validated preferences. Missing/invalid inputs route
to clarify, which calls interrupt() before any specialist work. Resume on the
same thread with Command(resume={...}); the reply is validated before proceeding.
The caller must not launch a fresh ordinary turn while a clarification is pending.

The dispatch function reads the pending list: transport first, hotels next,
itinerary last. Each completed node removes its task and routes back through
dispatch. This is conditional-edge routing, not an LLM choosing arbitrary code.
Changed preferences use the existing dependency table. Interests-only updates
preserve transport/hotels and rerun itinerary; date updates invalidate dependent
offers before new work begins. No-change turns run no workers. Independent
thread IDs isolate separate trip state; one trip is processed serially.

Workers are ordinary injected functions with explicit signatures so the real
agent integration can replace synthetic workers later without rewriting edges.
The included backend/demo_workers.py supports only the Delhi-Jaipur fixture;
all its sources and itinerary outputs are labeled synthetic. It is not a fallback
for live errors and does not pretend to schedule attractions or honor arbitrary
user search filters. Invalid/unsupported demo requests are not live searches.

Expected worker errors return warnings and empty affected results; remaining
steps can still complete. Errors are not replaced with invented offers. The
workflow's final status is workflow_complete, not plan_validated. Since offers
have not been selected, finalization cannot pick an arbitrary first quote and
claim affordability: the complete subtotal stays unknown.

## Checkpoint persistence

The caller supplies a checkpointer and controls its lifetime. The command-line
demo uses InMemorySaver and loses state when it exits. A test uses SqliteSaver,
closes it, rebuilds the graph on the same temporary database and resumes the
clarification. Persistent application trip handling and product version storage
are still pending; graph checkpoints are not numbered plan versions.

The invoke calls use a recursion_limit of 30 to catch accidental routing cycles.
This is a graph-safety limit, not the old API-probe request cap. User clarification
can pause for as long as needed without issuing model/provider calls.

Demo command: `venv\Scripts\python.exe scripts\demo_workflow.py`.
Expected: missing-date clarification, workflow_complete, then an interests-only
change whose trace contains no repeat transport/hotel work. No API keys required.

## Supervisor integration in checkpoint 04

A new supervisor graph node runs before prepare. With a configured Supervisor,
user_message becomes a validated preference patch and is cleared after processing
to avoid repeated calls. Existing structured request_patch input still skips the
LLM. A natural-language clarification reply also passes through Supervisor before
prepare; structured resume dictionaries continue working. Failed model calls
leave prior preferences unchanged. Message-only decisions stop before specialists.

backend/llm.py creates ChatGroq only on explicit request. invoke_structured uses
native JSON schema with strict=True and no tools attached. Intercepted-HTTP tests
verify the pinned wrapper sends this format, but live provider access and actual
model semantics remain pending. Optional hosted tracing is explicitly disabled.

backend/agents/supervisor.py returns intent plus preference updates. Allowed field
names are enumerated. Duplicate updates, invalid merged constraints and attempts
to modify preferences in a question/unsupported decision are rejected. Omitted
preferences remain unchanged. Multi-city/payment requests are prompted as
unsupported; this semantic classification needs live evaluation, not just tests
of the schema. Hotel class remains separate from guest rating.

A schema-valid answer can still contain an incorrectly extracted city/date;
representative extraction evaluations and user review remain necessary. The
Supervisor does not bypass Python routing or mandatory-field checks. Its final
plan explanation and remaining delegation responsibilities will be added later.

Model/API failures expose safe messages and optional numeric HTTP status, not
raw provider responses. State may retain parsed decisions and token counters,
never private reasoning. The first integration check uses one attempt, zero
automatic retries and a 45-second HTTP timeout; it does not inherit the old
five-request/day cap or fixed 65-second delay.

scripts/check_supervisor.py without --live loads no configuration/model. With
--live, it makes one Supervisor request for a fixed sample, then uses explicitly
synthetic downstream workers. It saves a unique JSON under ignored data/reports/
with parsed preferences, checks and usage. Missing usage on failure is unknown
consumption. This is not a complete live multi-agent travel demo.

References: https://console.groq.com/docs/structured-outputs and
https://docs.langchain.com/oss/python/integrations/chat/groq . Tool selection and
strict structured answering will use separate calls where required by Groq.

HTTP diagnostic revision: safe_provider_error() keeps only message/code/param/type
from structured provider errors. It redacts the current key before truncating,
and never copies failed_generation or entire exception/body objects. A safe
provider error travels through ModelCallError to state and the JSON report.
This preserves the reason for a rejected request without exposing generated
private content. Provider requests with a numeric failure status now have outcome
PROVIDER_REQUEST_ERROR rather than being mislabeled as extraction-check failures.

Confirmed schema correction: JSON Schema number also covers integers. Groq
rejected the previous value union because it listed both integer and number.
PreferenceChange now uses StrictFloat as its only numeric branch, so its schema
contains number once. validated_patch() converts exact whole values to Python
int for adults, hotel_class and flight_sort_by; fractional values, booleans and
nonfinite numbers are rejected. The integer constraints in TripPreferences
remain strict. A regression test walks the actual outgoing wrapper schema to
catch the overlap before future live requests.


## Checkpoint 05: follow the four-role path

Start at scripts/check_agents.py, which constructs ChatGroq and the four classes
then injects them into build_workflow(). Supervisor extracts preferences. The
conditional router then runs TransportationAgent, HotelAgent and ItineraryAgent
only when needed. Sources in specialist_fixtures.py are all synthetic; no real
flight/train/hotel/place API is contacted by this script.

TransportationAgent receives search results, applies eligible_transport(), and
asks the model to rank all eligible IDs with a short explanation. Train/flight
mode and class, route/date, traveler count and explicit flight cap are enforced
in Python. HotelAgent similarly filters dates, occupancy, class/rating and known
nightly prices. Unknown values cannot satisfy explicit hard filters. apply_ranking()
rejects foreign/duplicate/omitted IDs; no LLM text becomes a fabricated offer.

ItineraryAgent uses the first ranked valid option in each leg and first hotel as
proposed recommendations. It keeps their IDs in the draft. It receives only known
place candidates; Schedule contains IDs and local date/time strings. Python
validates actual timestamps against trip boundaries, known hours, 60-minute
arrival/departure buffers and 30-minute estimated transfers. Missing hours warn;
known closed days reject. Overnight hour normalization and verified route travel
times are not implemented. At most one repair call receives the exact errors.

The graph finalize node re-looks-up the recommended IDs and calls summarize_costs().
The model never supplies the numeric subtotal. Over-budget schedules require
review; incomplete price basis remains unknown. A synthetic complete quote can
produce a synthetic verified subtotal; it says nothing about a real payable fare.
All model ranking reasons and schedule notes still need semantic quality review.

Usage is recorded separately for Supervisor and the three specialists. Itinerary
usage includes a correction if one occurred. Counts reset per new turn, so an
explanation-only reply does not charge old specialist usage again. An invalid
ranking or model/provider error stops further model work and returns partial data.

No locks or numbered product versions are applied yet. The older lock primitive
is not the full user-facing feature. Read docs/PROGRESS.md for exact remaining work.

Numeric-input correction: the update value schema is generic, so a model can
return a string for a numeric field. validated_patch() now accepts exact numeric
strings ("3", "3.0") and explicit hotel labels ("3-star", "3 stars"), then checks
integrality and domain bounds. It never rounds/truncates fractions or interprets
ambiguous ranges. The original rejected value in the live report was not saved;
these are covered valid-representation cases, not a reconstruction of that reply.

Supervisor validation failures now attach the parsed decision and token usage
to ModelCallError. The graph retains this diagnostic data without applying the
patch. invoke_structured() extracts usage before parser/finish checks, so even
a rejected/truncated response can report known consumption. Specialist failure
usage adds only the failed call's available counters to earlier successful calls.
The live report uses null when no counter is available, not a misleading zero.

## Checkpoint 06: follow one real search

1. `scripts/check_providers.py` previews by default. Only `--live` loads the
   local SerpApi key and creates the HTTP client. It builds explicit Jaipur test
   preferences; these are not a Supervisor decision or saved user trip.
2. `backend/providers/serpapi.py`, `SerpApiAdapter.hotels()` maps dates, adults,
   currency, nightly bounds, star class and guest-rating bucket. One HTTP request
   returns one page. `places()` makes one Maps query from destination/interests.
3. `backend/providers/http.py` makes a fixed-host request with timeout and no
   retry/redirect. Its public audit excludes the API key. Network exceptions are
   recorded by type, not by their URL-bearing text. Quota/auth/provider errors
   stop the check before another category is attempted.
4. `parse_hotels()` constructs HotelOffer objects; explicit search echo mismatches
   reject the response. Missing totals stay null, unknown taxes stay unknown and
   occupancy remains unverified. `eligible_hotels()` applies exact user thresholds
   after the broader provider filters. A passing listing filter is not verified
   room capacity or final affordability.
5. `parse_places()` keeps coordinates, address, rating and known weekday hours.
   It handles the different search/detail hour shapes. Missing/ambiguous hours
   are unknown; closed weekdays are empty lists. Exact duplicate IDs are removed;
   nearby aliases and relevance still need review. No admission fee is researched.
6. The checker saves request inputs, normalized records and warnings after each
   case, then creates the share ZIP once. HTML tables summarize results; expandable
   records retain source IDs, URLs and fetch/provider timestamps. No raw responses
   or keys are saved. Unexpected local errors report their type without exception
   text. A hard process kill may leave a REQUESTING case; do not infer completion.

The adapter modules do not import fixtures. They are deliberately checked before
connecting to the four-role graph. `check_agents.py` still uses synthetic travel
data, so there is no mixed real/synthetic travel workflow. No Groq request occurs
in `check_providers.py`. This checkpoint adds two provider modules and one check
script rather than new agents or endpoint-specific graph nodes.

`tests/test_providers.py` intercepts actual httpx requests with MockTransport and
blocks real sockets. Tests cover parameter mapping, scope mismatches, taxes,
missing prices, hours, duplicates, errors, one/two-request limits and safe report
sharing. The checkpoint 06 suite had 108 tests. Its live hotel/Maps check passed
on Windows; the latest checkpoint has 142 offline tests.

## Checkpoint 07: follow a flight search

`check_providers.py --category flights` previews. Adding `--live` makes at most
two requests using explicit DEL/JAI AirportLocation objects. Other categories
retain their prior request counts. No new agent, graph node or dependency is added.

1. `FlightAdapter.search_leg()` checks the supplied airport cities match the
   requested direction, requires dates/adults and rejects unsupported cabins.
   It maps explicit preferences and calls the same SerpApiHttp boundary once.
   The return call reverses airports and uses p.return_date.
2. `parse_flights()` rejects echoed route/date/currency/passenger mismatches and
   round-trip scope. It combines best_flights/other_flights, not outward/return
   trips. Each result still describes only the requested one-way leg.
3. Each segment becomes a FlightSegment: IATA codes, local times with explicit
   zones, flight number, airline and class. Date/order/continuity checks prevent
   stitching unrelated segments. Overnight dates are preserved. Unknown airport
   zones, ambiguous/nonexistent DST clocks and airport-change transfers are
   skipped with a warning rather than guessed. The probe configures 15 Indian
   connection zones; this is not an airport resolver or worldwide lookup table.
4. The quote amount is used as returned, never multiplied by adults. Multi-person
   coverage and taxes stay unverified, so final affordability is unknown. Python
   still refuses to claim a complete price cap is met with an incomplete quote.
5. Each report case receives only its own request-ledger slice, so the return
   case does not accidentally repeat outbound inputs. HTML adds a flight table;
   normalized JSON retains segment and price evidence. Booking tokens are not saved.

`TripPreferences.flight_sort_by` is now restricted to 1–6. The Supervisor prompt
provides the mapping for explicit sorting requests; it does not invent a default
preference. Probe defaults are explicit test inputs, not user extraction.

`hotel_source_link()` compares recognized date/night/guest URL parameters with
the requested stay. Conflicting links are discarded and noted; a general source
link is used when present. This cannot verify opaque query tokens or checkout.

`services/place_aliases.py` flags close coordinate pairs only when names match
or both contain stepwell synonyms. The parser stores possible_duplicate_ids on
both records. validate_schedule() prevents scheduling both and treats their
hours as unverified. No model call or API lookup is needed for these rules.
Distinct nearby museums/palaces are not merged just because they are close.

The latest tests include actual intercepted HTTP parameter mapping, both leg
directions, fare scope, segments, overnight dates, timezone errors, conservative
caps, duplicate sources, bounded failure behavior and the live-report regressions.
Automatic airport resolution, weather and graph live retrieval remain pending;
the next section describes the rail adapter added in checkpoint 08.

## Checkpoint 08: follow the fixed rail sequence

Read `scripts/check_rail.py` and `backend/providers/railradar.py` together. The
script supplies explicit NDLS/JP station bindings and CC test class; these are
not end-user defaults or an automatic metro resolver.

1. `main()` previews by default. `--live` loads only the local RailRadar key.
2. `RailRadarHttp` allows only the four planned endpoint shapes on a fixed host.
   Authentication is a header, never a query argument. Requests have timeout and
   no retries/redirects. The probe supplies max_requests=6. Numeric quota headers
   can stop another call before it spends the remaining allowance.
3. Two `stations()` calls normalize StationCandidate records. City can remain
   null; the probe requires an exact selected code. General city ambiguity must
   be handled by the later user selection/clarification flow.
4. `search_leg()` checks bindings/dates/class/currency, retrieves dated direct
   services, then normalizes TransportOffer records. `from.day=2` does not shift
   the requested boarding date. `to.day-from.day` determines overnight arrival.
   Invalid route/day/duration data is skipped, not corrected by guessing.
5. Python sorts by actual duration then departure and takes at most two trains.
   `timetable()` constructs TrainTimetable with operated coach classes and stop
   codes. These do not indicate available seats. Details are needed before fare
   lookup here to avoid asking for an unsupported class or reversed station pair.
6. The first confirmed class/route receives one fare request, General quota GN.
   `apply_fare()` preserves the returned amount and numeric components, attaches
   explicit unknown-scope notes, and does not multiply by adults or invent taxes.
   Earlier scheduled records are not mutated. All other services stay unpriced.
7. An HTTP/parse/provider error stops subsequent requests. `last_result`, details
   and audit retain completed evidence, so the script can report partial results.
   It saves input/response summaries and a train table, then creates the share ZIP
   once. No raw bodies, authentication headers or model reasoning are stored.

`check_rail.py` makes no Groq/SerpApi/seat/PNR requests. The output is retrieval
verification, not an itinerary. The graph's synthetic four-role path is unchanged.
Return leg reversal/date handling is tested offline; this probe is outbound only.
Checkpoint 08 had 178 tests. Existing dependencies and venv are unchanged.

The flight report contained three generic skips. `FlightRecordError` now provides
fixed reason codes and validated airport IDs in SearchResult.skipped_records;
unexpected exception strings remain hidden. This improves future diagnostics
without new API calls or pretending the older omitted records can be recovered.

## Checkpoint 09: learn the assumed-fare path

Start with `backend/services/demo_fares.py`: one range dictionary and one function.
The dictionary has class ranges, not a list of trains. The function validates
train/route/class evidence, builds the four-part key, calculates SHA-256 modulo
the inclusive range, and multiplies by adults. Its return is a new typed offer;
the original and schedule Source remain unchanged. Everything in the price is
explicitly a demo assumption, including the per-adult unit and version identifier.

Then read the mock/live branch in `RailRadarAdapter.search_leg()`. Both modes use
the same real schedule/timetable checks. Mock handles up to two confirmed shortlist
matches locally; live makes at most one fare request. There is no failure-triggered
switch between modes. A class confirmed before a paid request stays confirmed if
the request fails. Settings defaults TRAIN_FARE_MODE to mock, even in an older .env.

`check_rail.py --replay-report` is the quickest verification: it loads a saved
generated report, validates stored offer/timetable models, applies assumptions
only to matching evidence, and saves a new HTML/JSON/ZIP report. No Settings/HTTP
client initialization, keys or requests. Historical timestamps are retained and
the report says saved replay. CLI --live is a separate mutually exclusive action.

In `services/costs.py`, assumed amounts are excluded from known/verified totals.
Complete actual affordability stays unknown. If all required amounts otherwise
have complete comparable scope, separate illustrative fields demonstrate budget
reasoning. Missing real scope does not disappear because a train price is mocked.
Graph finalization and agent warnings retain the illustrative label; future UI,
snapshot and export code must use these fields without calling them real prices.

The suite now has 209 tests. They cover unseen combinations and all class ranges,
cross-process/hash-seed stability, evidence guards, adult multiplication, mode
separation, zero-network replay and a four-agent draft with explicit assumed-price
warnings and unknown real affordability. No new framework or dependency was added.
