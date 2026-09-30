"""Regenerate all committed segment outputs from one reproducible synthetic run."""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from generate_loans import generate, PRODUCTS, VINTAGES
from build_triangle import (build_triangle, build_overlay_curve, TERMS,
                            OBSERVATION_DATE, RAW_AGGREGATION_SQL, ORIGINATIONS_SQL)
from payment_curves import derive_payment_curves


def precompute(rows=2_000_000, seed=42):
    data = Path(__file__).parent / 'data'
    data.mkdir(exist_ok=True)
    start = time.perf_counter()
    loans = generate(rows, verbose=False, seed=seed)
    gen_seconds = time.perf_counter() - start
    start = time.perf_counter()
    triangle = build_triangle(loans)
    tri_seconds = time.perf_counter() - start
    overlay = build_overlay_curve(triangle)
    curves = derive_payment_curves(loans)
    loans.to_parquet(data / 'loans.parquet', index=False)
    sample = loans.sample(min(rows, 40), random_state=seed).sort_values(['product','vintage'])
    sample.to_csv(data / 'loans_sample.csv', index=False)
    sample.to_csv(data / 'payment_sample.csv', index=False)
    triangle.to_parquet(data / 'vintage_triangle.parquet', index=False)
    overlay.to_csv(data / 'overlay_curve.csv', index=False)
    (data / 'payment_curves.json').write_text(json.dumps(curves, indent=2), encoding='utf-8')
    stats = {
        'generation': {
            'seed': seed, 'total_rows': len(loans), 'generation_seconds':gen_seconds,
            'vintage_range':[str(VINTAGES[0]),str(VINTAGES[-1])], 'vintages':len(VINTAGES),
            'loan_id_unique':bool(loans.loan_id.is_unique),
            'segment_assumptions':PRODUCTS,
            'product_mix_pct': {p:{'observed':float(loans['product'].eq(p).mean()*100),'target':c['share']*100} for p,c in PRODUCTS.items()},
            'default_rate_vs_target': {p:{'observed':float(loans.loc[loans['product'].eq(p),'default_flag'].mean()),'target':c['lifetime_default']} for p,c in PRODUCTS.items()},
        },
        'triangle': {
            'run_at':datetime.now().isoformat(timespec='seconds'), 'rows_loaded':len(loans),
            'triangle_build_seconds':tri_seconds, 'observation_date':str(OBSERVATION_DATE),
            'triangle_cells':len(triangle),
            'cells_excluded_by_censoring':sum((t+1)*len(VINTAGES) for t in TERMS.values())-len(triangle),
            'sql_queries':{'defaults_by_mob':RAW_AGGREGATION_SQL.strip(),'originations_by_vintage':ORIGINATIONS_SQL.strip()},
        },
    }
    (data / 'generation_stats.json').write_text(json.dumps(stats, indent=2), encoding='utf-8')
    print(f'{len(loans):,} loans; {len(triangle)} observed triangle cells; {len(overlay)} curve points; four matching segment curves.')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--rows',type=int,default=2_000_000)
    parser.add_argument('--seed',type=int,default=42)
    args=parser.parse_args()
    precompute(args.rows,args.seed)
