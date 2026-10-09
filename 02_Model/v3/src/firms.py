from . import units
from .ledger import TOL
from .markets import RefineryRequest, SupplyOffer


class FirmAgent:
    """Owns assets and makes the decisions for them."""

    def __init__(self, firm_id, region, assets_owned):
        self.firm_id = firm_id
        self.home_region = region
        self.assets_owned = tuple(assets_owned)

    def mines(self):
        return [asset for asset in self.assets_owned if asset.supply_chain_stage == "mining"]

    def plan_mine_offers(self, scenario):
        """Offer held product plus what each mine could make at full capacity this period."""
        return [SupplyOffer(seller_id=self.firm_id, source_asset_id=mine.asset_id, material_form=mine.output_form,
                            quantity=mine.held_product_t + mine.max_product_t,
                            min_price=mine.unit_cost * (1.0 + scenario.mine_markup_fraction),
                            li_grade=mine.target_output_grade)  # both routes grade on Li
                for mine in self.mines() if mine.held_product_t + mine.max_product_t > TOL]

    def plan_refinery_purchases(self, refinery, required_output_t, scenario):
        """Ask for the refined output still needed after finished stock, within capacity and reagents."""
        target = min(max(0.0, required_output_t - refinery.finished_t), refinery.available_output_t)
        return RefineryRequest(
            buyer_id=self.firm_id, receiving_asset_id=refinery.asset_id, requested_output_t=target,
            max_cost_per_t_output=scenario.refined_price_per_t / (1.0 + scenario.refinery_required_markup_fraction),
            routes=scenario.routes)

    def plan_manufacturing(self, manufacturer, final_demand_t):
        """Return (input needed for this period's output, extra input to buy)."""
        target = max(0.0, final_demand_t - manufacturer.finished_t)
        if manufacturer.capacity is not None:
            target = min(target, manufacturer.capacity)
        required_input = target / manufacturer.efficiency_rate
        return required_input, max(0.0, required_input - manufacturer.held_input_t)

    def plan_investment(self, refined_price, scenario, year):
        """Commit pipeline projects whose mine-gate price covers full cost plus a hurdle, each with a set chance per year."""
        committed = []
        for mine in self.mines():
            if mine.status != "pre-construction":
                continue
            draw = mine.rng.random()
            route = scenario.routes[mine.output_form]
            output_per_t_product = mine.target_output_grade * route.lithium_recovery_fraction * units.LCE_PER_LI
            mine_gate_price = output_per_t_product * (refined_price - route.processing_cost_per_t_output)
            economic = mine_gate_price >= mine.full_unit_cost(scenario.capex_payback_years) * (1.0 + scenario.investment_hurdle)
            if economic and draw < scenario.commitment_probability:
                mine.commit(year)
                committed.append(mine.asset_id)
        return committed
