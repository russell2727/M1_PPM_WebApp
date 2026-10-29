"""Convert a PPM 'breakdown_export.xlsx' into data/in_market_auto_shoppers.csv.gz.

Usage:  python scripts/convert_export.py CountID_109671_breakdown_export.xlsx
"""
import sys
from pathlib import Path

import pandas as pd

src = Path(sys.argv[1])
dst = Path(__file__).resolve().parent.parent / "data" / "in_market_auto_shoppers.csv.gz"

df = pd.read_excel(src, dtype=str).dropna(subset=["Zip Code"])          # drops the grand-total row
df["Zip Code"] = df["Zip Code"].str.strip().str.zfill(5)                 # restore leading zeros
df["Total"] = pd.to_numeric(df["Total"], errors="coerce").fillna(0).astype(int)
df = df.rename(columns={"Zip Code": "zip", "MSA Name": "msa", "PPM Segment": "segment",
                        "PPM Type": "condition", "Total": "shopper_count"})
df["condition"] = df["condition"].str.title()
df.to_csv(dst, index=False, compression="gzip")
print(f"{len(df):,} rows, {df.shopper_count.sum():,} shoppers -> {dst}")
