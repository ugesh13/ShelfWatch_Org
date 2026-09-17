import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
backend_dir = root_dir / "backend"

for p in (root_dir, backend_dir):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.main import app
