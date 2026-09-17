import sys
from pathlib import Path
from fastapi.staticfiles import StaticFiles

# Add backend directory to sys.path so that app.* modules import cleanly
backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app

# Mount built frontend static files if available
dist_dir = Path(__file__).resolve().parent / "frontend" / "dist"
if dist_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
