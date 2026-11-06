"""Loopback FastAPI entry point for one explicit planning submission."""
import logging
from datetime import date, datetime
from typing import Annotated, Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field, model_validator

from backend.config import Settings
from backend.llm import create_model
from backend.plan_view import plan_view
from backend.providers.session import TravelProviderSession, jaipur_probe_bindings
from backend.runtime import build_provider_workflow
from backend.schemas import DomainModel, Money, TripPreferences


class PlanRequest(DomainModel):
    departure_date: date
    return_date: date
    adults: Annotated[int, Field(strict=True, ge=1, le=6)] = 2
    transport_mode: Literal["train", "flight", "compare"] = "train"
    train_class: Literal["CC", "EC", "3A", "2A", "1A", "SL"] = "CC"
    flight_class: Literal["Economy", "Premium Economy", "Business", "First"] = "Economy"
    hotel_class: Annotated[int, Field(strict=True, ge=1, le=5)] | None = 3
    guest_rating_min: Annotated[float, Field(ge=0, le=5)] | None = None
    nightly_min: Money | None = None
    nightly_max: Money | None = None
    budget_total: Money | None = None

    @model_validator(mode="after")
    def check_trip(self):
        if self.departure_date <= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise ValueError("Choose a future departure date.")
        if not 1 <= (self.return_date - self.departure_date).days <= 7:
            raise ValueError("Choose a return date one to seven nights after departure.")
        if self.nightly_min is not None and self.nightly_max is not None and self.nightly_min > self.nightly_max:
            raise ValueError("The minimum nightly price cannot exceed the maximum.")
        return self

    def preferences(self) -> TripPreferences:
        return TripPreferences(origin="Delhi", destination="Jaipur", currency="INR",
                               interests=["history"], pace="relaxed", **self.model_dump())


app = FastAPI(title="Travel Planning Agent", version="0.12.0")
logger = logging.getLogger(__name__)


@app.get("/health")
def health():
    return {"status": "ok"}


def redact(value, secrets: list[str]):
    """Keep known credentials out of all returned display fields."""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
    elif isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()}
    elif isinstance(value, list):
        return [redact(v, secrets) for v in value]
    return value


@app.post("/plan")
def generate_plan(request: PlanRequest):
    """Each submission gets an isolated graph, with no provider calls at startup."""
    preferences = request.preferences()
    providers_needed = ["groq", "serpapi"]
    if preferences.transport_mode in ("train", "compare"):
        providers_needed.append("railradar")
    try:
        # The browser demo explicitly uses assumed rail prices.
        settings = Settings(train_fare_mode="mock")
    except ValueError:
        raise HTTPException(503, "Check the server's local .env configuration.") from None
    try:
        keys = [settings.require_provider_key(provider) for provider in providers_needed]
    except ValueError as error:
        raise HTTPException(503, str(error)) from None  # Fixed config message, no value.
    if settings.groq_model != "openai/gpt-oss-120b":
        raise HTTPException(503, "Set GROQ_MODEL to openai/gpt-oss-120b for this checkpoint.")

    try:
        with httpx.Client(timeout=45) as http, TravelProviderSession(settings, jaipur_probe_bindings()) as service:
            graph = build_provider_workflow(create_model(settings, http_client=http), InMemorySaver(), service)
            config = {"configurable": {"thread_id": "plan"}, "recursion_limit": 30}
            # Structured form fields are already validated; no Supervisor parsing call.
            state = graph.invoke({"request_patch": preferences.model_dump(mode="json")}, config)
        return redact(plan_view(state, preferences), sorted({v for k in keys for v in (k, quote(k, safe=""))},
                                                          key=len, reverse=True))
    except Exception as error:
        logger.error("Local planning failed (%s)", type(error).__name__)
        raise HTTPException(500, "Planning stopped before a result could be displayed.") from None
