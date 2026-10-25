"""Mutation sanity check: apply one deliberate bug at a time to a COPY of the code and confirm
the test-suite fails. Usage: python tools/mutation_check.py"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUTATIONS = [
    ("memelab/filters.py", "return value <= threshold", "return value < threshold", "at_most boundary"),
    ("memelab/filters.py", "return value >= threshold", "return value > threshold", "at_least boundary"),
    ("memelab/filters.py", "    if value is None:\n        return False\n    return value <= threshold",
     "    if value is None:\n        return True\n    return value <= threshold", "missing data passes (fail-open)"),
    ("memelab/simulator.py", "p <= ref * (1 - e.stop_loss_pct / 100)", "p < ref * (1 - e.stop_loss_pct / 100)", "stop boundary"),
    ("memelab/simulator.py", "p <= peak * (1 - e.trailing.drawdown_pct / 100)", "p <= peak * (1 + e.trailing.drawdown_pct / 100)", "trailing sign"),
    ("memelab/simulator.py", "tokens0 * tp.sell_fraction", "tokens0 * tp.sell_fraction * 0.9", "tp fraction"),
    ("memelab/simulator.py", "realised <= -pf.daily_loss_stop_usd", "realised < -pf.daily_loss_stop_usd", "daily stop boundary"),
    ("memelab/execution.py", "(liquidity_usd / 2.0)", "(liquidity_usd)", "slippage reserve = L/2"),
    ("memelab/execution.py", "gross_usd * (1.0 - fee_pct / 100.0 - (tax_pct or 0.0) / 100.0)", "gross_usd * (1.0 - fee_pct / 100.0)", "tax ignored"),
    ("memelab/report.py", "sorted(pnls, reverse=True)[n:]", "sorted(pnls, reverse=True)[n + 1:]", "ex_top_n off by one"),
    ("memelab/report.py", "peak = max(peak, eq)", "peak = max(peak, eq) if peak else eq", "drawdown peak"),
    ("memelab/report.py", "share > CONCENTRATION_LIMIT", "share > 1.5", "concentration warning threshold"),
    ("memelab/fetch_meme_rush.py", '"top10_pct": _f(raw.get("holdersTop10Percent"))', '"top10_pct": (_f(raw.get("holdersTop10Percent")) or 0) * 100', "meme-rush percent x100"),
    ("memelab/fetch_meme_rush.py", '"buy_tax_pct": _f(raw.get("taxRateBuy"))', '"buy_tax_pct": _f(raw.get("taxRateBuy")) or 0.0', "meme-rush unknown tax -> 0"),
    ("memelab/fetch_meme_rush.py", "if res.status in (401, 403):", "if res.status in (999,):", "meme-rush auth block ignored"),
    ("memelab/fetch_meme_rush.py", "hit = next((r for r in recs if r.get(k) is not None), None)", "hit = next((r for r in reversed(recs) if r.get(k) is not None), None)", "meme-rush static = last (look-ahead)"),
    ("memelab/fetch_meme_rush.py", "if not first:\n                sleep(delay_s)", "if False:\n                sleep(delay_s)", "meme-rush rate limit removed"),
    ("memelab/models.py", "progress = c.progress_pct", "progress = None", "per-candle progress ignored"),
]
bad = 0
for rel, old, new, name in MUTATIONS:
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "p"
        shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".venv", "__pycache__", "out", ".pytest_cache"))
        f = dst / rel
        src = f.read_text()
        if old not in src:
            print(f"SKIP (pattern not found): {name}")
            bad += 1
            continue
        f.write_text(src.replace(old, new, 1))
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x"], cwd=dst, capture_output=True, text=True)
        killed = r.returncode != 0
        print(f"{'KILLED  ' if killed else 'SURVIVED'} {name}")
        bad += 0 if killed else 1
print("all mutants killed" if bad == 0 else f"{bad} problem(s)")
sys.exit(1 if bad else 0)
