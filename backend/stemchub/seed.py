"""Fills the LOCAL dev stack with demo content:  python -m stemchub.seed [--sample-dir /data/sample]

- uploads the sample .czi files into Nextcloud following the naming rule  INDUZELL/<run>/day<NN>/<file>.czi
- uploads a process.csv per run (SYNTHETIC values, clearly marked — real ones come from the lab)
- creates one eLabFTW experiment per run with the extra field run_id

The run/day assignment of the sample files is invented for the demo: the files themselves carry no run or day.
"""

import argparse
import math
from pathlib import Path

from stemchub.config import get_settings
from stemchub.connectors.elabftw import ElabClient
from stemchub.connectors.nextcloud import NextcloudClient

# sample file -> (run, day)   — demo assignment
SAMPLE_PLACEMENT = {
    "New-04.czi": ("U1", 5),
    "New-05.czi": ("U3", 5),
    "New-09.czi": ("U3", 9),
}

RUNS = {
    "U1": {"cell_line": "hPSC line A (demo)", "protocol": "Cardiac differentiation v2", "glucose_drop": 0.30},
    "U3": {"cell_line": "hPSC line A (demo)", "protocol": "Cardiac differentiation v2", "glucose_drop": 0.38},
}


def synthetic_process_csv(glucose_drop: float) -> str:
    """Plausible-looking curves for days -2..10 (NOT real data)."""
    lines = ["day,parameter,value,unit"]
    for day in range(-2, 11):
        t = day + 2
        glucose = max(4.5 - glucose_drop * t, 0.6)
        lactate = 0.2 + 0.32 * t * (1 - math.exp(-t / 6))
        ph = 7.35 - 0.025 * t + (0.04 if day in (0, 1) else 0)  # medium change at CHIR/IWP-2
        lines += [
            f"{day},pH,{ph:.2f},",
            f"{day},glucose,{glucose:.2f},g/L",
            f"{day},lactate,{lactate:.2f},g/L",
            f"{day},temperature,{37.0 + 0.1 * math.sin(day):.1f},°C",
        ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample-dir", default="/data/sample")
    parser.add_argument("--skip-elab", action="store_true")
    args = parser.parse_args()
    s = get_settings()
    root = s.nextcloud_root

    with NextcloudClient(s) as nc:
        for name, (run, day) in SAMPLE_PLACEMENT.items():
            src = Path(args.sample_dir) / name
            if not src.exists():
                print(f"skip {name}: not found in {args.sample_dir}")
                continue
            dest = f"{root}/{run}/day{day:02d}/{name}"
            nc.upload(dest, src)
            print(f"uploaded {dest}")
        for run, meta in RUNS.items():
            dest = f"{root}/{run}/process.csv"
            nc.upload(dest, synthetic_process_csv(meta["glucose_drop"]).encode())
            print(f"uploaded {dest}  (synthetic process data)")

    if args.skip_elab:
        return
    with ElabClient(s) as elab:
        existing = {r.run_id for r in elab.runs()}
        for run, meta in RUNS.items():
            if run in existing:
                print(f"eLabFTW: run {run} already exists")
                continue
            elab_id = elab.create_experiment(
                title=f"Run {run} – hPSC cardiac differentiation (demo)",
                body="<p>Demo entry created by <code>stemchub.seed</code>. Process values are synthetic.</p>",
                fields={
                    "run_id": {"type": "text", "value": run, "position": 0},
                    "cell_line": {"type": "text", "value": meta["cell_line"], "position": 1},
                    "protocol": {"type": "text", "value": meta["protocol"], "position": 2},
                },
                tags=["induzell", run],
            )
            print(f"eLabFTW: created experiment #{elab_id} for run {run}")

    # don't wait for the schedule (Nextcloud every minute, eLabFTW every 2 minutes)
    from celery import Celery

    tasks = Celery("stemchub", broker=s.redis_url)
    tasks.send_task("stemchub.worker.sync_elabftw")
    tasks.send_task("stemchub.worker.poll_nextcloud")
    print("started the import and the eLabFTW sync")


if __name__ == "__main__":
    main()
