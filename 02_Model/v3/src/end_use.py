from typing import TYPE_CHECKING

from .ledger import MaterialEvent, Movement, StockRef

if TYPE_CHECKING:
    from .model import Model


class EndUse:
    """Accumulates delivered cathode product."""

    supply_chain_stage = "end_use"
    model: "Model"  # set when the end-use asset is added to a Model

    def __init__(self, asset_id="end_use", region="WORLD", material_form="cathode_cell"):
        self.asset_id = asset_id
        self.region = region
        self.material_form = material_form
        self.stocks = {("in_use", material_form): {"Li": 0.0, "other_material": 0.0}}

    @property
    def in_use_t(self):
        return sum(self.stocks[("in_use", self.material_form)].values())

    def delivery(self, source, requested_t):
        """Move finished product from the source asset into use. Returns tonnes delivered."""
        stock = source.stocks[("inventory", self.material_form)]
        available = sum(stock.values())
        delivered = min(requested_t, available)
        if delivered <= 0:
            return 0.0

        self.model.ledger.post_event(MaterialEvent(
            event_id=f"delivery:{source.asset_id}:{self.model.period}", period=self.model.period,
            event_kind="transfer", stage="end_use", asset_id=self.asset_id,
            movements=(Movement(StockRef(source.asset_id, "inventory", self.material_form),
                                StockRef(self.asset_id, "in_use", self.material_form),
                                {component: mass * delivered / available for component, mass in stock.items()}),)))
        return delivered
