"""Loopback FastAPI entry point for one explicit planning submission."""
import logging
from collections import OrderedDict
from datetime import date, datetime
from threading import Lock
from typing import Annotated, Literal
from uuid import UUID, uuid4
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field, model_validator

from backend.agents.supervisor import Supervisor
from backend.chat import TripChat
from backend.config import Settings
from backend.llm import create_model
from backend.locations import find_city, route_error
from backend.plan_view import plan_view
from backend.providers.airport_lookup import search_airports
from backend.providers.http import SerpApiHttp
from backend.providers.rail_http import RailRadarHttp
from backend.providers.railradar import RailRadarAdapter
from backend.providers.session import TravelProviderSession, trip_bindings
from backend.runtime import build_provider_workflow
from backend.schemas import DomainModel, Money, TripPreferences


class PlanRequest(DomainModel):
    # Defaults preserve callers of the original Delhi–Jaipur form endpoint.
    origin: Annotated[str, Field(min_length=1, max_length=80)] = "Delhi"
    destination: Annotated[str, Field(min_length=1, max_length=80)] = "Jaipur"
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
        if error := route_error(self.origin, self.destination, self.transport_mode):
            raise ValueError(error)
        if self.departure_date <= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise ValueError("Choose a future departure date.")
        if not 1 <= (self.return_date - self.departure_date).days <= 7:
            raise ValueError("Choose a return date one to seven nights after departure.")
        if self.nightly_min is not None and self.nightly_max is not None and self.nightly_min > self.nightly_max:
            raise ValueError("The minimum nightly price cannot exceed the maximum.")
        return self

    def preferences(self) -> TripPreferences:
        fields = self.model_dump() | {"origin": find_city(self.origin).name,
                                      "destination": find_city(self.destination).name}
        return TripPreferences(currency="INR", interests=["history"], pace="relaxed", **fields)


app = FastAPI(title="Travel Planning Agent", version="0.16.0")
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


def planner_settings() -> Settings:
    try:
        # The browser demo explicitly uses assumed rail prices.
        settings = Settings(train_fare_mode="mock")
    except ValueError:
        raise HTTPException(503, "Check the server's local .env configuration.") from None
    if settings.groq_model != "openai/gpt-oss-120b":
        raise HTTPException(503, "Set GROQ_MODEL to openai/gpt-oss-120b for this checkpoint.")
    return settings


def require_keys(settings, *providers):
    try:
        for provider in providers:
            settings.require_provider_key(provider)
    except ValueError as error:
        raise HTTPException(503, str(error)) from None  # Fixed config message, no value.


def redact_result(data, settings):
    secrets = set()
    for name in ("groq_api_key", "serpapi_api_key", "railradar_api_key"):
        key = getattr(settings, name).get_secret_value().strip()
        if key:
            secrets.update((key, quote(key, safe="")))
    return redact(data, sorted(secrets, key=len, reverse=True))


def run_workflow(settings, model, preferences, seed=None):
    needed = ["serpapi"]
    if preferences.transport_mode in ("train", "compare"):
        needed.append("railradar")
    require_keys(settings, *needed)
    with TravelProviderSession(settings, trip_bindings(preferences), expand_rail_shortlist=True) as service:
        graph = build_provider_workflow(model, InMemorySaver(), service)
        config = {"configurable": {"thread_id": "plan"}, "recursion_limit": 30}
        return graph.invoke((seed or {}) | {"request_patch": preferences.model_dump(mode="json")}, config)


@app.post("/plan")
def generate_plan(request: PlanRequest):
    """Structured form kept as a secondary way to use the same workflow."""
    preferences = request.preferences()
    settings = planner_settings()
    require_keys(settings, "groq")
    try:
        with httpx.Client(timeout=45) as http:
            result = run_workflow(settings, create_model(settings, http_client=http), preferences)
        return redact_result(plan_view(result, preferences), settings)
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Local planning failed (%s)", type(error).__name__)
        raise HTTPException(500, "Planning stopped before a result could be displayed.") from None


class ChatRequest(DomainModel):
    message: Annotated[str, Field(min_length=1, max_length=2000)]
    session_id: UUID | None = None


# Local single-user demo: serialize turns and keep only the latest state of up to
# 16 chats. This is not durable storage or a cross-session search cache.
chats: OrderedDict[UUID, TripChat] = OrderedDict()
chat_lock = Lock()


@app.post("/chat")
def chat(request: ChatRequest):
    with chat_lock:
        session_id = request.session_id or uuid4()
        session = chats.get(session_id)
        if request.session_id and session is None:
            raise HTTPException(404, "This chat expired. Start a new chat.")
        session = session or TripChat()
        settings = planner_settings()
        try:
            with httpx.Client(timeout=45) as http:
                model = None

                def get_model():
                    nonlocal model
                    if model is None:
                        require_keys(settings, "groq")
                        model = create_model(settings, http_client=http)
                    return model

                def supervisor(message, before, **kwargs):
                    return Supervisor(get_model(), settings.app_timezone)(message, before, **kwargs)

                def run(preferences, seed):
                    return run_workflow(settings, get_model(), preferences, seed)

                station_lookup = airport_http = None

                def find_stations(query):
                    nonlocal station_lookup
                    if station_lookup is None:
                        require_keys(settings, "railradar")
                        rail = RailRadarHttp(settings.require_provider_key("railradar"), max_requests=2, http_client=http)
                        station_lookup = RailRadarAdapter(rail)
                    return station_lookup.stations(query).items

                def find_airports(query):
                    nonlocal airport_http
                    if airport_http is None:
                        require_keys(settings, "serpapi")
                        airport_http = SerpApiHttp(settings.require_provider_key("serpapi"), max_requests=2, http_client=http)
                    return search_airports(airport_http, query)

                result = session.respond(request.message, supervisor, run, find_stations, find_airports)
        except HTTPException:
            raise
        except Exception as error:
            logger.error("Local chat planning failed (%s)", type(error).__name__)
            raise HTTPException(500, "The chat turn stopped before a result could be displayed.") from None
        chats[session_id] = session
        chats.move_to_end(session_id)
        if len(chats) > 16:
            chats.popitem(last=False)
        return redact_result(result, settings) | {"session_id": str(session_id)}
