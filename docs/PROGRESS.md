# Progress and continuation

Updated 3 November 2026 (India). Checkpoint 05: all four LLM roles.

## Completed and evidence

- Windows target Python 3.12.7 dependency installation and graph smoke check
  verified by user. Checkpoint 02's 20 domain tests passed on Windows.
- Clarification/routing demo completed after fixing backup test discovery.
- Supervisor native structured output verified live: all fixed preference checks
  passed, 801 input/360 output/1,161 total tokens. Report reviewed in conversation.
- Four LLM classes now participate in the graph: Supervisor, Transportation,
  Hotel, Itinerary. Downstream searches remain explicit synthetic fixtures.
- Python filters hard constraints before ranking. Unknown/repeated/missing IDs
  are rejected. Ranked results retain a short model explanation.
- Itinerary draft uses known place IDs and ranked transport/hotel recommendations;
  Python checks dates, duration, buffers, overlaps, known hours and daily pace.
  One correction call maximum; unresolved issues remain visible.
- Draft subtotal derives from the referenced recommended offers, using Decimal
  and complete scope/tax/currency checks. Over-budget drafts require review.
- Model errors stop further model work. Token usage is tracked by role per turn.
- 79 tests passed on Linux Python 3.12.14. Includes real ChatGroq HTTP intercepted
  locally for all four roles, correction bounds, malformed rankings and subtotals.
- No real Groq calls were made while building checkpoint 05. User Windows/live
  verification of this checkpoint remains pending. Dependencies unchanged.

- User subsequently verified the original 64-case suite on Windows. A live run
  stopped at hotel_class whole-number validation before the other three roles.
  The original handler discarded the rejected parsed value and response usage,
  so the reported zero did not establish zero token consumption. This revision
  normalizes numeric strings and explicit N-star labels, rejects fractional or
  ambiguous values, and retains parsed Supervisor decisions and known usage on
  rejection. Parser/truncation failures retain available usage too. Missing usage
  is now null/unknown. Report-level regression tests cover both known and unknown
  usage. Next action: verify 79 tests on Windows and run the live check once.

## Still pending — included in scope

- SerpApi/RailRadar/Open-Meteo adapters and actual place/weather retrieval.
- LangChain tool wrappers/tool-use integration with real provider adapters;
  current retrieval callbacks run in Python's fixed order.
- Selection controls and retained-lock compatibility against new requests.
- Durable application trip lifecycle, numbered view-only plan snapshots,
  stale-version protection and failed-replan preservation.
- FastAPI, Streamlit, final Supervisor explanation and Markdown export.
- Systematic representative evaluation and full live user journeys.

Graph checkpoints support clarification but are not product plan versions.
Synthetic evidence must never replace a failed live provider response.

## Next steps

1. Run checkpoint 05 offline tests on Windows. Run scripts/check_agents.py --live
   explicitly once with the local Groq key; four calls, up to five with repair.
2. Implement actual HTTP adapters, source normalization and tool wrappers. Verify
   station lookup, endpoint order, return flights, occupancy/tax basis and links.
   Derive hotel stay coverage from real arrival/departure dates, especially for
   overnight journeys; fixture schedules are same-day only. Resolve destination
   timezone rather than assuming India for international routes.
3. Feed actual Places/hours and optional daily weather. Preserve unknown or
   overnight hours as unverified until normalized. Estimate transfer buffers
   honestly; no navigation route-time service has been implemented.
4. Add selection/locks, compatibility checks, version repository and atomic
   update behavior before connecting user edit controls.
5. Add thin FastAPI, Streamlit, final explanation and Markdown download. Finish
   evaluations and a bounded live walkthrough; update owner learning guide.

## Preserve these decisions

Four agents; one destination; LangGraph/LangChain, Groq, FastAPI, Streamlit;
Python 3.12.7. Root D:\Projects\GenAI\Agentic AI\Travel Planning Agent.
No booking/payment automation, separate search cache, vector database or RAG.
Current trip results stay in graph state. Costs focus on intercity transport and
hotel; food, local transport and attractions excluded. No extra attraction fee
research. Selective replanning, locks, simple repair, versions and export remain
in scope. Groq paid upgrade chosen but actual activation/limits not confirmed;
independent SerpApi/RailRadar quotas still apply. No old daily caps/fixed waits.

## Known resolved implementation issues

Installer backups were initially collected as tests; pytest.ini now scopes tests/
and excludes backup_*/. Effective GROQ_MODEL can be overridden by the process
environment. HTTP-400 diagnostics retain only redacted message/code/param/type.
Groq rejected integer/number overlap in the Supervisor schema; one numeric branch
plus strict whole-number normalization fixed it, with a regression test and a
successful live response. Do not reintroduce the overlap in future schemas.

Read AGENTS.md, architecture, API findings and walkthrough before continuing.
Run tests before extending. Never request keys in chat. A passing synthetic
four-role check is not proof of live travel accuracy or full application readiness.
