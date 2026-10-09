"""
Create reproducible baseline dataset of lithium mining projects

The dataset combines source observations with explicitly assumed or synthetic attributes. 

Mining includes extraction and on-site concentration. Chemical conversion at a refinery is outside the mining boundary.

Importing this module does not read data, generate projects, or write files.


TO-DO:
    - convert the capacity and reserves from LCE to raw tonnes as wel
    - validate against BCS/USGS production / reserves / resources data
    - further costs needed: sustaining costs, closure costs, discounting
"""

from pathlib import Path

import numpy as np
import pandas as pd

from . import units, params
from .usgs_benchmarks import load_usgs_benchmarks

# Paths are relative to this file, independent of the working directory.
V3_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = V3_DIRECTORY / "data"
DEFAULT_SOURCE_PATH = (
    DATA_DIRECTORY / "master_database_projects_UPDATED.csv"
)

# ASSUMPTIONS - for now this is hardcoded, but will eventually come from the config file or a database.

PRE_CONSTRUCTION = {"minimum": 3, "maximum": 10, "mode": 5}
CONSTRUCTION = {"minimum": 1, "maximum": 5, "mode":3}
LIFESPAN = {"minimum":10, "maximum": 50, "mode": 20}

# Grades

DEPOSIT_TYPES = ["brine", "hard_rock"]

GRADE = {
    "hard_rock" : {"minimum" : 0.6, "maximum" : 2, "mode": 1.2, "units" : "% Li2O"},
    "brine": {"minimum" : 200, "maximum" : 2000, "mode": 600, "units" : "mg/L Li"}
}

GRADE_DRIFT = {"operation": 1.15, "construction": 1.0, "pre-construction": 0.9}

# Pipeline projects are costlier to operate than built mines.
OPEX_DRIFT = {"operation": 1.0, "construction": 1.0, "pre-construction": 1.15}

# Imputed stocks for pre-construction projects: lognormal fitted to reported pre-construction stocks,
# with a fixed spread and a cap at a multiple of the largest reported project.
PIPELINE_RESERVES_SIGMA = 1.5
PIPELINE_RESERVES_CAP_MULTIPLE = 3.0

# Taylor's rule: mine life (years) = coefficient x (ore or brine tonnes) ** 0.25.
# Coefficients fitted to USGS-calibrated operating mines (Taylor's original value is 0.2).
TAYLOR_COEFFICIENT = {"hard_rock": 0.54, "brine": 1.55}

MINING_RECOVERY = {
    "hard_rock": 0.65,
    "brine" : 0.55
}

RESERVES_SIGMA_FACTOR = 0.8
PRODUCTION_WEIGHT_SIGMA = 1.0

# OPEX assumptions
OPEX_PER_T_MATERIAL = {"hard_rock": 125.0, "brine": 5.0}  # 2024 USD/t original material

OPEX_SPREAD = 0.15 # sigma of the lognormal space for the cost. Choose a lower value here so that there is in minimal variation in the spread.

OPEX_EXTRACTION_SHARE = 0.7

# CAPEX ASSUMPTIONS
CAPEX_PER_T_CAPACITY = {"hard_rock": 200.0, "brine": 20.0}  # 2024 USD/(t original material/year)

CAPEX_SPREAD = 0.20 # sigma of the lognormal space for the cost. Choose a lower value here so that there is in minimal variation in the spread.

CAPEX_EXTRACTION_SHARE = 0.7

### FOR DUPLICATES

PROJECT_OVERRIDES = {
    # Nemaska: use the later supplied production start.
    37507: {"Development Stage": "Construction Planned", "production_start": 2028},
    # Mariana: provisionally retain construction status.
    37586: {"Development Stage": "Construction Started"},
    # Sal de Vida: use the later supplied production start.
    37611: {"production_start": 2026},
    # Sal de Vida Extension: both source labels map to operation.
    59728: {"Development Stage": "Production - Operating"},
    # Bougouni: provisionally retain commissioning status.
    78022: {"Development Stage": "Preproduction - Commissioning",},
    # Smackover: retain the more specific supplied description.
    83068: {"project_type": "Brine/DLE",},
}

