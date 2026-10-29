"""
Data access layer.

Loads the shopper file + vehicle-type lookup once at startup (cached in
memory), geocodes ZIPs, and answers radius queries.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
import pandas as pd
import zipcodes

import config

log = logging.getLogger(__name__)

_ZIPS: dict[str, dict] | None = None


def _zip_table() -> dict[str, dict]:
    """ZIP -> {lat, lon, city, state} from the bundled `zipcodes` package (no network needed)."""
    global _ZIPS
    if _ZIPS is None:
        _ZIPS = {}
        for z in zipcodes.list_all():
            try:
                _ZIPS[z["zip_code"]] = {"lat": float(z["lat"]), "lon": float(z["long"]),
                                        "city": z["city"], "state": z["state"]}
            except (TypeError, ValueError):
                continue
    return _ZIPS

EARTH_RADIUS_MI = 3958.8


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def _norm_zip(series: pd.Series) -> pd.Series:
    return series.astype(str).str.extract(r"(\d{5})")[0].str.zfill(5)


@lru_cache(maxsize=1)
def load_shoppers() -> pd.DataFrame:
    """Return the shopper table with canonical columns:
    zip, state, condition, vehicle_key, shoppers, vehicle_type, lat, lon
    """
    c = config.COLUMNS
    df = pd.read_csv(config.SHOPPERS_FILE, dtype=str, low_memory=False)
    optional = {c.get("state"), c.get("msa")}
    missing = [v for v in c.values() if v not in df.columns and v not in optional]
    if missing:
        raise ValueError(
            f"Shopper file is missing columns {missing}. "
            f"Available: {list(df.columns)}. Fix COLUMNS in config.py."
        )

    out = pd.DataFrame({
        "zip":         _norm_zip(df[c["zip"]]),
        "state":       df[c["state"]].str.upper().str.strip() if c.get("state") in df.columns else "",
        "msa":         df[c["msa"]].fillna("").str.strip() if c.get("msa") in df.columns else "",
        "condition":   df[c["condition"]].str.strip().str.title(),
        "vehicle_key": df[c["vehicle_key"]].str.strip(),
        "shoppers":    pd.to_numeric(df[c["shoppers"]], errors="coerce").fillna(0).astype(int),
    })
    out = out.dropna(subset=["zip"])

    # ---- join vehicle type lookup
    lk = config.LOOKUP_COLUMNS
    lookup = pd.read_csv(config.VEHICLE_TYPE_LOOKUP_FILE, dtype=str)
    lookup = lookup[[lk["key"], lk["type"]]].rename(columns={lk["key"]: "vehicle_key", lk["type"]: "vehicle_type"})
    lookup["vehicle_key"] = lookup["vehicle_key"].str.strip()
    lookup["vehicle_type"] = lookup["vehicle_type"].str.strip()
    lookup = lookup.drop_duplicates("vehicle_key")
    out = out.merge(lookup, on="vehicle_key", how="left")
    out["vehicle_type"] = out["vehicle_type"].fillna("Other")

    # ---- geocode every distinct ZIP once (bundled table, no network)
    geo = pd.DataFrame.from_dict(_zip_table(), orient="index").rename_axis("zip").reset_index()
    out = out.merge(geo.rename(columns={"state": "state_code"}), on="zip", how="left")
    if (out["state"] == "").all():
        out["state"] = out["state_code"].fillna("")
    out = out.drop(columns=["state_code"])

    dropped = out["lat"].isna().sum()
    if dropped:
        log.warning("%s rows have ZIPs that could not be geocoded and will be ignored in radius searches", dropped)
    log.info("Loaded %s shopper rows across %s ZIPs", len(out), out["zip"].nunique())
    return out


def geocode_zip(zip_code: str) -> dict | None:
    z = str(zip_code).strip()[:5].zfill(5)
    r = _zip_table().get(z)
    if not r:
        return None
    return {"zip": z, **r}


# --------------------------------------------------------------------------
# Querying
# --------------------------------------------------------------------------
def _haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MI * np.arcsin(np.sqrt(a))


def query(zip_code: str, radius_mi: float, conditions: list[str], vehicle_types: list[str] | None = None) -> dict:
    """Core query used by both the dashboard and the PDF."""
    center = geocode_zip(zip_code)
    if not center:
        raise ValueError(f"ZIP {zip_code} could not be located.")

    df = load_shoppers().dropna(subset=["lat"]).copy()
    df["distance_mi"] = _haversine(center["lat"], center["lon"], df["lat"].values, df["lon"].values)
    df = df[df["distance_mi"] <= radius_mi]

    if conditions:
        df = df[df["condition"].isin([c.title() for c in conditions])]
    if vehicle_types:
        df = df[df["vehicle_type"].isin(vehicle_types)]

    total = int(df["shoppers"].sum())

    by_type = (df.groupby("vehicle_type")["shoppers"].sum()
                 .sort_values(ascending=False))
    by_condition = df.groupby("condition")["shoppers"].sum()
    by_type_cond = (df.pivot_table(index="vehicle_type", columns="condition",
                                   values="shoppers", aggfunc="sum", fill_value=0)
                      .reindex(by_type.index))

    by_msa = df.groupby("msa")["shoppers"].sum().sort_values(ascending=False)
    by_msa = by_msa[by_msa.index != ""].head(8)

    by_zip = (df.groupby(["zip", "city", "state", "lat", "lon"], dropna=False)["shoppers"].sum()
                .reset_index().sort_values("shoppers", ascending=False))
    by_zip["distance_mi"] = _haversine(center["lat"], center["lon"], by_zip["lat"].values, by_zip["lon"].values).round(1)

    # distance rings for the chart
    bins = [0, 5, 10, 25, 50, 100, 150, 10_000]
    labels = ["0-5", "5-10", "10-25", "25-50", "50-100", "100-150", "150+"]
    df["ring"] = pd.cut(df["distance_mi"], bins=bins, labels=labels, right=True, include_lowest=True)
    by_ring = df.groupby("ring", observed=False)["shoppers"].sum()
    by_ring = by_ring[by_ring > 0]

    return {
        "center": center,
        "radius_mi": radius_mi,
        "conditions": conditions,
        "total_shoppers": total,
        "zip_count": int(df["zip"].nunique()),
        "by_type": by_type.to_dict(),
        "by_condition": {k: int(v) for k, v in by_condition.items()},
        "by_type_condition": {t: {c: int(v) for c, v in row.items()} for t, row in by_type_cond.iterrows()},
        "by_ring": {str(k): int(v) for k, v in by_ring.items() if v > 0},
        "by_msa": {k: int(v) for k, v in by_msa.items()},
        "top_zips": by_zip.head(25).to_dict(orient="records"),
        "map_points": by_zip[["zip", "city", "lat", "lon", "shoppers"]].head(500).to_dict(orient="records"),
    }


def available_vehicle_types() -> list[str]:
    return sorted(load_shoppers()["vehicle_type"].unique().tolist())
