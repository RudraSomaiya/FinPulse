#!/usr/bin/env python3
"""Quick import smoke test for the FinPulse backend."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import backend.config  # sets up sys.path
    from backend.main import app
    print("✓ Backend imports OK")
    print(f"✓ Routes: {[r.path for r in app.routes]}")
except Exception as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)
