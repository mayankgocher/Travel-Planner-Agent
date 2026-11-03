# API evidence and integration boundaries

These findings summarize the earlier probe runs reviewed in this conversation.
The application itself has not integrated these APIs yet. Keys and raw private
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

- ChatGroq structured output: checkpoint 04 verifies the actual wrapper HTTP
  payload with intercepted requests. Live Supervisor verification and the
  specialist tool-use path remain pending.
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
intercepted-HTTP integration tests (part of 64 offline tests). The live four-role
check still uses synthetic travel evidence and is pending user verification.
Actual SerpApi/RailRadar/weather adapters and LangChain tool-use integration are
not implemented in this checkpoint; earlier endpoint probes remain supporting
evidence, not proof of those future adapters. Seat availability stays unverified.
