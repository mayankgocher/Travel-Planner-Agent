# Checkpoint 02 walkthrough

The domain foundation is implemented. Agents, actual graph orchestration,
provider clients and UI are not implemented yet.

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
