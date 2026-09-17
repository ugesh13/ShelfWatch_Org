"""
ShelfWatch Configuration
========================
Central configuration for all backend services.
"""
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "shelfwatch.db"

# ── Data Generator Settings ────────────────────────────────────────────────
NUM_FACILITIES = 18
NUM_DRUGS = 8
SIMULATION_DAYS = 90
SHOCK_START_DAY = 60        # Day when demand spike / supply delay begins
SHOCK_FACILITIES = 3        # Number of facilities hit by the shock
SHOCK_DEMAND_MULTIPLIER = 2.5   # Consumption multiplier during shock
SHOCK_REPLENISH_DELAY = 8      # Extra days added to replenishment lag

# ── Analytics Settings ─────────────────────────────────────────────────────
ANOMALY_WINDOW = 7           # Rolling window (days) for velocity calculation
ANOMALY_Z_THRESHOLD = 2.0   # z-score threshold for flagging anomalies
CUSUM_DRIFT = 0.5            # CUSUM allowable slack parameter
CUSUM_THRESHOLD = 5.0        # CUSUM decision interval

# ── Diffusion Model Settings ──────────────────────────────────────────────
DIFFUSION_DAYS_FORWARD = 14  # How many days to project cascade
RISK_THRESHOLD_AT_RISK = 0.4    # local_risk_score above this → At-Risk
RISK_THRESHOLD_CRITICAL = 0.7   # local_risk_score above this → Critical
DIFFUSION_BETA = 0.3         # Infection rate (how fast risk spreads to neighbors)
DIFFUSION_GAMMA = 0.05       # Recovery rate (natural restocking dampening)

# ── Optimizer Settings ─────────────────────────────────────────────────────
SEARCH_RADIUS_KM = 50        # Max distance to look for surplus donors
DONOR_SAFETY_DAYS = 7        # Minimum days-of-stock a donor must retain
MAX_RECOMMENDATIONS = 10     # Max transfer recommendations per run

# ── Confidence Band Settings ──────────────────────────────────────────────
BOOTSTRAP_ITERATIONS = 100   # Number of bootstrap runs for uncertainty
CONFIDENCE_LEVELS = [0.10, 0.50, 0.90]  # P10, P50, P90

# ── API Settings ──────────────────────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 8000
CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

# ── Drug Catalog ──────────────────────────────────────────────────────────
DRUG_CATALOG = [
    {"id": "AMX", "name": "Amoxicillin 500mg",      "unit": "capsules",  "criticality": 9, "daily_base": 45,  "reorder_days": 10},
    {"id": "CFT", "name": "Ceftriaxone 1g IV",       "unit": "vials",     "criticality": 10, "daily_base": 12,  "reorder_days": 14},
    {"id": "PCM", "name": "Paracetamol 500mg",       "unit": "tablets",   "criticality": 6,  "daily_base": 120, "reorder_days": 7},
    {"id": "INS", "name": "Insulin Glargine 100IU",  "unit": "pens",      "criticality": 10, "daily_base": 8,   "reorder_days": 14},
    {"id": "ORS", "name": "ORS Packets",             "unit": "sachets",   "criticality": 8,  "daily_base": 60,  "reorder_days": 7},
    {"id": "MET", "name": "Metformin 500mg",         "unit": "tablets",   "criticality": 7,  "daily_base": 80,  "reorder_days": 10},
    {"id": "SAL", "name": "Salbutamol Inhaler",      "unit": "inhalers",  "criticality": 8,  "daily_base": 5,   "reorder_days": 14},
    {"id": "IFA", "name": "Iron Folic Acid",         "unit": "tablets",   "criticality": 5,  "daily_base": 100, "reorder_days": 7},
]
