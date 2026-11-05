"""Shared structured response and ID checks, not an agent framework abstraction."""
from pydantic import BaseModel, ConfigDict
from backend.llm import ModelCallError
from backend.schemas import HotelOffer


class OfferRanking(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ranked_ids: list[str]
    reason: str


def ranking_candidate(offer, alias=None):
    """Keep decision fields; URLs/long provenance notes stay in the actual offer."""
    data = offer.model_dump(mode="json", exclude={"source", "recommendation_reason"}, exclude_none=True)
    data["price"].pop("notes", None)
    data["price"].pop("demo_rule_version", None)
    if isinstance(offer, HotelOffer):
        # City, stay dates and adults already passed hard filters and appear
        # once in preferences, rather than once per hotel.
        for field in ("city", "check_in", "check_out", "adults"):
            data.pop(field, None)
    if alias is not None:
        data["id"] = alias
    data["synthetic"] = offer.source.synthetic
    return data


def apply_ranking(ranking: OfferRanking, offers: list, *, aliases=None) -> list:
    known = {offer.id: offer for offer in offers}
    if len(known) != len(offers):
        raise ValueError("Provider returned duplicate offer IDs")
    if aliases is not None:
        if set(ranking.ranked_ids) != set(aliases) or len(ranking.ranked_ids) != len(aliases):
            raise ModelCallError("Ranking must include every local candidate ID exactly once.")
        ranking = ranking.model_copy(update={"ranked_ids": [aliases[id] for id in ranking.ranked_ids]})
    if len(ranking.ranked_ids) != len(set(ranking.ranked_ids)) or set(ranking.ranked_ids) != set(known):
        raise ModelCallError("Ranking must include every eligible offer exactly once; no unknown IDs accepted.")
    reason = ranking.reason
    if any(not offer.price.complete for offer in offers):
        # A schema-valid LLM reason can still claim unsupported affordability.
        # Incomplete-price rankings expose only this safe scope statement.
        reason = incomplete_price_reason(offers)
    return [type(known[id]).model_validate(known[id].model_dump() | {"recommendation_reason": reason})
            for id in ranking.ranked_ids]


def incomplete_price_reason(offers):
    if any(offer.price.pricing_mode == "demo" for offer in offers):
        return ("Ranked eligible options using the stated preferences and timings. ASSUMED DEMO FARES "
                "are illustrative; actual fares, seats and whole-trip affordability remain unverified.")
    return ("Ranked eligible options using the stated preferences and supplied quote fields. "
            "Passenger/room or tax coverage is unverified; whole-trip affordability remains unknown.")
