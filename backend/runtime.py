"""Compose the same four agents with real provider tools; caller owns lifetimes."""
from backend.agents.hotel import HotelAgent
from backend.agents.itinerary import ItineraryAgent
from backend.agents.supervisor import Supervisor
from backend.agents.transportation import TransportationAgent
from backend.graph.builder import build_workflow
from langsmith import tracing_context


def build_provider_workflow(model, checkpointer, providers):
    transport, hotels, places = providers.tools()
    def invoke(tool):
        def search(p):
            with tracing_context(enabled=False):
                return tool.invoke(p.model_dump(mode="json"))
        return search
    zone = providers.bindings.destination_timezone
    return build_workflow(TransportationAgent(model, invoke(transport)), HotelAgent(model, invoke(hotels)),
        ItineraryAgent(model, invoke(places), zone), checkpointer, Supervisor(model, providers.settings.app_timezone),
        destination_timezone=zone, require_search_preferences=True)
