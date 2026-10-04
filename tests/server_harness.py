#!/usr/bin/env python3
"""Shared helpers for the P2 server modules (alias / cache / price / schema /
hardening). server.py is a script, not an installed package, so it is imported
by path exactly once per test module.
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "futgg")


def load_server():
    """Import server.py by path under a stable module name."""
    spec = importlib.util.spec_from_file_location(
        "fc27_server", os.path.join(ROOT, "server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()
