# API evidence and integration boundaries

These findings summarize the earlier probe runs reviewed in this conversation.
The application has hotel/Maps/flight/rail adapters and a connected provider-backed
graph probe. The separate check_agents.py retains synthetic travel data. Keys and raw private
responses are excluded. Evidence is feasibility testing, not a reliability SLA.

| Service | Reviewed observations | Application rule |
|---|---|---|
| SerpApi Google Flights | Eight parameter variants returned data; booking detail required Google POST handoff | Use provider search links; never invent a direct payment URL. Round-trip search results do not alone establish a fully verified outbound/return pair |
| SerpApi Google Hotels | Eight variants returned data; cheap results may be hostels/dorms; detail review was needed | Distinguish nightly/stay total, taxes, occupancy, room type, star class and guest rating |
| RailRadar | Direct services, fares and timetable probes returned data; seat endpoint returned HTTP error/plan restriction | Use four endpoints: station lookup, Trains Between, Fare Calculator, optional Timetable. Station autocomplete still needs application-level live validation |
| SerpApi Google Maps | Jaipur search returned 20 places with coordinates/ratings; no structured admission prices; one detail query worked | Use places and known hours; no extra attraction-price research. Deduplicate near-identical candidates carefully |
| Open-Meteo | Seven daily forecast dates returned usable data for a Jaipur probe | Optional near-term daily weather. Out-of-horizon trips show unavailable; do not present forecasts for unsupported dates |
| Groq GPT-OSS 120B | Five bounded synthetic tests passed across saved runs | Suitable initial candidate; not an end-to-end application evaluation |

## Parameters and normalization

Flights: map explicit sort_by, max_price, class, passenger and stop preferences
using provider-documented values. Do not infer a round-trip total from one leg.
Hotels: support explicit minimum/maximum nightly price, guest rating and hotel
class. In the tested API, guest-rating code 8 represented 4+, while a 4.2 user
threshold needed provider 4+ followed by Python filtering. Exact 3 stars differs
from 3 stars and above. Reconfirm mappings against current provider docs during
implementation. Never substitute guest rating for star class.

Rail fixed order and restrictions are in ARCHITECTURE.md. Fare errors are not
zero fares. Availability remains unverified even when fare/timetable succeeded.

Maps response shape differs between search and details (including hours and
place types). Normalize in the adapter. Names, coordinates and provider IDs do
not alone guarantee duplicates are removed; the probe found nearby candidates
with conflicting names/hours. No live-map feed or navigation integration.

Open-Meteo: daily forecast for relevant available dates; requested coordinates
can differ from model-grid coordinates. Keep both concepts distinct. Historical
climate is not a substitute for a missing future forecast. Use Asia/Kolkata for
Indian trip dates and explicit local timestamps for overnight train/flight legs.

## Groq results already reviewed

| Case | Behavior | Tokens | Client elapsed |
|---|---|---:|---:|
| G01 | Complete preference extraction | 752 | 1.297 s |
| G02 | Missing-date clarification without invented budget | 662 | 2.594 s |
| G03 | Hotel tool selection and exact arguments | 403 | 0.656 s |
| G03-RESULT | Eligible hotel selection, INR 12,800, not booked | 604 | 0.953 s |
| G04 | Grounded itinerary, buffers, hours, INR 13,000 subtotal | 1,025 | 1.782 s |

These are individual successful synthetic examples, not a statistically measured
accuracy score. Measured usage includes the provider's reported reasoning tokens.
An earlier non-JSON 403 attempt had unknown usage. G02 was recovered offline from
its original saved response; a Windows PermissionError replacing the report ZIP
was later identified during G03. These local report failures are not evidence of
model failure. The final two calls used a deliberate 64-second quota wait; do not
include that in model latency or carry it into paid application configuration.

Original free Groq limits were 30 RPM / 8,000 TPM / 1,000 RPD / 200,000 TPD.
User decided to upgrade to pay-as-you-go; actual activation/limits are pending.
Rate limits and eligibility must be checked in the account, never inferred from
these historical numbers. SerpApi and RailRadar allowances remain independent.

## Still to verify

