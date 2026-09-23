"""Run with the documented alphagen Python 3.8 to guard pipeline imports."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class SingleFactorImportCompatibilityTests(unittest.TestCase):
    def test_first_party_pipeline_imports_in_fresh_interpreter(self):
        # A fresh process prevents modules cached by other tests from hiding
        # annotation evaluation errors. It imports only, without training PPO.
        project_root = Path(__file__).resolve().parents[2]
        script = """
import importlib
import sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
failures = []
for name in (
    'config', 'features', 'preprocess', 'data', 'expression', 'evaluator',
    'storage', 'runner', 'environment', 'universe', 'pool_selection', 'cli',
):
    try:
        importlib.import_module('single_factor.' + name)
    except Exception as exc:
        failures.append('{}: {}: {}'.format(name, type(exc).__name__, exc))
print('Python ' + sys.version.split()[0])
for failure in failures:
    print(failure)
sys.exit(bool(failures))
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(project_root), str(project_root / "custom_backtester")],
            cwd=str(project_root / "custom_backtester"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