# import raw data

def load_raw_mines(source_path = DEFAULT_SOURCE_PATH):
    return pd.read_csv(source_path)

### MAIN FUNCTION

def create_mines_dataset(raw_data, *,  seed, base_year = params.BASE_YEAR, historical_utilisation = params.HISTORICAL_UTILISATION, drop_incomplete_data=False):
    rng = np.random.default_rng(seed)
    
    df = clean_source(raw_data.copy(deep=True), base_year=base_year)
    df = consolidate_projects(df, PROJECT_OVERRIDES)

    df["reserves_source"] = df["reserves"]
    df["unit_source"] = df["unit"]
    df["source_stock_basis"] = "t Li2O-equivalent, reserves and resources incl. inferred (D-GLB-31)"
    df["reserves"] = df["reserves_source"] * units.LI_PER_LI2O
    df["unit"] = "t Li"


    reported_year = df["reserves_as_of_year"]
    df["reserves_as_of_year"] = reported_year.where(
        reported_year.le(base_year), base_year
    ).astype("Int64")


    # validate dates and classify initial status
    df = group_project_stages(df)

    # optionally filter incomplete projects
    
    if drop_incomplete_data:
        df = drop_incomplete_rows(df)

    # fill missing stocks and durations
    df = fill_missing_data(df, rng, base_year=base_year)
    df = redraw_pipeline_reserves(df, np.random.default_rng(np.random.SeedSequence([seed, 2])))

    # assign deposit types
    df = fill_project_type(df, rng)

    # generate grades
    df = generate_grades(df, rng)

    # assign mining recovery
    df = draw_recovery_efficiency(df)

    # calculate contained content and recovered yield
    ## this is maybe not needed in this file - this more so for construction of visualisations and charts - maybe in an exploratory file?
    df = contained_li(df)

    # infer extraction capacity and normalise stocks
    df = determine_capacity(df)
    df = normalise_to_base_year(df, base_year, historical_utilisation=0.0)
    production_rng = np.random.default_rng(np.random.SeedSequence([seed, 1]))
    df = calibrate_operating_capacity(df, load_usgs_benchmarks(), production_rng, base_year=base_year, historical_utilisation=historical_utilisation)
    
    # recalculate opening stocks using calibrated extraction capacities
    df = normalise_to_base_year(df, base_year, historical_utilisation)
    
    calibrated = df["production_target_t_li"].notna()
    available_output = df["reserves_base_year"] * df["recovery_efficiency"]
    insufficient = calibrated & (df["stage_at_base_year"].ne("operation") | available_output.lt(df["production_target_t_li"] - 1e-8))

    if insufficient.any():
        raise ValueError(f"Allocated production exceeds eligible opening stocks: {df.loc[insufficient, 'asset_id'].tolist()}")

    # derive output capacities and unit costs
    df = draw_opex(df,rng)
    df = draw_capex(df, rng)
    df = derive_costs(df)
    df = assign_opening_years(df, np.random.default_rng(np.random.SeedSequence([seed, 3])), base_year)



    # validate and return

    return df



