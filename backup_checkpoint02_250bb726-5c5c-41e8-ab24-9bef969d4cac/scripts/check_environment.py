"""Offline dependency and graph smoke check; does not read credentials."""
import importlib
from importlib.metadata import version
import sys
from typing import TypedDict


def main() -> int:
    print("Python:", sys.version.split()[0])
    if sys.version_info[:2] != (3, 12):
        print("Use Python 3.12.7 for this project.")
        return 2
    if sys.version_info[:3] != (3, 12, 7):
        print("Note: target is exactly 3.12.7; this interpreter differs in patch version.")
    packages = {
        "langchain": "langchain", "langgraph": "langgraph.graph",
        "langchain-groq": "langchain_groq", "langgraph-checkpoint-sqlite": "langgraph.checkpoint.sqlite",
        "fastapi": "fastapi", "uvicorn": "uvicorn", "streamlit": "streamlit",
        "httpx": "httpx", "pydantic-settings": "pydantic_settings",
        "python-dotenv": "dotenv", "pytest": "pytest",
    }
    for distribution, module in packages.items():
        importlib.import_module(module)
        print(f"{distribution}=={version(distribution)}")

    from langgraph.graph import END, START, StateGraph

    class State(TypedDict):
        count: int

    def increment(state: State) -> dict:
        return {"count": state["count"] + 1}

    graph = StateGraph(State)
    graph.add_node("increment", increment)
    graph.add_node("finish", lambda state: {})
    graph.add_edge(START, "increment")
    graph.add_conditional_edges("increment", lambda state: "finish" if state["count"] == 1 else END)
    graph.add_edge("finish", END)
    result = graph.compile().invoke({"count": 0})
    if result["count"] != 1:
        raise RuntimeError("Graph smoke check failed")
    print("PASS: imports and conditional graph execution. No provider requests made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
