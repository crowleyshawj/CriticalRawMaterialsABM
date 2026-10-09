from dataclasses import dataclass

from . import units
from .ledger import TOL, MaterialEvent, Movement, StockRef


@dataclass(frozen=True)
class SupplyOffer:
    seller_id: str
    source_asset_id: str | int
    material_form: str
    quantity: float     # t product
    min_price: float    # USD per t product
    li_grade: float     # t Li per t product


@dataclass(frozen=True)
class RefineryRequest:
    buyer_id: str
    receiving_asset_id: str | int
    requested_output_t: float     # t refined output wanted from purchases
    max_cost_per_t_output: float  # purchase plus processing cost the buyer will accept
    routes: dict                  # material form -> RefiningRoute


def clear_refinery_input_market(offers, request, scarcity_premium):
    """Buy the cheapest refined-output-equivalent feed first. Returns (allocations, price); changes no stocks.

    Price rule, per tonne of refined output, paid to every accepted seller:
        price = min(buyer maximum, 90th-percentile accepted cost x (1 + scarcity_premium x unmet share))
    """
    options = []
    for offer in offers:
        route = request.routes[offer.material_form]
        output_per_input = offer.li_grade * route.lithium_recovery_fraction * units.LCE_PER_LI
        cost = offer.min_price / output_per_input + route.processing_cost_per_t_output
        if cost <= request.max_cost_per_t_output:
            options.append((cost, offer, output_per_input, route))
    options.sort(key=lambda option: option[0])

    remaining = request.requested_output_t
    accepted = []
    for cost, offer, output_per_input, route in options:
        if remaining <= TOL:
            break
        output_t = min(remaining, offer.quantity * output_per_input)
        accepted.append((cost, offer, output_per_input, route, output_t))
        remaining -= output_t

    if not accepted:
        return [], (request.max_cost_per_t_output if request.requested_output_t > TOL else None)

    # Anchor: cost of the supplier at the 90th percentile of accepted volume.
    total_t, cumulative_t = sum(option[-1] for option in accepted), 0.0
    for cost, *_, output_t in accepted:
        cumulative_t += output_t
        if cumulative_t >= 0.9 * total_t:
            break
    unmet_share = max(0.0, remaining) / request.requested_output_t
    clearing_value = min(request.max_cost_per_t_output, cost * (1.0 + scarcity_premium * unmet_share))

    return [{"seller_id": offer.seller_id, "source_asset_id": offer.source_asset_id,
             "buyer_id": request.buyer_id, "receiving_asset_id": request.receiving_asset_id,
             "material_form": offer.material_form, "quantity_t_input": output_t / output_per_input,
             "output_t": output_t,
             "price_per_t_input": output_per_input * (clearing_value - route.processing_cost_per_t_output)}
            for _, offer, output_per_input, route, output_t in accepted], clearing_value


def settle(model, allocations, event_id):
    """Move every allocation from seller to buyer in one ledger event and record the trades."""
    movements, transactions = [], []
    for allocation in allocations:
        form = allocation["material_form"]
        source = model.assets_by_id[allocation["source_asset_id"]]
        stock = source.stocks[("inventory", form)]
        share = min(1.0, allocation["quantity_t_input"] / sum(stock.values()))
        movements.append(Movement(StockRef(source.asset_id, "inventory", form),
                                  StockRef(allocation["receiving_asset_id"], "inventory", form),
                                  {component: mass * share for component, mass in stock.items()}))
        transactions.append({**allocation, "period": model.period, "event_id": event_id,
                             "transaction_value": allocation["quantity_t_input"] * allocation["price_per_t_input"]})

    if movements:
        receiver = model.assets_by_id[allocations[0]["receiving_asset_id"]]
        model.ledger.post_event(MaterialEvent(event_id=event_id, period=model.period, event_kind="transfer",
                                              stage=receiver.supply_chain_stage, asset_id=receiver.asset_id,
                                              movements=tuple(movements)))
    model.transactions.extend(transactions)
    return transactions
