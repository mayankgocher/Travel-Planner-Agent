"""Validated domain data. These models do not perform searches or bookings."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator

Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Name = Annotated[str, Field(min_length=1)]
Component = Literal["outbound_transport", "return_transport", "hotel_stay"]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True,
                              allow_inf_nan=False, validate_assignment=True)


class TripPreferences(DomainModel):
    # Missing mandatory fields stay unknown until the Supervisor asks the user.
    origin: Name | None = None
    destination: Name | None = None
    departure_date: date | None = None
    return_date: date | None = None
    adults: Annotated[int, Field(strict=True, ge=1)] | None = None
    transport_mode: Literal["train", "flight", "compare"] | None = None
    train_class: Name | None = None
    flight_class: Name | None = None
    flight_sort_by: Annotated[int, Field(strict=True, ge=0)] | None = None
    flight_max_price: Money | None = None
    hotel_class: Annotated[int, Field(strict=True, ge=1, le=5)] | None = None
    hotel_class_rule: Literal["exact", "at_least"] = "exact"
    nightly_min: Money | None = None
    nightly_max: Money | None = None
    guest_rating_min: Annotated[float, Field(ge=0, le=5)] | None = None
    budget_total: Money | None = None
    currency: Currency | None = None
    interests: list[Name] = Field(default_factory=list)
    pace: Literal["relaxed", "balanced", "busy"] | None = None

    @model_validator(mode="after")
    def coherent_constraints(self):
        if self.departure_date and self.return_date and self.return_date <= self.departure_date:
            raise ValueError("Return date must be after departure date")
        if self.nightly_min is not None and self.nightly_max is not None and self.nightly_min > self.nightly_max:
            raise ValueError("Minimum hotel price exceeds maximum hotel price")
        if self.origin and self.destination and self.origin.casefold() == self.destination.casefold():
            raise ValueError("Origin and destination must differ")
        return self

    def missing_required(self) -> list[str]:
        return [name for name in ("origin", "destination", "departure_date", "return_date", "adults")
                if getattr(self, name) is None]


class Source(DomainModel):
    provider: Name
    fetched_at: AwareDatetime
    source_id: Name | None = None
    url: HttpUrl | None = None
    synthetic: bool = False


class PriceQuote(DomainModel):
    """Adapters must normalize to a total for the entire stated scope first."""
    amount: Money | None = None
    currency: Currency
    basis: Literal["whole_stay", "whole_leg", "unverified"] = "unverified"
    covers_all_travelers: bool = False
    taxes_included: bool | None = None

    @property
    def complete(self) -> bool:
        # Taxes/occupancy must be known before claiming a complete payable total.
        return (self.amount is not None and self.basis != "unverified"
                and self.covers_all_travelers and self.taxes_included is True)


class HotelOffer(DomainModel):
    id: Name
    name: Name
    city: Name
    check_in: date
    check_out: date
    adults: Annotated[int, Field(strict=True, ge=1)]
    hotel_class: Annotated[int, Field(strict=True, ge=1, le=5)] | None = None
    guest_rating: Annotated[float, Field(ge=0, le=5)] | None = None
    room_type: str | None = None
    nightly_price: Money | None = None
    price: PriceQuote
    source: Source
    recommendation_reason: str | None = None

    @model_validator(mode="after")
    def valid_stay(self):
        if self.check_out <= self.check_in:
            raise ValueError("Check-out must follow check-in")
        if self.price.basis not in ("whole_stay", "unverified"):
            raise ValueError("Hotel price must describe a whole stay")
        return self


class TransportOffer(DomainModel):
    id: Name
    mode: Literal["train", "flight"]
    origin: Name
    destination: Name
    departure: AwareDatetime
    arrival: AwareDatetime
    adults: Annotated[int, Field(strict=True, ge=1)]
    travel_class: Name | None = None
    price: PriceQuote
    seat_availability: Literal["unverified"] = "unverified"
    source: Source
    recommendation_reason: str | None = None

    @model_validator(mode="after")
    def valid_journey(self):
        if self.arrival <= self.departure:
            raise ValueError("Arrival must follow departure")
        if self.price.basis not in ("whole_leg", "unverified"):
            raise ValueError("Transport price must describe a whole leg")
        return self


class Selection(DomainModel):
    component: Component
    offer_id: Name
    locked: bool = False


class CostSummary(DomainModel):
    currency: Currency
    known_subtotal: Money | None
    complete_subtotal: Money | None
    missing_or_unverified: list[Component]
    budget_status: Literal["unknown", "within_budget", "over_budget", "not_specified"]
    excluded_costs: list[str] = Field(default_factory=lambda: ["attractions", "food", "local_transport"])


class PlaceCandidate(DomainModel):
    id: Name
    name: Name
    # Monday=0. Missing weekday means unknown; an empty list means closed.
    weekly_hours: dict[int, list[tuple[str, str]]] = Field(default_factory=dict)
    source: Source
