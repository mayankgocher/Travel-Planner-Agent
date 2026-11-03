# Checkpoint 04 walkthrough

The domain foundation, graph orchestration and optional Groq Supervisor intake
are implemented. The other three LLM agents, provider clients, offer selection,
plan validation and UI are not implemented yet.

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
and unexpected fields. Natural-language extraction is not implemented yet.

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
Relative data_dir resolves from project root. No provider client exists yet.

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