- ChatGroq structured output: all four role paths passed a live synthetic check;
  specialist tool-use integration remains pending.
- Station autocomplete, ambiguous city/station handling and application adapters.
- Requested return journeys: normalize outbound and return offers separately.
- Real occupancy/room completeness, taxes and booking/source link rendering.
- Integrated API error handling, throttling and full user journeys on Windows.
- Evaluation across representative dates, empty results and incompatible locks.

Provider docs: https://serpapi.com/google-flights-api ;
https://serpapi.com/google-hotels-api ; https://serpapi.com/google-maps-api ;
https://railradar.in/docs ; https://open-meteo.com/en/docs ;
https://console.groq.com/docs . Prior probes inform the implementation, but
current documentation and actual normalized response tests must establish each
adapter contract before claiming support.


## Application verification through checkpoint 05

The corrected Supervisor wrapper passed a live request with all fixed preference
checks true, using 1,161 reported tokens. All four role implementations now pass
intercepted-HTTP integration tests. The user verified the corrected 79-test suite
and a live four-role synthetic check: 6,845 tokens across five calls, one itinerary
repair, INR 20,100 synthetic subtotal, no remaining schedule errors. This is one
successful scenario, not an accuracy score. Seat availability stays unverified.

## Checkpoint 06 contracts

Hotel and Maps adapters now pass intercepted-HTTP tests; full suite 108 tests.
No real provider calls were made in this build environment. The user subsequently
ran the hotel/Maps check on Windows: PASS_CHECKS, exactly two HTTP 200 responses.
Flight integration followed in checkpoint 07, rail in checkpoint 08; weather and
LangChain tool-use integration remain pending.

Current hotel documentation was checked during implementation:
https://serpapi.com/google-hotels-api and https://serpapi.com/google-hotels-properties .
Rating 7 means 3.5+, 8 means 4+, 9 means 4.5+. A user threshold such as 4.2 uses
the broader provider bucket plus an exact Python filter. Hotel class accepts
2/3/4/5 and comma-separated choices; 1 star needs local filtering. Min/max bounds
are nightly-display filters. Prefer explicit extracted_after_taxes_fees when
present; extracted_lowest/display price alone does not establish included taxes.

Saved hotel probe fields did not establish room occupancy or room type. The adapter
therefore keeps covers_all_travelers=false and room_type=null even when the search
requested two adults. Exact requested date/currency/adult echoes confirm search
scope, not room capacity or a guaranteed payable amount. A missing total_rate
stays unknown; multiplying an average would overstate the evidence. This means
real hotel quotes currently keep complete trip affordability unknown.

Maps search/detail hour formats are normalized separately. Admission fees are
not fetched; malformed or ambiguous hours stay unknown. Exact IDs deduplicate
identical records, but alternate IDs for nearby aliases are not yet merged.
The two-call checker saves only normalized data and field names, with request
inputs, source/fetch timestamps and warnings; no raw provider bodies or secrets.

## Reviewed checkpoint 06 live report

Run providers_20261103_171503_728051_43edf0: Jaipur, 17–20 November 2026, two
adults, exactly 3 stars, INR 2,000–4,000 nightly, guest rating at least 4.2.
18 normalized hotels; 14 pass every requested listing filter. Four 4.1-rated
properties were correctly excluded by Python after the API's broader 4+ filter.
20 normalized places with coordinates; all have only three parsed weekday entries
(Tuesday–Thursday), so other weekdays remain unknown. No complete payable hotel
totals were established: occupancy/type and tax inclusion remain unverified.

One hotel's website URL carried checkin=26-08-2026 and num_nights=1, conflicting
with this three-night November search. That is a source-link quality issue, not
proof that the API's returned quote was for August. Checkpoint 07 discards the
conflicting URL. Generic fallback search links may not preserve selected dates.
Amer Stepwell / Panna Meena ka Kund are about 10 m apart with differing reported
hours. They are now flagged as possible aliases, not asserted to be identical.
No additional live queries were needed to identify or test these issues.

## Checkpoint 07 flight contract

