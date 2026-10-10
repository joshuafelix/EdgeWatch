# ingestion-llm/api_server.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json
from pathlib import Path

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # fine for a hackathon demo, tighten later if needed
    allow_methods=["GET"],
    allow_headers=["*"],
)

SNAPSHOT_PATH = Path(__file__).parent / "latest_snapshot.json"

@app.get("/api/latest")
def get_latest():
    if not SNAPSHOT_PATH.exists():
        return {"nodes": [], "fleet_summary": "No analysis yet."}
    try:
        with open(SNAPSHOT_PATH) as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {"nodes": [], "fleet_summary": "Snapshot mid-write, try again."}
    
BATCH_LOG_PATH = Path(__file__).parent / "batch_log.json"

@app.get("/api/batch-log")
def get_batch_log():
    if not BATCH_LOG_PATH.exists():
        return []
    with open(BATCH_LOG_PATH) as f:
        return json.load(f)
    
