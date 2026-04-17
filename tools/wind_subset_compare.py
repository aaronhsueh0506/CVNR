#!/usr/bin/env python3
"""
Compare per-file metrics on wind subset between enhanced-dir variants.

Parses compute_improvement_vctk outputs (txt) to extract per-file metrics,
filters by wind_subset.txt, and prints average over subset.

Usage:
    python3 tools/wind_subset_compare.py \
        --subset results/wind_subset.txt \
        --reports results/c1_v3_2_fixed.txt results/c4_v4_phase3.txt
"""

import re
import argparse
from pathlib import Path


def parse_metrics(txt_path):
    pat = re.compile(
        r'(p\d+_\d+\.wav):\s+segSNR=([+-]?[\d.]+),\s+fwSegSNR=([+-]?[\d.]+),\s+PESQ=([\d.]+),\s+STOI=([\d.]+)'
    )
    results = {}
    with open(txt_path) as f:
        for line in f:
            m = pat.search(line)
            if m:
                fn, seg, fwseg, pesq, stoi = m.groups()
                results[fn] = {
                    'segSNR': float(seg),
                    'fwSegSNR': float(fwseg),
                    'PESQ': float(pesq),
                    'STOI': float(stoi),
                }
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--subset', required=True)
    ap.add_argument('--reports', nargs='+', required=True)
    args = ap.parse_args()

    with open(args.subset) as f:
        subset = set(line.strip() for line in f if line.strip())

    for rpt in args.reports:
        data = parse_metrics(rpt)
        tag = Path(rpt).stem
        filtered = {k: v for k, v in data.items() if k in subset}
        n = len(filtered)
        if n == 0:
            print(f"[{tag}] no matching files")
            continue
        avg = {}
        for key in ['segSNR', 'fwSegSNR', 'PESQ', 'STOI']:
            avg[key] = sum(v[key] for v in filtered.values()) / n

        print(f"[{tag}] n={n}  PESQ={avg['PESQ']:.3f}  STOI={avg['STOI']:.3f}  "
              f"segSNR={avg['segSNR']:+.2f}  fwSegSNR={avg['fwSegSNR']:+.2f}")


if __name__ == "__main__":
    main()