def clean_source(df, base_year=params.BASE_YEAR):
    df.columns = df.columns.str.strip()

    primary_commodity = (df["Primary Commodity"].astype("string").str.strip())

    df = df.loc[primary_commodity.eq("Lithium")].copy()

    df = df[["Property Name", "Country/ Region",  "Development Stage", "Primary Reserves and Resources", 
         "Unit", "Project Type", "Coordinates", "Construction Start", "Production Start", "Closure", 
         "Reserves & Resources As Of Date" , "Property ID"]]

    df = df.rename(columns={
    "Property Name": "name", "Country/ Region": "country", 
    "Primary Reserves and Resources": "reserves", "Unit": "unit","Project Type": "project_type", "Coordinates": "coordinates", "Production Start": "production_start", 
    "Construction Start": "construction_start", "Closure": "closure", "Reserves & Resources As Of Date" : "reserves_as_of", "Property ID":"asset_id"})

    coords = df["coordinates"].astype("string").str.split(",", n=1, expand=True).reindex(columns=[0,1])
    df["lat"] = pd.to_numeric(coords[0], errors="coerce")
    df["lon"] = pd.to_numeric(coords[1], errors="coerce")

    valid_coordinates = (df["lat"].between(-90,90) & df["lon"].between(-180,180))
    df["coordinates_unusable"] = ~valid_coordinates
    df.loc[~valid_coordinates, ["lat", "lon"]] = np.nan

    df = df.drop(columns=["coordinates"])

    df["reserves"] = pd.to_numeric(df["reserves"], errors="coerce")

    date_text = df["reserves_as_of"].astype("string").str.strip().replace({"": pd.NA, "na":pd.NA})
    reported_year = pd.to_datetime(date_text, format="mixed", dayfirst=False, errors="coerce").dt.year
    
    df["reserves_as_of_year"] = reported_year.astype("Int64")
    
    df["construction_start"] = pd.to_numeric(df["construction_start"], errors="coerce")
    df["production_start"] = pd.to_numeric(df["production_start"], errors="coerce")
    df["closure"] = pd.to_numeric(df["closure"], errors="coerce")

    return df


def consolidate_projects(df, overrides):
    "Return one project row per asset, rejecting unresolved conflicts"
    df = df.copy()

    text_columns = df.select_dtypes(include=["object", "string"]).columns

    for column in text_columns:
        df[column] = (df[column].astype("string").str.strip().replace({"":pd.NA, "na": pd.NA}))

    if df["asset_id"].isna().any():
        raise ValueError("Every project must have an asset_id.")

    for asset_id, fields in overrides.items():
        for column, value in fields.items():
            df.loc[df["asset_id"].eq(asset_id), column] = value

    grouped = df.groupby("asset_id", sort=True)

    conflicts = grouped.nunique(dropna=True).gt(1)
    conflicts = conflicts.loc[conflicts.any(axis=1)]

    if not conflicts.empty:
        raise ValueError("Resolve conflicting project fields:\n" + conflicts.to_string())

    projects = grouped.first().reset_index()

    stock_columns = ["reserves", "unit", "reserves_as_of", "reserves_as_of_year"]

    for _, project in projects.iterrows():
        source_rows = df.loc[df["asset_id"].eq(project["asset_id"])]
        matches = pd.Series(True, index=source_rows.index)

        for column in stock_columns:
            value = project[column]

            if pd.isna(value):
                matches &= source_rows[column].isna()
            else:
                matches &= source_rows[column].eq(value).fillna(False)

        if not matches.any():
            raise ValueError(f"Inconsistent stock record: {project['asset_id']}")


    return projects

def group_project_stages(df):
    stage = df["Development Stage"].str.strip()

    pre_construction = {
        "Target Outline", "Exploration", "Advanced Exploration", "Grassroots",
        "Reserves Development", "Reserves Development - Prefeas/Scoping",
        "Prefeas/Scoping", "Feasibility", "Feasibility Started", "Feasibility Complete", "Construction Planned", "Preproduction - Construction Planned"
    }
    construction = {
        "Construction Started", "Under Construction",
        "Commissioning", "Preproduction",  "Preproduction - Construction Started",
        "Preproduction - Commissioning", "Preproduction - Expansion",  # judgment call: treated as still building out
    }
    operation = {
        "Operating", "Production - Operating", "Expansion", "Limited Production",
        "Satellite",  # judgment call: satellite deposit of an active mine
        "Preproduction - Operating",  # judgment call: contradictory label in source data, treated as operating
    }

    known_stages = pre_construction | construction | operation
    unknown_stage = ~stage.isin(known_stages)

    if unknown_stage.any():
        unknown_labels = stage.loc[unknown_stage].unique().tolist()
        raise ValueError(f"unrecognised development stages: {unknown_labels}")

    stage_group = pd.Series("pre-construction", index=df.index)
    stage_group[stage.isin(construction)] = "construction"
    stage_group[stage.isin(operation)] = "operation"
    df["stage_group"] = stage_group

    return df

