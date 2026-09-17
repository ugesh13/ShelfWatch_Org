"""
Pytest configuration and shared fixtures for ShelfWatch backend.
"""
import sys
import os
from pathlib import Path

# Ensure backend root is always in sys.path for test execution
BACKEND_DIR = Path(__file__).resolve().parent
os.environ["SHELFWATCH_DB"] = ":memory:"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
