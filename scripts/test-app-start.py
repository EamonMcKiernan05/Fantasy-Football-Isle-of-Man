#!/usr/bin/env python3
"""Test that the app loads with FFIOM-DB separation."""
import sys
sys.path.insert(0, '.')

try:
    from app.main import app
    print("App loaded successfully!")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
