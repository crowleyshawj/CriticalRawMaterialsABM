import random

import pandas as pd

from .ledger import MaterialLedger
from .markets import clear_refinery_input_market, settle
from .params import BASE_YEAR, Scenario


class Model:
    """
    Runs the supply chain one step at a time; the step length is defined by Scenario.steps_per_year (one year by default).
    Capacities and demand are annual rates, scaled to the step. Stocks carry over between steps.

    ASSUMPTIONS:
        - production is instantaneous within a period
        - mines produce only what the refinery has agreed to buy
        - the refinery refines everything it buys within the period
        - refined product sells to the manufacturer at a fixed scenario price
        - lock-in risk: any shortfall is assumed to lead to equivalent purchase of a fossil fuel asset,
          e.g. gas generator and ICE vehicle.
    """

    def __init__(self, mines, refinery=None, manufacturer=None, end_use=None, demand=None, firms=(), *,
                 seed=None, scenario=None, start_year=BASE_YEAR):
        self.mines = mines
        self.refinery = refinery
        self.manufacturer = manufacturer
        self.end_use = end_use
        self.demand = demand or {}  # {calendar year: annual final-product demand} - exogenous, from IAM
        self.firms = firms
        self.scenario = scenario or Scenario()
        
        self.start_year = start_year
        self.steps_per_year = self.scenario.steps_per_year
        
        if not isinstance(self.steps_per_year, int) or self.steps_per_year < 1:
            raise ValueError(f"steps_per_year must be a positive whole number, e.g. 1, 2, 4, 12, or 52. Instead received: {self.steps_per_year}.")
        
        self.step_years = 1 / self.steps_per_year
        self.period = 0 # index of the current step
        self.period_rows = []
        self.price = None  # last realised price, USD per t refined output (LCE)
        self.transactions = []

        assets = [*mines, *(asset for asset in (refinery, manufacturer, end_use) if asset is not None)]
        self.assets_by_id = {asset.asset_id: asset for asset in assets}
        self.owner = {asset.asset_id: firm for firm in firms for asset in firm.assets_owned}
        for asset in assets:
            asset.model = self
        # One random stream per project, so draws do not depend on ownership or the order firms act in.
        for mine in mines:
            mine.rng = random.Random(None if seed is None else f"{seed}:{mine.asset_id}")
        self.mine_order = {mine.asset_id: i for i, mine in enumerate(mines)}
        self.ledger = MaterialLedger(assets)

    @property
    def time(self):
        """Start of the current step, in years (2024.25 is the start of the second quarter of 2024.)"""
        return self.start_year + self.period / self.steps_per_year
    
    @property
    def year(self):
        """Calendar year of the current step."""
        return self.start_year + self.period // self.steps_per_year

    @property
    def step_in_year(self):
        """Position of the current step within its year, from 1 to steps_per_year."""
        return self.period % self.steps_per_year + 1

    def run(self, periods=None):
        """Run to the end of the demand horizon, or for a given number of steps."""
        if periods is None:
            periods = (max(self.demand) + 1 - self.start_year) * self.steps_per_year - self.period
        for _ in range(periods):
            self.step()
        return pd.DataFrame(self.period_rows)

    def step(self):
        """Run one step from mining through final delivery."""
        refinery, manufacturer, end_use = self.refinery, self.manufacturer, self.end_use
        assert refinery and manufacturer and end_use, "step() needs a refinery, a manufacturer and an end use."
        time = self.time
        scenario = self.scenario

        opened = [mine.asset_id for mine in self.mines
                  if mine.status == "construction" and mine.opening_year is not None and mine.opening_year <= time]
        for mine_id in opened:
            self.assets_by_id[mine_id].status = "operation"

        # 1. Work backwards from final demand to the inputs each stage must buy.
        demand = demand_in_step(self.demand, self.year, self.step_in_year, self.steps_per_year)
        required_input, input_to_buy = self.owner[manufacturer.asset_id].plan_manufacturing(manufacturer, demand)
        request = self.owner[refinery.asset_id].plan_refinery_purchases(refinery, input_to_buy, scenario)

        # 2. Agree quantities and prices on capacity-based offers, then mines produce what was ordered.
        offers = [offer for firm in self.firms for offer in firm.plan_mine_offers(scenario)]
        offers.sort(key=lambda offer: self.mine_order[offer.source_asset_id])  # cost ties fill in dataset order
        allocations, price = clear_refinery_input_market(offers, request, scenario.scarcity_premium)
        self.price = price if price is not None else self.price
        for allocation in allocations:
            self.assets_by_id[allocation["source_asset_id"]].produce(allocation["quantity_t_input"])
        settle(self, allocations, event_id=f"refinery_purchases:{self.period}")

        # 3. Refine everything bought.
        refined_t = sum(refinery.refine(form, route) for form, route in request.routes.items())

        # 4. Sell refined product to the manufacturer at the fixed scenario price.
        sold_t = min(refinery.finished_t, input_to_buy)
        if sold_t > 0:
            settle(self, [{"seller_id": self.owner[refinery.asset_id].firm_id, "source_asset_id": refinery.asset_id,
                           "buyer_id": self.owner[manufacturer.asset_id].firm_id,
                           "receiving_asset_id": manufacturer.asset_id, "material_form": refinery.output_form,
                           "quantity_t_input": sold_t, "price_per_t_input": scenario.refined_price_per_t}],
                   event_id=f"refined_sale:{self.period}")

        # 5. Manufacture, then deliver finished product.
        manufactured_t = manufacturer.process(required_input)
        delivered_t = end_use.delivery(manufacturer, demand)

        # 6. Firms decide whether to start building pipeline projects at this step's price.
        committed = [] if self.price is None else [
            mine_id for firm in self.firms for mine_id in firm.plan_investment(self.price, scenario, time)]

        self.ledger.check_conservation()
        row = {"period": self.period, "time": time, "year" : self.year, "step_in_year": self.step_in_year, "opened_mine_ids": opened, "demand_t": demand,
               "refined_output_t": refined_t, "manufacturing_input_purchased_t": sold_t,
               "cathode_output_t": manufactured_t, "delivered_t": delivered_t,
               "unmet_demand_t": max(0.0, demand - delivered_t), "in_use_t": end_use.in_use_t,
               "price_usd_per_t_lce": self.price, "committed_mine_ids": committed,
               "mines_operating": sum(mine.status == "operation" for mine in self.mines)}
        self.period_rows.append(row)
        self.period += 1
        return row


