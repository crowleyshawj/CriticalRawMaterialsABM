from typing import TYPE_CHECKING

from . import units
from .ledger import MaterialEvent, Movement, StockRef

if TYPE_CHECKING:
    from .model import Model

INPUT_FORMS = ("spodumene_concentrate", "concentrated_brine")

# Reagent mass that joins each tonne of refined product, so that product mass is LCE mass.
REAGENT_PER_T_OUTPUT = 1.0 - 1.0 / units.LCE_PER_LI


class Refinery:
    """One worldwide refinery. The model currently asks it to refine everything it buys."""

    supply_chain_stage = "refining"
    model: "Model"  # set when the refinery is added to a Model

    def __init__(self, asset_id, region, capacity, output_form="battery_grade_li"):
        self.asset_id = asset_id
        self.region = region
        self.capacity = capacity  # t refined output per year; None means unlimited
        self.output_form = output_form

        accounts = [("inventory", form) for form in (*INPUT_FORMS, output_form)]
        accounts += [("processing_inputs", "refining_reagents")]
        accounts += [("residue", f"{form}_refining_residue") for form in INPUT_FORMS]
        self.stocks = {account: {"Li": 0.0, "other_material": 0.0} for account in accounts}

    @property
    def finished_t(self):
        return sum(self.stocks[("inventory", self.output_form)].values())

    @property
    def available_output_t(self):
        """Output possible this step, limited by capacity and reagents."""
        reagents = self.stocks[("processing_inputs", "refining_reagents")]["other_material"]
        capacity = float("inf") if self.capacity is None else self.capacity * self.model.step_years
        return min(capacity, reagents / REAGENT_PER_T_OUTPUT)

    def refine(self, input_form, route, quantity_t=None):
        """Refine held feed of one form: all of it by default. Returns tonnes of product."""
        stock = self.stocks[("inventory", input_form)]
        held = sum(stock.values())
        quantity = held if quantity_t is None else min(quantity_t, held)
        if quantity <= 0:
            return 0.0
        feed = {name: mass * quantity / held for name, mass in stock.items()}

        li = feed["Li"] * route.lithium_recovery_fraction
        reagent = li * (units.LCE_PER_LI - 1)
        residue = {**feed, "Li": feed["Li"] - li}

        feed_ref = StockRef(self.asset_id, "inventory", input_form)
        product_ref = StockRef(self.asset_id, "inventory", self.output_form)
        self.model.ledger.post_event(MaterialEvent(
            event_id=f"refining:{self.asset_id}:{input_form}:{self.model.period}", period=self.model.period,
            event_kind="processing", stage="refining", asset_id=self.asset_id,
            operating_cost=(li + reagent) * route.processing_cost_per_t_output,
            movements=(Movement(feed_ref, product_ref, {"Li": li}),
                       Movement(feed_ref, StockRef(self.asset_id, "residue", f"{input_form}_refining_residue"), residue),
                       Movement(StockRef(self.asset_id, "processing_inputs", "refining_reagents"), product_ref,
                                {"other_material": reagent}))))
        return li + reagent
