"""
Batch driver — ingest the top 13 blocks from the Kobo SHG form into
villages.csv + shg_kobo_clean.csv, applying canonical-name renames so the
output matches `4DSS_VAR_2.0.shp` block names.

Run from the leaf_flask directory:
    python ingest_kobo_top_blocks.py --xlsx <path-to-kobo-export.xlsx>
"""

import argparse
import subprocess
import sys
from pathlib import Path

# (kobo_district, kobo_block, canonical_block_or_None)
TOP_BLOCKS = [
    ("DHEMAJI",       "MURKONGSELEK TRIBAL", "MURKONGSELEK"),
    ("DIBRUGARH",     "NAHARKATIA",          None),  # boundary sourced separately
    ("BISWANATH",     "PUB-CHAIDUAR",        "PUB CHAIDUAR"),
    ("LAKHIMPUR",     "DHAKUAKHANA",         None),
    ("UDALGURI",      "BHERGAON",            None),
    ("LAKHIMPUR",     "NOWBOICHA",           None),
    ("SIVASAGAR",     "GAURISAGAR",          None),
    ("BAKSA",         "JALAH",               None),
    ("CHIRANG",       "BOROBAZAR",           None),
    ("SIVASAGAR",     "DEMOW",               None),
    ("DIBRUGARH",     "LAHOWAL",             None),  # geometry transplanted from Block_assam.shp
    ("LAKHIMPUR",     "GHILAMARA",           None),
    ("LAKHIMPUR",     "BOGINADI",            None),
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--xlsx", required=True, type=Path)
    args = p.parse_args()

    here = Path(__file__).parent
    failures = []
    for district, block, canonical in TOP_BLOCKS:
        cmd = [
            sys.executable, str(here / "ingest_kobo.py"),
            "--xlsx", str(args.xlsx),
            "--district", district,
            "--block", block,
        ]
        if canonical:
            cmd += ["--canonical-block", canonical]
        print(f"\n>>> {district} / {block}" + (f"  ->  {canonical}" if canonical else ""))
        rc = subprocess.call(cmd)
        if rc != 0:
            failures.append((district, block, rc))
    if failures:
        print(f"\n{len(failures)} blocks failed:", *failures, sep="\n  ")
        return 1
    print(f"\nIngested {len(TOP_BLOCKS)} blocks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
