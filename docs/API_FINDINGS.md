# API evidence and integration boundaries

These findings summarize the earlier probe runs reviewed in this conversation.
The application now has separate hotel/Maps/flight adapters; graph retrieval still uses
synthetic data. Keys and raw private
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
Flight integration followed in checkpoint 07; RailRadar/weather adapters and
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
New flight retrieval is offline-tested only; real Windows verification is next.
