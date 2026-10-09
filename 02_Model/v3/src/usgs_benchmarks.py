from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_SOURCE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "mining_USGS.xlsx"
)


def load_usgs_benchmarks(source_path=DEFAULT_SOURCE_PATH):
    """Preserve workbook entries alongside cleaned lithium benchmarks."""
    columns = [
        "Country", "Production_2024", "Production_2025",
        "Reserves", "Resources",
    ]
    raw = pd.read_excel(
        source_path, sheet_name="Sheet1", usecols=columns
    )
    raw = raw.loc[raw["Country"].notna()].reset_index(drop=True)

    df = raw.rename(columns={
        column: column.lower() + "_workbook"
        for column in columns
    })

    df["country"] = (
        df["country_workbook"].astype("string").str.strip()
        .replace({"USA": "United States"})
    )
    if df["country"].eq("").any() or df["country"].duplicated().any():
        raise ValueError("Countries must be present and unique.")

    df["is_aggregate"] = df["country"].eq("ROW")
    df["cleaning_note"] = ""

    fields = [
        "production_2024", "production_2025", "reserves", "resources"
    ]
    for field in fields:
        df[field + "_t_li"] = pd.to_numeric(
            df[field + "_workbook"], errors="raise"
        ).astype(float)

    argentina = df["country"].eq("Argentina")
    if not df.loc[
        argentina, "production_2025_t_li"
    ].isin([2300, 23000]).all():
        raise ValueError("Review the Argentina production entry.")

    corrected = argentina & df["production_2025_t_li"].eq(2300)
    df.loc[corrected, "production_2025_t_li"] = 23000.0
    df.loc[corrected, "cleaning_note"] = (
        "Argentina 2025: workbook 2300 corrected to USGS 23000 t Li."
    )

    us = df["country"].eq("United States")
    for year in [2024, 2025]:
        quantity = f"production_{year}_t_li"
        status = f"production_{year}_status"

        df[status] = np.where(
            df[quantity].notna(), "estimated", "missing"
        )
        df.loc[us, quantity] = np.nan
        df.loc[us, status] = "withheld"
        df.loc[df["is_aggregate"], status] = "source_dash_zero"

    df.loc[
        df["country"].isin(["Argentina", "Chile"]),
        "production_2024_status",
    ] = "reported"

    df.loc[us, "cleaning_note"] = (
        "Workbook production zeros replaced by missing: USGS W (withheld)."
    )

    df["resources_status"] = np.where(
        df["resources_t_li"].notna(), "source_quantity", "missing"
    )
    df.loc[df["is_aggregate"], "resources_status"] = (
        "workbook_aggregate_unverified"
    )

    for field in fields:
        quantities = df[field + "_t_li"].dropna()
        if not np.isfinite(quantities).all() or quantities.lt(0).any():
            raise ValueError(f"Invalid quantities in {field}.")

    df.attrs.update(
        source_workbook=str(source_path),
        source_edition="USGS Mineral Commodity Summaries 2026",
        publication_year=2026,
        unit="t Li",
        stock_reporting_vintage="MCS 2026; exact stock dates unspecified",
        source_url=(
            "https://pubs.usgs.gov/periodicals/"
            "mcs2026/mcs2026-lithium.pdf"
        ),
        australia_reserves_note=(
            "Source footnote: JORC-compliant or equivalent reserves "
            "are 5.1 million t Li."
        ),
    )
    return df