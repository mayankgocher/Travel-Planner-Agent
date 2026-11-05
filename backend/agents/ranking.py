"""Shared structured response and ID checks, not an agent framework abstraction."""
from pydantic import BaseModel, ConfigDict
from backend.llm import ModelCallError


class OfferRanking(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ranked_ids: list[str]
    reason: str


def ranking_candidate(offer):
    """Keep decision fields; URLs/long provenance notes stay in the actual offer."""
    data = offer.model_dump(mode="json", exclude={"source", "recommendation_reason"})
    data["price"].pop("notes", None)
    data["synthetic"] = offer.source.synthetic
    return data


def apply_ranking(ranking: OfferRanking, offers: list) -> list:
    known = {offer.id: offer for offer in offers}
    if len(known) != len(offers):
        raise ValueError("Provider returned duplicate offer IDs")
    if len(ranking.ranked_ids) != len(set(ranking.ranked_ids)) or set(ranking.ranked_ids) != set(known):
        raise ModelCallError("Ranking must include every eligible offer exactly once; no unknown IDs accepted.")
    return [type(known[id]).model_validate(known[id].model_dump() | {"recommendation_reason": ranking.reason})
            for id in ranking.ranked_ids]
