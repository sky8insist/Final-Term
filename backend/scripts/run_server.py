"""Run the FastAPI server with platform-specific runtime setup applied first."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime.windows_asyncio import configure_event_loop_policy

configure_event_loop_policy()

import uvicorn


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
