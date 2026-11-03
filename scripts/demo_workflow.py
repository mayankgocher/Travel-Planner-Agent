"""Offline demonstration of an interrupt, resume and selective replan."""
from pathlib import Path
import sys
from uuid import uuid4

# Permit `python scripts/demo_workflow.py` from the project root on Windows.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from backend import demo_workers
from backend.graph.builder import build_workflow


def main() -> int:
    print(demo_workers.LABEL)
    graph = build_workflow(demo_workers.transport, demo_workers.hotels,
                           demo_workers.itinerary, InMemorySaver())
    config = {"configurable": {"thread_id": str(uuid4())}, "recursion_limit": 30}
    paused = graph.invoke({"request_patch": {"origin": "Delhi", "destination": "Jaipur", "adults": 2}}, config)
    print("Clarification:", paused["__interrupt__"][0].value)
    result = graph.invoke(Command(resume={"departure_date": "2027-02-10", "return_date": "2027-02-14"}), config)
    print("Initial workflow:", result["status"])
    for event in result["trace"]:
        print(" -", event)
    revised = graph.invoke({"request_patch": {"interests": ["history"]}}, config)
    print("Interests-only change invalidates:", ", ".join(revised["invalidated"]))
    for event in revised["trace"]:
        print(" -", event)
    print("No API calls made. This is workflow verification, not a generated travel plan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
