from dataclasses import dataclass
from typing import TYPE_CHECKING
import random

from .ledger import MaterialEvent, Movement, StockRef

if TYPE_CHECKING:
    from .model import Model


@dataclass(frozen=True)
class MineRoute:
    """One route from raw material to a product at a fixed grade of one component."""
    input_form: str
    output_form: str
    grade_component: str
    target_output_grade: float
    residue_form: str


MINE_ROUTES = {
    "hard_rock": MineRoute("ore", "spodumene_concentrate", "Li", 0.0279, "tailings"),
    "brine": MineRoute("raw_brine", "concentrated_brine", "Li", 0.06, "brine_residue"),
}

VALID_STATUSES = {"pre-construction", "construction", "operation", "closed"}


class Mine:
    """A mining asset. Extraction and concentration happen in one step."""

    supply_chain_stage = "mining"
    model: "Model"  # set when the mine is added to a Model
    rng: random.Random # investment draws; set when the mine is added to a Model

    def __init__(self, asset_id, region, deposit_type, project_status, geological_stock_t_material,
                 capacity_t_material_annual, composition_mass_fractions, mining_recovery_fraction,
                 opex_usd_per_t_material, capex_usd=0.0, lead_time_years=0, opening_year=None, coordinates=None):
        route = MINE_ROUTES[deposit_type]
        self.grade_component = route.grade_component
        self.target_output_grade = route.target_output_grade

        # Named components plus "other_material" for the remainder.
        composition = {name: float(f) for name, f in composition_mass_fractions.items() if name != "other_material"}
        composition["other_material"] = 1.0 - sum(composition.values())

        if project_status not in VALID_STATUSES:
            raise ValueError(f"Unsupported mine status: {project_status}")
        if any(not 0 <= f <= 1 for f in composition.values()):
            raise ValueError("Composition fractions must lie between zero and one and sum to one.")
        if not 0 < composition.get(self.grade_component, 0.0) < self.target_output_grade:
            raise ValueError("Feed grade must be positive and below the product grade.")
        if not 0 <= mining_recovery_fraction <= 1:
            raise ValueError("Mining recovery must lie between zero and one.")

        self.asset_id = asset_id
        self.region = region
        self.coordinates = coordinates
        self.deposit_type = deposit_type
        self.status = project_status
        self.opening_year = opening_year
        self.committed_year = None  # year a pipeline project committed to construction

        self.composition = composition
        self.capacity = float(capacity_t_material_annual)
        self.recovery = float(mining_recovery_fraction)
        self.opex = float(opex_usd_per_t_material)
        self.capex = float(capex_usd)
        self.lead_time_years = int(lead_time_years)
        self.input_form = route.input_form
        self.output_form = route.output_form
        self.residue_form = route.residue_form

        stock = float(geological_stock_t_material)
        empty = {name: 0.0 for name in composition}
        self.stocks = {
            ("geological_stock", self.input_form): {name: stock * f for name, f in composition.items()},
            ("inventory", self.output_form): dict(empty),
            ("residue", self.residue_form): dict(empty),
        }

    @property
    def reserves(self):
        return sum(self.stocks[("geological_stock", self.input_form)].values())

    @property
    def held_product_t(self):
        return sum(self.stocks[("inventory", self.output_form)].values())

    @property
    def product_yield(self):
        """Tonnes of product per tonne of raw material."""
        return self.composition[self.grade_component] * self.recovery / self.target_output_grade

    @property
    def unit_cost(self):
        """Operating cost per tonne of product."""
        return self.opex / self.product_yield

    @property
    def max_product_t(self):
        """Product the mine could make this step at full capacity."""
        if self.status != "operation":
            return 0.0
        return min(self.capacity * self.model.step_years, self.reserves) * self.product_yield

    def full_unit_cost(self, payback_years):
        """Operating cost plus capex recovered over a fixed payback period, per tonne of product."""
        return self.unit_cost + self.capex / (payback_years * self.capacity * self.product_yield)

    def commit(self, time):
        """Start building at 'time' (years): the mine opens once its lead time has passed."""
        self.status = "construction"
        self.committed_year = time
        self.opening_year = time + self.lead_time_years

    def produce(self, ordered_t):
        """Make enough product to fill an order, using held stock first."""
        needed = max(0.0, ordered_t - self.held_product_t)
        return self.extract(needed / self.product_yield)

    def extract(self, requested_t_material):
        """Extract raw material and concentrate it to the target grade. Returns tonnes extracted."""
        if self.status != "operation":
            return 0.0
        extracted = min(requested_t_material, self.capacity * self.model.step_years, self.reserves)
        if extracted <= 0:
            return 0.0

        grade = self.grade_component
        geology = self.stocks[("geological_stock", self.input_form)]
        feed = {name: mass * extracted / self.reserves for name, mass in geology.items()}

        # Keep the recovered grade component, plus just enough other material to reach the target grade.
        recovered = feed[grade] * self.recovery
        other_kept = recovered / self.target_output_grade - recovered
        other_share = other_kept / (extracted - feed[grade])
        product = {name: recovered if name == grade else mass * other_share for name, mass in feed.items()}
        # One residue stream: rejected material plus the unrecovered grade component.
        residue = {name: mass - product[name] for name, mass in feed.items()}

        source = StockRef(self.asset_id, "geological_stock", self.input_form)
        self.model.ledger.post_event(MaterialEvent(
            event_id=f"mining:{self.asset_id}:{self.model.period}", period=self.model.period,
            event_kind="extraction", stage="mining", asset_id=self.asset_id,
            operating_cost=extracted * self.opex,
            movements=(
                Movement(source, StockRef(self.asset_id, "inventory", self.output_form), product),
                Movement(source, StockRef(self.asset_id, "residue", self.residue_form), residue),
            )))
        return extracted