def drop_incomplete_rows(df):
    drop_mask = (df["stage_group"] == "pre-construction") & df["reserves"].isna()
    df = df[~drop_mask]
    return df


#constr_dur = (df["production_start"] - df["construction_start"]).dropna()
#lifespan = (df["closure"] - df["production_start"]).dropna()

def fill_missing_data(df, rng, base_year=params.BASE_YEAR):
    # no real data exists for pre-construction duration, so every row is synthetic
    # UPGRADE: draw the pre-construction years based on the specific stages
    df["pre_construction_years"] = sample_triangular(PRE_CONSTRUCTION, len(df), rng)

    # construction years: uses the real duration where both dates exist, else draw from assumptions
    real_construction = df["production_start"] - df["construction_start"]
    synth_construction = pd.Series(sample_triangular(CONSTRUCTION, len(df), rng),index=df.index)
    df["construction_years"] = real_construction.where(real_construction > 0, synth_construction)

    #lifespan: determines how long a project goes for - unsure if this needed though, if we just have reserves and capacity then that should be sufficient?
    real_lifespan = df["closure"] - df["production_start"]
    synth_lifespan = pd.Series(sample_triangular(LIFESPAN, len(df), rng), index=df.index)
    df["lifespan_years"] = real_lifespan.where(real_lifespan > 0, synth_lifespan)

    # imputation flags

    df["construction_years_imputed"] = ~real_construction.gt(0)
    df["lifespan_years_imputed"] = ~real_lifespan.gt(0)
    df["reserves_imputed"] = df["reserves"].isna()
    df["pre_construction_years_imputed"] = True


    # Reject invalid reported stocks before fitting or imputation.
    reported_stocks = df["reserves"].dropna()
    invalid_stocks = (
        ~np.isfinite(reported_stocks)
        | reported_stocks.le(0)
    )

    if invalid_stocks.any():
        invalid_rows = reported_stocks.index[invalid_stocks]
        asset_ids = df.loc[invalid_rows, "asset_id"].tolist()
        raise ValueError(f"Reported stocks must be finite and positive: {asset_ids}")

    df["reserves_filled"] = df["reserves"].copy()

    # Fit a distribution only when missing stocks require draws.
    if df["reserves_imputed"].any():
        reserves_mu, reserves_sigma = fit_lognormal(df["reserves"])
        df["reserves_filled"] = fill_with_draws(df["reserves"], reserves_mu, reserves_sigma * RESERVES_SIGMA_FACTOR, rng)

    df.loc[df["reserves_imputed"], "reserves_as_of_year"] = base_year

    return df


def redraw_pipeline_reserves(df, rng):
    """Draw missing pre-construction stocks from the reported pre-construction stocks, with a capped fat tail."""
    pipeline = df["stage_group"].eq("pre-construction")
    reported = df.loc[pipeline & ~df["reserves_imputed"], "reserves"]
    missing = pipeline & df["reserves_imputed"]
    draws = rng.lognormal(np.log(reported).mean(), PIPELINE_RESERVES_SIGMA, size=int(missing.sum()))
    df.loc[missing, "reserves_filled"] = np.minimum(draws, PIPELINE_RESERVES_CAP_MULTIPLE * reported.max())
    return df


def assign_opening_years(df, rng, base_year):
    """Construction mines without a start date are a random 0-50% through construction at the base year."""
    progress = rng.uniform(0.0, 0.5, size=len(df))
    undated = df["stage_at_base_year"].eq("construction") & df["production_start"].isna()
    remaining = np.ceil(df["construction_years"] * (1.0 - progress))
    df["opening_year"] = df["production_start"].where(~undated, base_year + remaining)
    df["lead_time_years"] = np.ceil(df["pre_construction_years"] + df["construction_years"])
    return df

