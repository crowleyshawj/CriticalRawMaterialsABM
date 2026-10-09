# UNITS

LCE_PER_LI = 5.323
LCE_PER_LI2O = 2.473
BRINE_DENSITY = 1.2 # t per m3
LI_PER_LI2O = LCE_PER_LI2O / LCE_PER_LI

MINING_COLUMN_UNITS = {
    # Geological stocks: provisional contained-LCE interpretation.
    "reserves": "t contained Li",
    "reserves_filled": "t contained Li",
    "reserves_base_year": "t contained Li",
    "reserves_source" : "source quantity; see source_stock_basis",

    # Native grade units depend on the deposit route.
    "grade_base": "see grade_unit",
    "grade": "see grade_unit",
    "recovery_efficiency": "dimensionless",
    "contained_li_fraction": "t contained Li/t original material",
    "recovered_li_fraction": "t intermediate Li/t original material",

    # Durations.
    "pre_construction_years": "years",
    "construction_years": "years",
    "lifespan_years": "years",
    "capacity_years": "years",

    # Annual capacities.
    "capacity_contained_li": "t contained Li/year",
    "capacity_material": "t original material/year",
    "capacity_recovered_li": "t intermediate Li/year",

    # Operating expenditure per tonne of original feed.
    "opex_total": "2024 USD/t original material",
    "opex_multiplier": "dimensionless",

    # Total initial capital expenditure.
    "capex_total": "2024 USD",
    "capex_multiplier": "dimensionless",

    # Costs per tonne of recovered intermediate content.
    "opex_per_t_li": "2024 USD/t intermediate Li",
    "project_cost_per_t_li": "2024 USD/t intermediate Li",
}