from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_SOURCE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "iea_demand.xlsx"
)

SCENARIO_COLUMNS = {
    "CPS": [1, 3, 4, 5, 6, 7],
    "STEPS": [1, 9, 10, 11, 12, 13],
    "HDS": [1, 15, 16, 17, 18, 19],
}


def load_iea_demand(source_path=DEFAULT_SOURCE_PATH):
    """Return total global demand in tonnes of elemental lithium per year."""
    raw = pd.read_excel(source_path, sheet_name="Sheet1", header=None)

    labels = raw.iloc[:, 0].astype("string").str.strip()
    total_rows = raw.loc[labels.eq("Total demand").fillna(False)]

    if len(total_rows) != 1:
        raise ValueError("Expected one Total demand row.")

    annual_years = np.arange(2025, 2051)
    expected_years = np.array([2025, 2030, 2035, 2040, 2045, 2050])
    tables = []

    for scenario, columns in SCENARIO_COLUMNS.items():
        anchor_years = pd.to_numeric(
            raw.iloc[1, columns], errors="raise"
        ).to_numpy(dtype=float)

        # The supplied workbook uses kt Li.
        anchor_demand = pd.to_numeric(
            total_rows.iloc[0, columns], errors="raise"
        ).to_numpy(dtype=float) * 1000.0

        if not np.array_equal(anchor_years, expected_years):
            raise ValueError(f"Unexpected anchor years for {scenario}.")

        if (
            not np.isfinite(anchor_demand).all()
            or (anchor_demand < 0).any()
        ):
            raise ValueError(f"Invalid demand for {scenario}.")

        tables.append(pd.DataFrame({
            "scenario": scenario,
            "year": annual_years,
            "demand_t_li": np.interp(
                annual_years, anchor_years, anchor_demand
            ),
            "is_interpolated": ~np.isin(annual_years, anchor_years),
        }))

    demand = pd.concat(tables, ignore_index=True)
    demand.attrs.update(
        source_workbook=str(source_path),
        source_sheet="Sheet1",
        source_edition="IEA Global Critical Minerals Outlook 2026",
        source_unit="kt Li",
        unit="t Li/year",
    )
    return demand

def to_model_demand(
    demand_table, *, scenario, start_year, demand_boundary,
    manufacturing_efficiency,
):
    """Convert annual t Li to the model's final-product proxy tonnes."""
    from .units import LCE_PER_LI

    if not 0 < manufacturing_efficiency <= 1:
        raise ValueError("Manufacturing efficiency must be in (0, 1].")

    if demand_boundary not in {
        "manufacturing_input", "delivered_product"
    }:
        raise ValueError("Unknown demand boundary.")

    selected = demand_table.loc[
        demand_table["scenario"].eq(scenario)
        & demand_table["year"].ge(start_year)
    ].sort_values("year")

    if selected.empty:
        raise ValueError("No demand for the requested scenario and year.")

    years = selected["year"].to_numpy()
    if not np.array_equal(years, np.arange(start_year, years[-1] + 1)):
        raise ValueError("Demand years must be unique and consecutive.")

    demand_t_li = selected["demand_t_li"].to_numpy(dtype=float)
    if not np.isfinite(demand_t_li).all() or (demand_t_li < 0).any():
        raise ValueError("Demand must be finite and non-negative.")

    final_product_t = demand_t_li * LCE_PER_LI
    if demand_boundary == "manufacturing_input":
        final_product_t *= manufacturing_efficiency

    return {
        int(year): float(quantity)
        for year, quantity in zip(years, final_product_t)
    }