Primary docs checked: https://serpapi.com/google-flights-api and
https://serpapi.com/google-flights-results . One-way searches use type=2; sorting
codes are 1 top, 2 price, 3 departure, 4 arrival, 5 duration, 6 emissions. Explicit
class and max_price parameters are supported in the adapter. It never treats an
outbound-only round-trip result as a complete outbound/return pair. There is no
booking-options request or invented payment URL.

The new checker uses two separate one-way requests for DEL/JAI. Their combination
is not a bundled round-trip fare. Native price fields do not establish tax/baggage/
booking fee completeness; multi-passenger coverage is kept unverified. Currency
and passenger/date/route echo mismatches are rejected. Unknown prices stay null.
Airport bindings are explicit; resolving arbitrary user cities is still pending.
Connection airport timezones must be known; airport-change transfers are skipped.
The user subsequently verified live flight retrieval on Windows; see below.

## Reviewed checkpoint 07 live flight report

Reviewed attachment: share_results(20261103-173349).zip.
Request timestamps were 17:32:44 and 17:32:47 UTC
on 3 November 2026. Two HTTP 200 responses, two adults, Economy, price sort, no cap.
DEL to JAI on 17 November normalized 8 of 10 raw results; JAI to DEL on 20 November
normalized 7 of 8. Every retained option had a known quote and passed the requested
listing filters. Airlines, flight numbers, aware segment times and Google search
URLs are present. Multi-passenger/tax/baggage/fee completeness remains unverified.

Three records were skipped under a combined diagnostic; their precise causes
cannot be inferred from the normalized ZIP. They could involve route/date/time
validation or unresolved airport zones. Checkpoint 08 adds safe per-record codes
and validated airport IDs, without storing raw discarded content. No new live
flight request was needed to implement and test that reporting improvement.

## Checkpoint 08 RailRadar contract

Current primary references:
https://railradar.in/docs/search-stations ;
https://railradar.in/docs/trains-between-stations ;
https://railradar.in/docs/get-train-details ;
https://railradar.in/docs/authentication ;
https://railradar.in/docs/rate-limits .
The fare documentation URL https://railradar.in/docs/train-fare-calculator
redirected to the docs index during review. Official indexed documentation and
pricing still describe GET /v1/trains/{number}/fare; earlier saved T05/T06 quotes
also succeeded. This does not establish current key access. The bounded live
check must determine whether fares remain accessible; preserve schedules on errors.

The adapter uses Bearer authentication in a header. Lookup accepts code/name
candidates; the probe selects exact NDLS/JP codes explicitly. Date-filtered direct
services use boarding-station dates, live=false/byCity=false. Coach classes and
stop order are checked for at most two duration-shortlisted trains before a single
General-quota fare query. No seat/PNR/live-running endpoint is called.

The probe reports numeric quota headers and stops on reported zero availability
or its own six-request budget, without waits/retries. Operated classes do not prove
vacant seats. Fare response fields do not fully establish party/tax/payable scope;
the amount stays unverified and is not multiplied by adults. Missing totals stay
null. No full trip affordability claim can follow from the probe passing.

Offline replay passed: T02 normalized 20 scheduled services, T07 normalized train
12952 coach classes/stops, T05 preserved INR 3,165 as an unverified quote with 12
numeric components. No fresh live API requests here. Station lookup/current fare
access and new Windows execution were pending when checkpoint 08 was delivered.
That checkpoint's full offline suite had 178 tests. Subsequent results follow.

## Actual rail result and approved mock-price mode

Reviewed share_results(20261103-175535).zip: five HTTP 200 responses confirmed
station lookups, two scheduled services, and timetables for 12958 and 12015.
The 12015 CC fare call returned HTTP 403, code PLAN_UPGRADE_REQUIRED. The response
said fare access needs a Developer/Growth/Scale subscription. Reported remaining
monthly quota: 86. This was neither a rejected API key nor quota exhaustion.
Prior successful fare probes do not override this newer access result.

The user approved explicitly assumed train prices for interview demos instead
of purchasing a rail subscription. No claim is made that these are real or
estimated railway fares. The SHA-256 generator is our own demo rule, not provider
data. It supports any new confirmed five-digit train/route/class combination,
using arbitrary class ranges and a reproducible per-adult result. Mock mode
never queries the paid fare endpoint; live failures never switch automatically.

