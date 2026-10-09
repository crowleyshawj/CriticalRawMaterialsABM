from typing import TYPE_CHECKING

from .ledger import MaterialEvent, Movement, StockRef

if TYPE_CHECKING:
    from .model import Model


class Manufacturer:
    """Turns battery-grade lithium into a cathode-product proxy with a fixed mass loss."""

    supply_chain_stage = "manufacturing"
    model: "Model"  # set when the manufacturer is added to a Model

    def __init__(self, asset_id, region, capacity=None, efficiency_rate=0.95, unit_cost=0.0):
        if not 0 < efficiency_rate <= 1:
            raise ValueError("Manufacturing efficiency must be in (0, 1].")
        self.asset_id = asset_id
        self.region = region
        self.capacity = capacity  # t output per year; None means unlimited
        self.efficiency_rate = efficiency_rate
        self.unit_cost = unit_cost
        self.input_form = "battery_grade_li"
        self.output_form = "cathode_cell"
        self.stocks = {account: {"Li": 0.0, "other_material": 0.0} for account in (
            ("inventory", self.input_form), ("inventory", self.output_form), ("residue", "manufacturing_residue"))}

    @property
    def held_input_t(self):
        return sum(self.stocks[("inventory", self.input_form)].values())

    @property
    def finished_t(self):
        return sum(self.stocks[("inventory", self.output_form)].values())

    def process(self, requested_t_input):
        """Process up to the requested input. Returns tonnes of product."""
        limit = float("inf") if self.capacity is None else self.capacity * self.model.step_years / self.efficiency_rate
        processed = min(requested_t_input, self.held_input_t, limit)
        if processed <= 0:
            return 0.0

        stock = self.stocks[("inventory", self.input_form)]
        share = processed / self.held_input_t
        product = {component: mass * share * self.efficiency_rate for component, mass in stock.items()}
        residue = {component: mass * share - product[component] for component, mass in stock.items()}

        source = StockRef(self.asset_id, "inventory", self.input_form)
        self.model.ledger.post_event(MaterialEvent(
            event_id=f"manufacturing:{self.asset_id}:{self.model.period}", period=self.model.period,
            event_kind="processing", stage="manufacturing", asset_id=self.asset_id,
            operating_cost=sum(product.values()) * self.unit_cost,
            movements=(Movement(source, StockRef(self.asset_id, "inventory", self.output_form), product),
                       Movement(source, StockRef(self.asset_id, "residue", "manufacturing_residue"), residue))))
        return sum(product.values())
