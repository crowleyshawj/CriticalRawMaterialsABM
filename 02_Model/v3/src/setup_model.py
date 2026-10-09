import pandas as pd

from . import params
from .end_use import EndUse
from .firms import FirmAgent
from .manufacturer import Manufacturer
from .mines import Mine
from .model import Model
from .refinery import REAGENT_PER_T_OUTPUT, Refinery


def mine_from_row(row):
    """Create a fresh mine from one prepared dataset row."""
    coordinates = (row["lat"], row["lon"]) if pd.notna(row["lat"]) and pd.notna(row["lon"]) else None
    return Mine(
        asset_id=row["asset_id"],
        region=row["country"],
        deposit_type=row["deposit_type"],
        project_status=row["stage_at_base_year"],
        geological_stock_t_material=row["reserves_base_year"] / row["contained_li_fraction"],
        capacity_t_material_annual=row["capacity_material"],
        composition_mass_fractions={"Li": row["contained_li_fraction"]},
        mining_recovery_fraction=row["recovery_efficiency"],
        opex_usd_per_t_material=row["opex_total"],
        capex_usd=row["capex_total"],
        lead_time_years=row["lead_time_years"],
        opening_year=int(row["opening_year"]) if pd.notna(row["opening_year"]) else None,
        coordinates=coordinates,
    )


def create_mine_assets(prepared_mines):
    """Create independent mine objects for a new simulation."""
    return [mine_from_row(row) for _, row in prepared_mines.iterrows()]


def agent_country(mine):
    """Code of the country agent a mine belongs to."""
    return params.MINING_AGENT_COUNTRIES.get(mine.region, params.REST_OF_WORLD)

def mining_firms(mines, mining_agents):
    """One firm per mine ("mine") or one firm per agent country owning the mines located there ("country"). 
    
    Later, will add actual firm ownership across borders ("actual")."""
    if mining_agents == "mine":
        return [FirmAgent(f"mine_owner:{mine.asset_id}", agent_country(mine), [mine]) for mine in mines]
    if mining_agents == "country":
        codes = [*params.MINING_AGENT_COUNTRIES.values(), params.REST_OF_WORLD]
        return [FirmAgent(f"miner:{code}", code, [mine for mine in mines if agent_country(mine) == code]) for code in codes]
    raise ValueError(f"Unknown mining agent setup: {mining_agents}")

def build_model(prepared_mines, *, demand, refinery_capacity, scenario=None,
                simulation_seed=params.SIMULATION_SEED, start_year=params.BASE_YEAR, mining_agents="mine"):
    """Assemble a fresh model from a prepared mine dataset."""
    mines = create_mine_assets(prepared_mines)
    refinery = Refinery("refinery", "WORLD", refinery_capacity)
    manufacturer = Manufacturer("manufacturer", "WORLD", efficiency_rate=0.95)

    # Opening reagents cover the whole demand horizon.
    refined_needed_t = sum(demand.values()) / manufacturer.efficiency_rate
    refinery.stocks[("processing_inputs", "refining_reagents")]["other_material"] = refined_needed_t * REAGENT_PER_T_OUTPUT

    firms = mining_firms(mines, mining_agents)
    firms += [FirmAgent("refinery_owner", "WORLD", [refinery]), FirmAgent("manufacturer_owner", "WORLD", [manufacturer])]

    return Model(mines, refinery, manufacturer, EndUse(), demand, firms,
                 seed=simulation_seed, scenario=scenario, start_year=start_year)