def allocate_production(weights, limits, target):
    """Allocate production capacity by weight, redistrubuting output above stock limits."""
    allocation = pd.Series(0.0, index=weights.index)

    if limits.sum() < target - 1e-8:
        raise ValueError("Country stocks cannot suppor the production target.")

    remaining = float(target)
    active = limits.gt(0)

    while remaining > 1e-8 and active.any():
        shares = remaining * weights.loc[active] / weights.loc[active].sum()
        room = limits.loc[active] - allocation.loc[active]
        additions = shares.clip(upper=room)

        allocation.loc[active] += additions
        remaining = max(0.0, float(target) - float(allocation.sum()))
        active.loc[active] = shares.lt(room)

    return allocation

def calibrate_operating_capacity(df, benchmarks, rng, *, base_year, historical_utilisation):
    """Allocate national production as effective recovered-Li capacity."""
    df = df.copy()
    production_column = f"production_{base_year}_t_li"

    # The rest-of-world aggregate reads as zero in the source workbook. Treat it as unknown,
    # so its operating mines keep their stock-lifetime capacity instead of being calibrated to zero.
    targets = benchmarks.loc[~benchmarks["is_aggregate"]].set_index("country")[production_column]

    named_countries = benchmarks.loc[~benchmarks["is_aggregate"], "country"]
    countries = df["country"].replace({"USA" : "United States"})
    df["production_calibration_group"] = countries.where(countries.isin(named_countries), "ROW")

    operating = df["stage_at_base_year"].eq("operation")
    df["capacity_recovered_li_uncalibrated"] = df["capacity_recovered_li"]
    df["capacity_basis"] = "stock_lifetime_provisional"
    df["production_target_t_li"] = np.nan
    df["production_weight"] = np.nan

    df.loc[operating, "production_weight"] = rng.lognormal(mean=0.0, sigma=PRODUCTION_WEIGHT_SIGMA, size=int(operating.sum()))

    # Allow for historical depletion and one baseline year's output. Historical depletion is
    # years x production, because capacity = production / utilisation and output = utilisation x capacity.
    limits = (df["reserves_filled"] * df["recovery_efficiency"] / (1.0 + df["historical_production_years"])).astype(float)

    for country, target in targets.items():
        if pd.isna(target):
            continue

        selected = operating & df["production_calibration_group"].eq(country)

        if not selected.any():
            if target > 0:
                raise ValueError(f"No eligible operating mines for {country}")

            continue

        allocated = allocate_production(df.loc[selected, "production_weight"], limits.loc[selected], float(target))

        df.loc[selected, "production_target_t_li"] = allocated
        df.loc[selected, "capacity_recovered_li"] = allocated / historical_utilisation
        df.loc[selected, "capacity_basis"] = "usgs_effective_capacity"

    df["capacity_contained_li"] = df["capacity_recovered_li"] / df["recovery_efficiency"]
    df["capacity_material"] = df["capacity_contained_li"] / df["contained_li_fraction"]


    return df


def determine_capacity(df):
    """
    Infer annual extraction and intermediate-output capacities.
    """
    # Taylor's rule: larger deposits are mined faster, but over a longer life.
    ore_t = df["reserves_filled"] / df["contained_li_fraction"]
    df["capacity_years"] = df["deposit_type"].map(TAYLOR_COEFFICIENT) * ore_t ** 0.25

    df["capacity_contained_li"] = df["reserves_filled"] / df["capacity_years"]
    df["capacity_material"] = df["capacity_contained_li"] / df["contained_li_fraction"]
    df["capacity_recovered_li"] = df["capacity_contained_li"] * df["recovery_efficiency"]


    return df


### FILLING PROJECT TYPES

