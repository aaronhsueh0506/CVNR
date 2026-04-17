#!/usr/bin/env python3
"""
Analyze WindDetector behavior from dump summary.csv.

Prints:
- Mean wind_prob, fraction > mild, fraction > severe, hangover active %
- Top-10 files with highest mean wind_prob (likely false alarms if in clean set)
- Per-feature distribution analysis

Usage:
  python3 tools/analyze_wind_detector.py dumps/vctk_clean/summary.csv
  python3 tools/analyze_wind_detector.py dumps/vctk_clean/summary.csv dumps/wind_synth/summary.csv
"""

import sys
import os
import argparse
import csv
from collections import defaultdict


def load_summary(path):
    rows = []
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            # 過濾 init frames
            is_init = row.get('is_init', '0')
            if is_init in ('True', 'true', '1', '1.0'):
                continue
            rows.append(row)
    return rows


def analyze(path, mild_th=0.5, severe_th=0.85):
    rows = load_summary(path)
    if not rows:
        print(f"[{path}] no data")
        return
    n = len(rows)

    wp = [float(r['wind_prob']) for r in rows]
    ler = [float(r['feat_ler']) for r in rows]
    tilt = [float(r['feat_tilt_db']) for r in rows]
    zcr = [float(r['feat_zcr']) for r in rows if float(r['feat_zcr']) >= 0]
    hang = [int(float(r['hangover_active'])) for r in rows]

    frac_mild = sum(p > mild_th for p in wp) / n
    frac_sev = sum(p > severe_th for p in wp) / n
    frac_hang = sum(hang) / n

    import statistics as st
    print(f"\n==== {path}  (n_frames={n}) ====")
    print(f"  wind_prob:  mean={st.mean(wp):.3f}  median={st.median(wp):.3f}  p80={sorted(wp)[int(0.8*n)]:.3f}  p95={sorted(wp)[int(0.95*n)]:.3f}")
    print(f"  frac(>{mild_th:.2f} mild): {frac_mild*100:.1f}%")
    print(f"  frac(>{severe_th:.2f} severe): {frac_sev*100:.1f}%")
    print(f"  hangover active: {frac_hang*100:.1f}%")
    print(f"  feat_ler:   mean={st.mean(ler):.3f}  p95={sorted(ler)[int(0.95*n)]:.3f}")
    print(f"  feat_tilt:  mean={st.mean(tilt):+.1f}dB  p95={sorted(tilt)[int(0.95*n)]:+.1f}dB")
    if zcr:
        print(f"  feat_zcr:   mean={st.mean(zcr):.4f}  p05={sorted(zcr)[int(0.05*len(zcr))]:.4f}  p95={sorted(zcr)[int(0.95*len(zcr))]:.4f}")

    # Per-file aggregate wind_prob
    per_file = defaultdict(list)
    for r in rows:
        per_file[r['file']].append(float(r['wind_prob']))

    file_means = {f: sum(v) / len(v) for f, v in per_file.items()}
    top_files = sorted(file_means.items(), key=lambda x: x[1], reverse=True)[:10]
    print(f"  Top-10 files by mean wind_prob:")
    for fn, m in top_files:
        print(f"    {fn:30s} mean={m:.3f}  n_frames={len(per_file[fn])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('summary_csvs', nargs='+')
    ap.add_argument('--mild-threshold', type=float, default=0.5)
    ap.add_argument('--severe-threshold', type=float, default=0.85)
    args = ap.parse_args()

    for p in args.summary_csvs:
        analyze(p, args.mild_threshold, args.severe_threshold)


if __name__ == '__main__':
    main()
