# Checkpoint 01 walkthrough

Start with ARCHITECTURE.md to understand the planned request flow. There are no
application agents or provider adapters to walk through yet.

Existing executable: `scripts/check_environment.py` imports the intended
libraries, prints interpreter/package versions, then runs a two-node LangGraph
with a conditional edge. The nodes manipulate a small integer; no LLM or travel
facts are involved. It does not load .env, instantiate ChatGroq or contact APIs.
This proves basic dependency imports and graph execution only.

`requirements.txt` pins direct application and testing dependencies. A separate
`requirements-lock.txt` records the resolved transitive environment used for this
checkpoint. Neither is proof of Windows-specific package installation; verify on
the target Windows Python 3.12.7 environment. Use requirements.txt initially.

`.env.example` is safe to commit; `.env` is the local copy containing placeholders.
The application configuration loader will be implemented in checkpoint 02.
AGENTS.md keeps agent-coding instructions separate from runtime prompts.

As code is implemented, replace this initial walkthrough with one concrete trip
traced through API request, Supervisor, tools, state updates, validation and export.
The goal is for the owner to explain the main code within a few focused days;
this is a learning target, not a guarantee.