def fill_project_type(df, rng):

    df["deposit_type_known"] = df["project_type"].map(bucket_project_type)

    known = df.dropna(subset=["deposit_type_known"])

    if not df.empty and known.empty:
        raise ValueError ("Cannot imput deposit types: no recognised deposit types are available.")

    country_mix = (known.groupby("country")["deposit_type_known"].value_counts(normalize=True).unstack(fill_value=0.0).reindex(columns=DEPOSIT_TYPES, fill_value=0.0))
    global_mix = known["deposit_type_known"].value_counts(normalize=True).reindex(DEPOSIT_TYPES, fill_value=0.0)

    miss = df["deposit_type_known"].isna()
    df["deposit_type"] = df["deposit_type_known"]
    df.loc[miss, "deposit_type"] = [impute_type(c, rng, country_mix, global_mix) for c in df.loc[miss, "country"]]
    df["deposit_type_imputed"] = miss
    return df

def bucket_project_type(t):
    if pd.isna(t):
        return None
    t = t.strip().lower()
    if any(k in t for k in ("brine", "dle", "geothermal", "in-situ leach")):
        return "brine"
    if any(k in t for k in ("open pit", "underground", "placer", "tailings", "stock pile")):
        return "hard_rock"
    return None

def impute_type(country, rng, country_mix, global_mix):
    p = country_mix.loc[country] if country in country_mix.index else global_mix
    if p.sum() == 0:
        p = global_mix
    return rng.choice(DEPOSIT_TYPES, p = (p / p.sum()).values)


## GRADE DISTRIBUTION

def generate_grades(df,rng):
    """
    Next we draw the grade distributions. 
    
    A slight stage drift is added - it is likely that the already operational mines have higher grades (or lower costs), as these were most economic initially.
    Equally, the under-construction mines are likely to have higher grades than pre-construction.
    This is a large simplification and assumption - there are other factors (e.g. cost, regulatory environment) that impact these decisions. These should be factored in later.
    """

    df["grade_base"] = np.nan
    for dt in DEPOSIT_TYPES:
        m = df["deposit_type"] == dt
        df.loc[m,"grade_base"] = sample_triangular(GRADE[dt], int(m.sum()), rng)

    df["grade"] = df["grade_base"] * df["stage_group"].map(GRADE_DRIFT)
    df["grade_unit"] = df["deposit_type"].map({"hard_rock":"pct_Li2O", "brine":"mgLi_per_L"})

    df["grade_imputed"] = True
    
    return df

### COST DISTRIBUTION

# Opex

def draw_opex(df, rng):
    """Operating cost per tonne of raw material, extraction and concentration together."""
    df["opex_multiplier"] = rng.lognormal(mean=0.0, sigma=OPEX_SPREAD, size=len(df))
    df["opex_total"] = df["deposit_type"].map(OPEX_PER_T_MATERIAL) * df["opex_multiplier"] * df["stage_group"].map(OPEX_DRIFT)
    return df

# Capex

def draw_capex(df, rng):
    """Total initial capital cost of the installed extraction capacity."""
    df["capex_multiplier"] = rng.lognormal(mean=0.0, sigma=CAPEX_SPREAD, size=len(df))
    df["capex_total"] = df["deposit_type"].map(CAPEX_PER_T_CAPACITY) * df["capacity_material"] * df["capex_multiplier"]
    return df

## ADD RECOVERY EFFICIENCY

def draw_recovery_efficiency(df):
    df["recovery_efficiency"] = df["deposit_type"].map(MINING_RECOVERY)

    return df

def contained_li(df):
    df["contained_li_fraction"] = df.apply(lambda row: li_fraction(row["grade"], row["deposit_type"]), axis=1)
    df["recovered_li_fraction"] = df["contained_li_fraction"] * df["recovery_efficiency"]

    return df

## DERIVED COLUMNS

