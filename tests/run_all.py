#!/usr/bin/env python3
"""Run all hermes-verify-tjl tests and report combined results."""
import subprocess
import sys

tests = [
    ("verify_tjl_all.py", "US scanners: math + retry + regime"),
    ("verify_tjl_futu.py", "HK Futu scanner: math + watchlist + schema"),
    ("verify_compare_results.py", "Compare-results parsing + sandbox"),
]

total_passed = 0
total_count = 0
for script, desc in tests:
    path = f"/Users/jaydensmac/.local/share/hermes-verify-tjl/{script}"
    print(f"\n{'=' * 70}")
    print(f" {script} — {desc}")
    print(f"{'=' * 70}")
    r = subprocess.run(
        ["/Users/jaydensmac/.hermes/hermes-agent/venv/bin/python", path],
        capture_output=True, text=True, timeout=120,
    )
    # Show last few lines
    out_lines = r.stdout.split("\n")
    # Find RESULT line
    result_line = next((l for l in out_lines if "RESULT:" in l), "RESULT: ?")
    print(r.stdout[-3000:] if r.returncode != 0 else "\n".join(out_lines[-5:]))
    if r.returncode != 0:
        print("STDERR:", r.stderr[-500:])
    # Extract numbers from result
    import re
    m = re.search(r"RESULT: (\d+)/(\d+)", result_line)
    if m:
        total_passed += int(m.group(1))
        total_count += int(m.group(2))

print()
print("=" * 70)
print(f"OVERALL: {total_passed}/{total_count} checks passed")
print("=" * 70)
sys.exit(0 if total_passed == total_count else 1)