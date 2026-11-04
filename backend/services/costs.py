"""Calculate subtotals without converting missing prices into free offers."""
from decimal import Decimal

from backend.schemas import Component, CostSummary, Money, PriceQuote


def summarize_costs(quotes: dict[Component, PriceQuote | None], currency: str,
                    budget: Money | None = None) -> CostSummary:
    # Initial product plans a return journey and hotel stay. A missing dictionary
    # entry is missing evidence, not permission to omit that part of the budget.
    required: tuple[Component, ...] = ("outbound_transport", "return_transport", "hotel_stay")
    missing: list[Component] = []
    comparable, assumed, illustrative = [], [], []
    illustration_complete = True
    for component in required:
        quote = quotes.get(component)
        expected_basis = "whole_stay" if component == "hotel_stay" else "whole_leg"
        if quote and quote.pricing_mode == "demo":
            assumed.append(component)
        in_scope = quote is not None and quote.currency == currency and quote.amount is not None and quote.basis == expected_basis
        if in_scope and ((quote.pricing_mode == "demo" and quote.covers_all_travelers) or quote.complete):
            illustrative.append(quote.amount)
        else:
            illustration_complete = False
        if quote and quote.currency == currency and quote.amount is not None and quote.basis == expected_basis:
            if quote.pricing_mode != "demo":
                comparable.append(quote.amount)
        if (quote is None or quote.currency != currency or not quote.complete
                or quote.basis != expected_basis):
            missing.append(component)
    known = sum(comparable, Decimal("0")) if comparable else None
    complete = known if not missing else None
    status = "unknown"
    if complete is not None:
        status = "not_specified" if budget is None else "within_budget" if complete <= budget else "over_budget"
    demo_total = sum(illustrative, Decimal("0")) if assumed and illustration_complete else None
    demo_status = "unknown"
    if demo_total is not None:
        demo_status = "not_specified" if budget is None else "within_assumed_budget" if demo_total <= budget else "over_assumed_budget"
    return CostSummary(currency=currency, known_subtotal=known, complete_subtotal=complete,
        missing_or_unverified=missing, budget_status=status, assumed_components=assumed,
        illustrative_subtotal=demo_total, illustrative_budget_status=demo_status,
        pricing_notice="Illustrative calculation includes assumed demo fares; real budget fit is unverified." if assumed else None)