def derive_costs(df):
    
    df["opex_per_t_li"] = df["opex_total"] / df["recovered_li_fraction"]

    prospective_output_t_li = df["reserves_base_year"] * df["recovery_efficiency"]

    candidate = (df["stage_at_base_year"].eq("pre-construction") & prospective_output_t_li.gt(0))

    df["project_cost_per_t_li"] = np.nan
    df.loc[candidate, "project_cost_per_t_li"] = (df.loc[candidate, "opex_per_t_li"].astype(float) + df.loc[candidate, "capex_total"].astype(float) / prospective_output_t_li.loc[candidate].astype(float))
    
    return df


def normalise_to_base_year(df, base_year, historical_utilisation):
    """
    Estimates stocks and project status at the baseline year.

    This will need to be revisited.

    """
    # For operating mines without a start date, assume produciton was underway at the stock reference date

    production_start = df["production_start"].fillna(df["reserves_as_of_year"].where(df["stage_group"].eq("operation")))

    depletion_start = pd.concat([df["reserves_as_of_year"], production_start], axis=1,).max(axis=1)

    # stop depletion at closure or the baseline year
    depletion_end = df["closure"].fillna(base_year).clip(upper=base_year)

    years = (depletion_end - depletion_start).clip(lower=0)
    years = years.where(production_start.notna(),0)

    df["historical_production_years"] = years
    
    depletion = years * historical_utilisation * df["capacity_contained_li"]
    df["depletion_clipped"] = depletion > df["reserves_filled"]

    df["reserves_base_year"] = (df["reserves_filled"] - depletion).clip(lower=0)


    # Start from the source classification, then apply known dates
    stage = df["stage_group"].copy()

    stage.loc[df["construction_start"].gt(base_year) | df["production_start"].gt(base_year)] = "pre-construction"

    stage.loc[df["construction_start"].le(base_year) & ~production_start.le(base_year)] = "construction"

    stage.loc[production_start.le(base_year)] = "operation"

    stage.loc[df["closure"].le(base_year) | df["reserves_base_year"].le(0)] = "closed"

    df["stage_at_base_year"] = stage
    
    return df


## UTILS

def li_fraction(grade_value, deposit_type):
    """t Li per t of raw material, before recovery."""
    if deposit_type == "hard_rock":
        return grade_value / 100 * units.LI_PER_LI2O  # grade in % Li2O
    if deposit_type == "brine":
        return grade_value * 1e-6 / units.BRINE_DENSITY  # grade in mg Li per litre
    raise ValueError(f"Unsupported deposit type: {deposit_type!r}")


def fit_lognormal(x):
    """Fit log-space parameters from positive, finite observations."""
    observations = x.dropna()

    if (~np.isfinite(observations)| observations.le(0)).any():
        raise ValueError("Lognormal fitting requires positive, finite observations.")

    if len(observations) < 2:
        raise ValueError("At least two reported stocks are required to estimate lognormal spread.")

    log_stocks = np.log(observations)
    return log_stocks.mean(), log_stocks.std()

def sample_triangular(assumptions, size, rng):
    """Draw values from the specified triangular distribution."""
    return rng.triangular(
        assumptions["minimum"],
        assumptions["mode"],
        assumptions["maximum"],
        size=size,
    )


def fill_with_draws(series, mu, sigma, rng):
    """Fill missing entries with lognormal draws, preserving observations."""
    missing = series.isna()
    draws = rng.lognormal(mu, sigma, size=missing.sum())

    return series.mask(
        missing,
        pd.Series(draws, index=series.index[missing]),
    )



# main

def main():
    """
    Build the baseline dataset when this module is run directly
    """

    raw_data = load_raw_mines()

    mines = create_mines_dataset(raw_data, seed=params.INITIALISATION_SEED, base_year=params.BASE_YEAR, historical_utilisation=params.HISTORICAL_UTILISATION,drop_incomplete_data=False)

    export_path = DATA_DIRECTORY / (f"synthetic_mines_draft_seed{params.INITIALISATION_SEED}.csv")
    mines.to_csv(export_path, index=False)
    print(f"Prepared {len(mines):,} mining projects")

if __name__ == "__main__":
    main()