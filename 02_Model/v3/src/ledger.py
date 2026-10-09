"""Moves component masses between asset stocks and keeps a log of every movement."""

from dataclasses import dataclass
from math import fsum, isclose

import pandas as pd

TOL = 1e-9


@dataclass(frozen=True)
class StockRef:
    holder_id: str | int
    stock: str
    material_form: str


@dataclass(frozen=True)
class Movement:
    source: StockRef
    destination: StockRef
    component_masses_t: dict[str, float]


@dataclass(frozen=True)
class MaterialEvent:
    event_id: str
    period: int
    event_kind: str
    stage: str
    asset_id: str | int
    movements: tuple[Movement, ...]
    operating_cost: float = 0.0


class MaterialLedger:
    """Asset stocks are the record; the ledger moves mass and checks closure."""

    def __init__(self, holders):
        self.holders = {holder.asset_id: holder for holder in holders}
        self.opening = self.snapshot()
        self.events = []
        self.movements = []

    def snapshot(self):
        return {(holder_id, stock, form, component): mass
                for holder_id, holder in self.holders.items()
                for (stock, form), masses in holder.stocks.items()
                for component, mass in masses.items()}

    def account(self, ref):
        return self.holders[ref.holder_id].stocks[(ref.stock, ref.material_form)]

    def post_event(self, event):
        for movement_id, movement in enumerate(event.movements, start=1):
            source = self.account(movement.source)
            destination = self.account(movement.destination)

            for component, mass in movement.component_masses_t.items():
                available = source.get(component, 0.0)
                if mass < -TOL or mass > available + max(TOL, 1e-12 * available):
                    raise ValueError(f"{event.event_id}: cannot move {mass} t {component} from {movement.source}")

                source[component] = max(0.0, source[component] - mass)
                destination[component] = destination.get(component, 0.0) + mass
                self.movements.append({"event_id": event.event_id, "movement_id": movement_id,
                                       "component": component, "quantity_t": mass,
                                       "source": movement.source, "destination": movement.destination})

        self.events.append({"event_id": event.event_id, "period": event.period, "event_kind": event.event_kind,
                            "stage": event.stage, "asset_id": event.asset_id, "operating_cost": event.operating_cost})
        return event.event_id

    def check_conservation(self):
        """Total mass of each component must equal its opening total."""
        closing = self.snapshot()
        for component in {key[-1] for key in self.opening}:
            before = fsum(mass for key, mass in self.opening.items() if key[-1] == component)
            after = fsum(mass for key, mass in closing.items() if key[-1] == component)
            if not isclose(before, after, rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError(f"System imbalance for {component}: {before} vs {after}")
        return True

    def to_dataframes(self):
        columns = ["holder_id", "stock", "material_form", "component", "quantity_t"]
        stocks = lambda balances: pd.DataFrame([(*key, mass) for key, mass in balances.items()], columns=pd.Index(columns))
        movements = pd.DataFrame([{
            **{k: row[k] for k in ("event_id", "movement_id", "component", "quantity_t")},
            "source_id": row["source"].holder_id, "source_stock": row["source"].stock, "source_form": row["source"].material_form,
            "destination_id": row["destination"].holder_id, "destination_stock": row["destination"].stock,
            "destination_form": row["destination"].material_form} for row in self.movements])
        return {"opening_stocks": stocks(self.opening), "current_stocks": stocks(self.snapshot()),
                "events": pd.DataFrame(self.events), "movements": movements}
