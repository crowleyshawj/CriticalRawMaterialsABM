from dataclasses import dataclass

BASE_YEAR = 2024

INITIALISATION_SEED = 1
SIMULATION_SEED = 1

HISTORICAL_UTILISATION = 0.8  # USGS reports production; capacity = production / utilisation

# Countries with their own mining agent (dataset country name -> code); all other mines belong to RoW.
MINING_AGENT_COUNTRIES = {"Australia": "AUS", "Argentina": "ARG", "Chile":"CHL", "China": "CHN", "Canada": "CAN", "USA": "USA"}
REST_OF_WORLD = "ROW"

@dataclass(frozen=True)
class RefiningRoute:
    lithium_recovery_fraction: float
    processing_cost_per_t_output: float


@dataclass(frozen=True)
class Scenario:
    steps_per_year: int = 1                # 1 = annual (default), 2 = half-yearly, 4 = quarterly, 12 = monthly, 52 = weekly
    mine_markup_fraction: float = 0.0
    refinery_required_markup_fraction: float = 0.0
    refined_price_per_t: float = 25_000.0  # refiners' maximum: caps the price
    scarcity_premium: float = 1.0          # price = 90th-percentile cost x (1 + premium x unmet share)
    investment_hurdle: float = 0.2         # commit if price >= full cost x (1 + hurdle)
    commitment_probability: float = 0.5    # chance an economic project commits in a given year
    capex_payback_years: float = 20.0      # capex recovered over this many years of output, undiscounted
    hard_rock_route: RefiningRoute = RefiningRoute(lithium_recovery_fraction=0.90, processing_cost_per_t_output=3_000.0)
    brine_route: RefiningRoute = RefiningRoute(lithium_recovery_fraction=0.85, processing_cost_per_t_output=3_500.0)

    @property
    def routes(self):
        """Refining route for each mine product."""
        return {"spodumene_concentrate": self.hard_rock_route, "concentrated_brine": self.brine_route}