Zero-network replay of the reviewed report passed: 12015 CC received an assumed
INR 618 per adult / INR 1,236 for two; 12958 has no CC and stayed unpriced. Source
timestamps and real schedule metadata were preserved. This is historical evidence
replay, not fresh availability. Independent synthetic hashing example 13240 /
NDLS / JP / 3A gives INR 897 per adult; no route/class validity follows from it.

Checkpoint 09 had 209 passing offline tests on Linux Python 3.12.14. The user
verified all 209 on Windows and its saved-report replay passed, with zero calls.
Reviewed share_results(20261104-150038).zip preserves original source timestamps
and clearly marks INR 618/adult / 1,236/two as assumed for 12015 CC; no CC price
was added to 12958. This is not a fresh fare or availability observation.

## Checkpoint 10 integration boundary

Actual provider adapter/parser code now runs through four agent classes and the
graph via LangChain tool wrappers. All 221 offline tests pass; full intercepted
HTTP cases cover train, flight and compare, both directions, overnight hotel
dates and source/error/assumption propagation. These are invented response
payloads over MockTransport, not new live-provider evidence or an accuracy score.

The new connected live probe has explicit DEL/JAI and NDLS/JP bindings, no general
city resolver. It requests train/mock by default and never calls paid rail fares.
Unverified room/passenger/tax scope still prevents actual affordability claims.
Provider request budgets are independent of model quota. No fresh API calls were
made during this build; new Windows/connected-live verification is pending.

## Reviewed checkpoint 10 connected failure and recovery

Reviewed share_results(20261104-184805).zip, run
connected_20261104_184653_663713_8be319. The user also verified the original
221-test suite on Windows Python 3.12.7. All eight travel requests returned HTTP
200: two SerpApi queries (hotel/Maps) and six rail schedule/timetable queries.
The two confirmed CC train legs received clearly assumed fares locally, with
no paid fare endpoint. Sixteen eligible hotels were retained. Hotel occupancy/
tax scope remained unknown, as expected.

Known completed model usage was Supervisor 1,260, Transportation 1,071, Hotel
4,789 = 7,120 tokens. Groq rejected the Itinerary request with HTTP 429 before
reported completion. It reported service tier on_demand, limit 8,000 TPM,
used 5,586 and requested 2,584; the failed call's usage is unknown. These counters
are different measurements, not an arithmetic inconsistency. The error establishes
the key/organization's effective limit for that request, not the user's billing
state. The selected model was openai/gpt-oss-120b. An earlier local failure used
a stale effective GROQ_MODEL; that was corrected before this run.

The itinerary was absent because of model quota, not unsuccessful hotel/rail
retrieval. Maps succeeded but the original code lost its normalized places on
the subsequent model error. The recovery revision retains those places for future
failures, shortens rankings and resumes only the unfinished itinerary. The old
report necessarily needs one new Maps search; it cannot recover missing places
from a normalized report that never saved them.

The saved explanations also claimed budget fit with assumed/incomplete quotes.
Revised rankings and resumed old recommendations replace that unsupported prose
with explicit price-scope notices. Actual costs remain unknown; no payable fare
or room-scope evidence has been invented.

The actual saved report passes recovery validation offline: two train offers,
16 hotels and unchanged source timestamps can be reused. No new requests or keys
were needed for that validation. The recovery revision passes 237 offline tests
on Linux Python 3.12.14. New Windows/resumed-live verification remains pending.

## Reviewed 5 November hotel ranking failure

Run connected_20261105_144353_861241_1918ca, attachment
share_results(20261105-144512).zip: six RailRadar HTTP 200 responses, one SerpApi
hotel HTTP 200, and 4,260 reported model tokens. The Hotel Agent's structured
reply failed the local alias check. The report does not retain the invalid list,
so it does not establish whether aliases were missing, repeated or unknown. No
429 or provider failure was reported. Itinerary did not run and Maps was not
called. Short aliases alone did not prevent the validation failure.

The hotel fix rejects the ranking and continues with existing eligible hotel
records in a local order. Offline intercepted responses exercised all three
invalid-list shapes. The new ranking path still awaits live verification.
