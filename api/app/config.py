"""Declared demonstration assumptions; none are healthcare standards."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    DATABASE_PATH = Path(os.environ.get("SHELFWATCH_DB", "/tmp/shelfwatch_v1.db"))
else:
    DATABASE_PATH = Path(os.environ.get("SHELFWATCH_DB", PROJECT_ROOT / "data" / "shelfwatch_v1.db"))
SCHEMA_VERSION = "1.0"
ALGORITHM_VERSION = "inventory-1.1"
HISTORY_DAYS = 90
BASELINE_DAYS = 28
MIN_OBSERVATIONS = 21
DISPLAY_DAYS = 14
RESERVE_DAYS = 7
INTERNAL_DAYS = DISPLAY_DAYS + RESERVE_DAYS
PATH_COUNT = 200
HISTORY_SEED = 16092026
SCENARIO_SEED = 42
EVALUATION_SEED = 81000
PRESENTATION_SEED = 91000
MAX_STOCK_AGE_HOURS = 24
MIN_DELIVERY_OBSERVATIONS = 5
ASSUMED_DELAYS = (0, 1, 3)
WEEKDAY_SHRINKAGE = 3
PLANNING_QUANTILE = 0.8
HIGH_RISK_THRESHOLD = 0.5
WATCH_THRESHOLD = 0.2
DEMAND_ELEVATED_RATIO = 1.5
MAX_CACHE_ENTRIES = 64
MAX_IMPORT_BYTES = 10 * 1024 * 1024

# ── Anomaly Detection ─────────────────────────────────────────────────────
ANOMALY_WINDOW = 7               # Rolling window (days) for velocity calculation
ANOMALY_Z_THRESHOLD = 2.0        # z-score threshold for flagging anomalies
CUSUM_DRIFT = 0.5                # CUSUM allowable slack parameter (k = 0.5σ)
CUSUM_THRESHOLD = 5.0            # CUSUM decision interval (h = 5σ)
RISK_THRESHOLD_AT_RISK = 0.4     # local_risk_score above this → At-Risk
RISK_THRESHOLD_CRITICAL = 0.7    # local_risk_score above this → Critical

# ── Shortage Fingerprinting ───────────────────────────────────────────────
SPIKE_RATIO_DEMAND_SURGE = 2.5   # consumption spike ratio for demand surge
SPIKE_RATIO_HOARDING = 3.0       # single-day ratio for panic hoarding
SUPPLY_GAP_MULTIPLIER = 1.5      # supply gap > 1.5x expected → supply disruption
CHRONIC_EROSION_SLOPE = -0.3     # negative trend slope over 21+ days
CHRONIC_EROSION_WINDOW = 21      # minimum days for chronic erosion detection
NEIGHBOR_Z_NORMAL = 1.5          # neighbor z-score below this = normal
FINGERPRINT_WINDOW = 14          # days of consumption to analyse for fingerprinting

# ── Domino Index ──────────────────────────────────────────────────────────
DOMINO_SIMULATION_DAYS = 7       # forward simulation window for cascade counting
DOMINO_NEIGHBOUR_RADIUS_KM = 30  # max distance for alternative source lookup
DOMINO_RISK_TRANSFER_RATE = 0.3  # how much risk transfers to dependent neighbours

# ── SIS Diffusion Model ──────────────────────────────────────────────────
DIFFUSION_DAYS_FORWARD = 14      # how many days to project cascade
DIFFUSION_BETA_AT_RISK = 0.2     # infection rate from At-Risk facility
DIFFUSION_BETA_CRITICAL = 0.4    # infection rate from Critical facility
DIFFUSION_RECOVERY_GAMMA = 0.3   # recovery rate when actual replenishment arrives

PRODUCTS = [
    {"sku_id": "AMX500_CAP", "generic_name": "Amoxicillin", "strength": "500 mg", "dosage_form": "capsule", "base_unit": "capsules", "storage_class": "ROOM_TEMPERATURE"},
    {"sku_id": "PCM500_TAB", "generic_name": "Paracetamol", "strength": "500 mg", "dosage_form": "tablet", "base_unit": "tablets", "storage_class": "ROOM_TEMPERATURE"},
    {"sku_id": "ORS1L_SACHET", "generic_name": "ORS", "strength": "1 litre formulation", "dosage_form": "sachet", "base_unit": "sachets", "storage_class": "ROOM_TEMPERATURE"},
    {"sku_id": "MET500_TAB", "generic_name": "Metformin", "strength": "500 mg", "dosage_form": "tablet", "base_unit": "tablets", "storage_class": "ROOM_TEMPERATURE"},
    {"sku_id": "CET10_TAB", "generic_name": "Cetirizine", "strength": "10 mg", "dosage_form": "tablet", "base_unit": "tablets", "storage_class": "ROOM_TEMPERATURE"},
]
