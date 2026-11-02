"""Calculate subtotals without converting missing prices into free offers."""
from decimal import Decimal

from backend.schemas import Component, CostSummary, Money, PriceQuote


def summarize_costs(quotes: dict[Component, PriceQuote | None], currency: str,
                    budget: Money | None = None) -> CostSummary:
    # Initial product plans a return journey and hotel stay. A missing dictionary
    # entry is missing evidence, not permission to omit that part of the budget.
    required: tuple[Component, ...] = ("outbound_transport", "return_transport", "hotel_stay")
    missing: list[Component] = []
    comparable = []
    for component in required:
        quote = quotes.get(component)
        expected_basis = "whole_stay" if component == "hotel_stay" else "whole_leg"
        if quote and quote.currency == currency and quote.amount is not None and quote.basis == expected_basis:
            comparable.append(quote.amount)
        if (quote is None or quote.currency != currency or not quote.complete
                or quote.basis != expected_basis):
            missing.append(component)
    known = sum(comparable, Decimal("0")) if comparable else None
    complete = known if not missing else None
    status = "unknown"
    if complete is not None:
        status = "not_specified" if budget is None else "within_budget" if complete <= budget else "over_budget"
    return CostSummary(currency=currency, known_subtotal=known, complete_subtotal=complete,
                       missing_or_unverified=missing, budget_status=status)
