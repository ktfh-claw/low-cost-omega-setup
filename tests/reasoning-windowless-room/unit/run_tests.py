#!/usr/bin/env python3
"""Stdlib test-runner shim for the windowless-room benchmark unit tests.

Discovers test_* functions in test_*.py files in this directory and runs
them with plain asserts (no pytest dependency). Usage:
    python3 unit/run_tests.py
"""
import importlib
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))


def run_tests() -> int:
    """Run all test_* functions from test_*.py modules in this directory."""
    passed = 0
    failed = 0
    errors = []

    test_files = sorted(f for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py"))

    for fname in test_files:
        mod_name = fname[:-3]
        try:
            mod = importlib.import_module(mod_name)
        except ImportError as e:
            errors.append(f"{mod_name}: import error: {e}")
            continue

        for attr_name in sorted(dir(mod)):
            if attr_name.startswith("test_"):
                fn = getattr(mod, attr_name)
                if callable(fn):
                    try:
                        fn()
                        passed += 1
                    except AssertionError as e:
                        failed += 1
                        print(f"FAIL: {attr_name}: {e}")
                    except Exception as e:
                        failed += 1
                        print(f"ERROR: {attr_name}: {e}")

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 and not errors else 1


if __name__ == "__main__":
    sys.exit(run_tests())
