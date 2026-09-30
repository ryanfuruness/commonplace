import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_demo_runs_end_to_end():
    out = subprocess.run([sys.executable, "demo/seed_demo.py", "--no-serve"], cwd=ROOT, capture_output=True,
                         text=True, timeout=240)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "promoted" in out.stdout and "0 awaiting curation" in out.stdout