def mine_sales_by_country(model):
    """Refined output equivalent tonnes and revenue sold by mines, per year and agent country."""
    trades = pd.DataFrame([t for t in model.transactions if t["event_id"].startswith("refinery_purchases:")])
    trades["country"] = trades["source_asset_id"].map(lambda asset_id: model.owner[asset_id].home_region)
    trades["year"] = model.start_year + trades["period"] // model.steps_per_year
    return trades.pivot_table(index="year", columns="country", values=["output_t", "transaction_value"], aggfunc="sum", fill_value=0.0)

def demand_in_step(annual_demand, year, step_in_year, steps_per_year):
    """Demand in one step from annual quantities keyed by the calendar year.
    Witihin each year demand rises a long a straight line centred on that year's quantity, with the slope taken from the
    neighbouring years, so the steps of a year add up exactly to its annual quantity. With one-year steps this is the annual quantity itself."""

    value = annual_demand.get(year, 0.0)
    previous = annual_demand.get(year - 1)
    following = annual_demand.get(year + 1)
    
    if previous is None and following is None:
        slope = 0.0
    elif previous is None:
        slope = following - value
    elif following is None:
        slope = value - previous
    else:
        slope = (following - previous) / 2

    slope = max(-2 * value, min(2*value, slope)) # keeps the rate non-negative within the year
    middle_of_step = (step_in_year - 0.5) / steps_per_year
    return (value + slope * (middle_of_step - 0.5)) / steps_per_year