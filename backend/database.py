"""
ClimateShield - Persistent Baseline Database Engine (SQLite)
Provides persistent storage for Ward profiles, Interventions catalog,
Municipal outcome tracking (mortality, hospital admissions, 108 calls),
and Optimization audit history.
"""

import sqlite3
import os
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
import shutil

if os.environ.get("VERCEL"):
    TMP_DB = "/tmp/climateshield_baseline.db"
    ORIGINAL_DB = os.path.join(os.path.dirname(__file__), "data", "climateshield_baseline.db")
    if not os.path.exists(TMP_DB) and os.path.exists(ORIGINAL_DB):
        try:
            shutil.copy2(ORIGINAL_DB, TMP_DB)
        except Exception:
            pass
    DB_PATH = TMP_DB
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "climateshield_baseline.db")


def get_db_connection() -> sqlite3.Connection:
    """Returns a connection to the SQLite baseline database with row dict factory, WAL mode, and foreign keys enabled."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Initializes tables in the baseline database."""
    conn = get_db_connection()
    conn.execute("PRAGMA journal_mode = WAL;")
    cursor = conn.cursor()

    # 1. Wards Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wards (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        slum_density REAL NOT NULL,
        outdoor_labor_ratio REAL NOT NULL,
        elderly_ratio REAL NOT NULL,
        baseline_heat_risk REAL NOT NULL,
        population INTEGER DEFAULT 100000,
        area_sq_km REAL DEFAULT 5.0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Interventions Catalog
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS interventions (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cost_inr REAL NOT NULL,
        crew_req INTEGER NOT NULL,
        water_req_l REAL NOT NULL,
        base_risk_reduction REAL NOT NULL,
        max_per_ward INTEGER NOT NULL,
        vulnerable_impact_json TEXT NOT NULL
    );
    """)

    # 3. Ground-truth Municipal Outcome Records (Data-Sharing Agreements)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS outcome_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_date TEXT NOT NULL,
        ward_id TEXT NOT NULL,
        hospital_heat_admissions INTEGER DEFAULT 0,
        mortality_count INTEGER DEFAULT 0,
        emergency_108_calls INTEGER DEFAULT 0,
        water_scarcity_complaints INTEGER DEFAULT 0,
        reported_by TEXT DEFAULT 'AMC_HEALTH_SURVEILLANCE',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (ward_id) REFERENCES wards (id)
    );
    """)

    # 4. Optimization Audit Runs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS optimization_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        budget_inr REAL NOT NULL,
        crew_members INTEGER NOT NULL,
        water_cap_l REAL NOT NULL,
        equity_slider REAL NOT NULL,
        total_cost_inr REAL NOT NULL,
        total_risk_reduction REAL NOT NULL,
        allocation_summary_json TEXT NOT NULL
    );
    """)

    # 5. Learning Loop: Historical Risk Predictions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS predictions (
        prediction_id TEXT PRIMARY KEY,
        ward_id TEXT NOT NULL,
        ward_name TEXT,
        timestamp TEXT NOT NULL,
        hazard_type TEXT NOT NULL,
        predicted_risk_score REAL NOT NULL,
        risk_category TEXT NOT NULL,
        data_source TEXT NOT NULL,
        provenance TEXT NOT NULL DEFAULT 'ESTIMATED',
        details_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (ward_id) REFERENCES wards (id)
    );
    """)

    # 6. Learning Loop: Recommended Interventions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS recommendations (
        recommendation_id TEXT PRIMARY KEY,
        prediction_id TEXT NOT NULL,
        ward_id TEXT NOT NULL,
        intervention_type TEXT NOT NULL,
        priority_score REAL,
        estimated_cost_inr REAL,
        expected_impact_min REAL,
        expected_impact_expected REAL,
        expected_impact_max REAL,
        required_crew INTEGER,
        required_water_l REAL,
        assumptions_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PROPOSED',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (prediction_id) REFERENCES predictions (prediction_id),
        FOREIGN KEY (ward_id) REFERENCES wards (id)
    );
    """)

    # 7. Learning Loop: Executed Field Actions (Approved and carried out actions)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS executed_actions (
        action_id TEXT PRIMARY KEY,
        recommendation_id TEXT,
        prediction_id TEXT,
        ward_id TEXT NOT NULL,
        intervention_type TEXT NOT NULL,
        approval_status TEXT NOT NULL,
        approved_by TEXT NOT NULL,
        approved_at TEXT,
        execution_status TEXT NOT NULL DEFAULT 'SCHEDULED',
        started_at TEXT,
        completed_at TEXT,
        actual_cost_inr REAL,
        actual_crew_used INTEGER,
        actual_water_used_l REAL,
        failure_reason TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (recommendation_id) REFERENCES recommendations (recommendation_id),
        FOREIGN KEY (prediction_id) REFERENCES predictions (prediction_id),
        FOREIGN KEY (ward_id) REFERENCES wards (id)
    );
    """)

    # 8. Learning Loop: Verified Municipal Outcomes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS verified_outcomes (
        outcome_id TEXT PRIMARY KEY,
        ward_id TEXT NOT NULL,
        prediction_id TEXT,
        action_id TEXT,
        measurement_date TEXT NOT NULL,
        measurement_window_hours INTEGER DEFAULT 24,
        hazard_type TEXT NOT NULL,
        hospital_heat_admissions INTEGER DEFAULT 0,
        mortality_count INTEGER DEFAULT 0,
        emergency_108_calls INTEGER DEFAULT 0,
        water_scarcity_complaints INTEGER DEFAULT 0,
        waterlogging_depth_cm REAL,
        data_source TEXT NOT NULL,
        provenance TEXT NOT NULL DEFAULT 'REAL',
        data_quality_score REAL DEFAULT 1.0,
        verification_notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (prediction_id) REFERENCES predictions (prediction_id),
        FOREIGN KEY (action_id) REFERENCES executed_actions (action_id),
        FOREIGN KEY (ward_id) REFERENCES wards (id)
    );
    """)

    # 9. Learning Loop: Impact Verifications (Before-After & Difference-in-Differences)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS impact_verifications (
        verification_id TEXT PRIMARY KEY,
        action_id TEXT NOT NULL,
        ward_id TEXT NOT NULL,
        control_ward_id TEXT,
        hazard_type TEXT NOT NULL,
        primary_metric TEXT NOT NULL,
        methodology TEXT NOT NULL,
        status TEXT NOT NULL,
        baseline_period TEXT,
        followup_period TEXT,
        baseline_value REAL,
        followup_value REAL,
        control_baseline_value REAL,
        control_followup_value REAL,
        observed_delta REAL,
        did_estimate REAL,
        expected_impact_nominal REAL,
        action_completed INTEGER NOT NULL,
        intended_outcome_observed INTEGER,
        provenance TEXT NOT NULL,
        confidence_score REAL NOT NULL,
        causal_claim_allowed INTEGER NOT NULL DEFAULT 0,
        uncertainty_json TEXT,
        explanation TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (action_id) REFERENCES executed_actions (action_id),
        FOREIGN KEY (ward_id) REFERENCES wards (id)
    );
    """)

    # 10. Learning Loop: Model Evaluations & Accuracy Tracking
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS model_evaluations (
        evaluation_id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        eval_window_days INTEGER DEFAULT 30,
        heat_metrics_json TEXT NOT NULL,
        waterlogging_metrics_json TEXT NOT NULL,
        water_shortage_metrics_json TEXT NOT NULL,
        overall_mae REAL,
        sample_count_real INTEGER NOT NULL,
        sample_count_excluded INTEGER NOT NULL,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 11. Learning Loop: Proposed Parameter Updates (Require Human Approval)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS proposed_parameter_updates (
        proposal_id TEXT PRIMARY KEY,
        evaluation_id TEXT NOT NULL,
        target_parameter_type TEXT NOT NULL,
        target_identifier TEXT NOT NULL,
        current_value REAL NOT NULL,
        proposed_value REAL NOT NULL,
        delta REAL NOT NULL,
        supporting_samples_count INTEGER NOT NULL,
        justification TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL',
        reviewed_by TEXT,
        reviewed_at TEXT,
        review_notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (evaluation_id) REFERENCES model_evaluations (evaluation_id)
    );
    """)

    # 12. Learning Loop: Immutable Model Versions & Parameter Audit Trail
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS model_versions (
        version_id TEXT PRIMARY KEY,
        version_number INTEGER NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 0,
        parameters_json TEXT NOT NULL,
        approved_by TEXT NOT NULL,
        approved_at TEXT NOT NULL,
        change_summary TEXT NOT NULL,
        proposal_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 13. Verified Impact Assessments
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS impact_assessments (
        assessment_id TEXT PRIMARY KEY,
        intervention_id TEXT NOT NULL,
        ward_id TEXT NOT NULL,
        intervention_type TEXT NOT NULL,
        execution_status TEXT NOT NULL DEFAULT 'COMPLETED',
        verification_status TEXT NOT NULL,
        provenance_mode TEXT NOT NULL,
        is_synthetic INTEGER NOT NULL DEFAULT 0,
        baseline_period_json TEXT NOT NULL,
        follow_up_period_json TEXT NOT NULL,
        indicators_json TEXT NOT NULL,
        calculated_changes_json TEXT NOT NULL,
        data_quality_warnings_json TEXT NOT NULL,
        attribution_disclaimer TEXT NOT NULL,
        summary_json TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 14. Impact Assessment Audit History
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS impact_assessment_history (
        history_id INTEGER PRIMARY KEY AUTOINCREMENT,
        assessment_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL,
        archived_at TEXT NOT NULL,
        change_reason TEXT,
        FOREIGN KEY (assessment_id) REFERENCES impact_assessments (assessment_id)
    );
    """)

    # 15. Action Centre: Intervention Evidence Verifications
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS action_verifications (
        verification_id TEXT PRIMARY KEY,
        action_id TEXT NOT NULL,
        ward_id TEXT NOT NULL,
        overall_status TEXT NOT NULL,
        checklist_json TEXT NOT NULL,
        verified_by TEXT NOT NULL,
        verified_at TEXT NOT NULL,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 16. Action Centre: Action Audit Trail & Event Log
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS action_audit_events (
        event_id TEXT PRIMARY KEY,
        action_id TEXT NOT NULL,
        ward_id TEXT,
        event_type TEXT NOT NULL,
        old_status TEXT,
        new_status TEXT,
        actor TEXT NOT NULL,
        reason TEXT,
        metadata_json TEXT,
        timestamp TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Indices for relational query performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_predictions_ward ON predictions (ward_id, timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recommendations_pred ON recommendations (prediction_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_rec ON executed_actions (recommendation_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_pred ON executed_actions (prediction_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_pred ON verified_outcomes (prediction_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_action ON verified_outcomes (action_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_ward_date ON verified_outcomes (ward_id, measurement_date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_verifications_action ON impact_verifications (action_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_verifications_ward ON impact_verifications (ward_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_time ON model_evaluations (timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposed_parameter_updates (status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_versions_active ON model_versions (is_active);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_impact_assessments_ward ON impact_assessments (ward_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_impact_assessments_interv ON impact_assessments (intervention_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_impact_history_assessment ON impact_assessment_history (assessment_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_action_verif_action ON action_verifications (action_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_action_id ON action_audit_events (action_id);")

    # 15. Groundwater Observations (CGWB In-situ Monitoring Telemetry)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS groundwater_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_row_id INTEGER,
        station_name TEXT NOT NULL,
        agency TEXT NOT NULL DEFAULT 'CGWB',
        state TEXT NOT NULL DEFAULT 'Gujarat',
        district TEXT NOT NULL,
        tehsil TEXT,
        block TEXT,
        village TEXT,
        latitude REAL,
        longitude REAL,
        observation_date TEXT NOT NULL,
        acquisition_timestamp TEXT NOT NULL,
        quarter_season TEXT,
        water_level_mbgl REAL,
        has_water_level INTEGER NOT NULL DEFAULT 1,
        is_historical INTEGER NOT NULL DEFAULT 1,
        provenance TEXT NOT NULL DEFAULT 'REAL_MANUAL_CGWB',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gw_station ON groundwater_observations (station_name);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gw_district ON groundwater_observations (district);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gw_date ON groundwater_observations (observation_date);")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_gw_unique ON groundwater_observations (station_name, acquisition_timestamp);")

    # 16. Reservoir Observations (CWC Weekly Storage Bulletins)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reservoir_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reservoir_name TEXT NOT NULL,
        state TEXT DEFAULT 'Gujarat',
        basin TEXT,
        district TEXT,
        observation_date TEXT NOT NULL,
        frl_meters REAL,
        total_capacity_bcm REAL,
        current_live_storage_bcm REAL,
        storage_percentage REAL,
        last_year_storage_bcm REAL,
        ten_year_avg_storage_bcm REAL,
        is_live INTEGER DEFAULT 0,
        is_stale INTEGER DEFAULT 0,
        data_freshness TEXT,
        source TEXT NOT NULL,
        provenance TEXT DEFAULT 'OFFICIAL_CWC_BULLETIN',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_res_name ON reservoir_observations (reservoir_name);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_res_date ON reservoir_observations (observation_date);")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_res_unique ON reservoir_observations (reservoir_name, observation_date);")

    conn.commit()
    conn.close()


def seed_baseline_data() -> None:
    """Seeds baseline wards, interventions catalog, and sample historical outcomes."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Seed all 48 Wards from GeoJSON if available, with core 10 having calibrated vulnerability
    cursor.execute("SELECT COUNT(*) as count FROM wards;")
    count = cursor.fetchone()["count"]
    if count < 48:
        # Seed core priority wards
        ahmedabad_wards = [
            ("W1", "Danilimda", 0.85, 0.75, 0.20, 0.92, 125000, 6.2),
            ("W2", "Behrampura", 0.80, 0.70, 0.18, 0.88, 110000, 5.4),
            ("W3", "Asarwa", 0.65, 0.60, 0.25, 0.78, 95000, 4.8),
            ("W4", "Bapunagar", 0.75, 0.65, 0.22, 0.84, 130000, 5.9),
            ("W5", "Khadia (Old City)", 0.40, 0.45, 0.35, 0.72, 85000, 3.2),
            ("W6", "Amraiwadi", 0.70, 0.68, 0.19, 0.81, 105000, 5.1),
            ("W7", "Vatva", 0.78, 0.72, 0.17, 0.86, 140000, 7.8),
            ("W8", "Sabarmati", 0.35, 0.35, 0.28, 0.55, 90000, 6.5),
            ("W9", "Maninagar", 0.30, 0.30, 0.30, 0.50, 115000, 5.0),
            ("W10", "Naroda", 0.60, 0.58, 0.21, 0.70, 100000, 6.8)
        ]
        cursor.executemany("""
        INSERT OR IGNORE INTO wards (id, name, slum_density, outdoor_labor_ratio, elderly_ratio, baseline_heat_risk, population, area_sq_km)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, ahmedabad_wards)

        # Seed remaining wards up to W48 from GeoJSON if present
        geojson_path = os.path.join(os.path.dirname(__file__), "data", "Ahmedabad_Wards.geojson")
        if os.path.exists(geojson_path):
            try:
                with open(geojson_path, "r", encoding="utf-8") as f:
                    geo = json.load(f)
                features = geo.get("features", [])
                for idx, feat in enumerate(features):
                    w_id = f"W{idx + 1}"
                    props = feat.get("properties", {})
                    name = props.get("Name", props.get("NAME", f"Ward {idx + 1}"))
                    cursor.execute("""
                    INSERT OR IGNORE INTO wards (id, name, slum_density, outdoor_labor_ratio, elderly_ratio, baseline_heat_risk, population, area_sq_km)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """, (w_id, name, 0.50, 0.50, 0.20, 0.60, 100000, 5.0))
            except Exception:
                pass

    # Check if interventions catalog already seeded
    cursor.execute("SELECT COUNT(*) as count FROM interventions;")
    if cursor.fetchone()["count"] == 0:
        interventions = [
            ("cooling_center", "Cooling Center Shelter", 50000, 4, 500, 85.0, 2, json.dumps({"slum_dwellers": 40, "outdoor_laborers": 20, "elderly_infants": 40})),
            ("hydration_kiosk", "Emergency Hydration Kiosk", 15000, 2, 1200, 45.0, 4, json.dumps({"slum_dwellers": 30, "outdoor_laborers": 60, "elderly_infants": 10})),
            ("shade_canopy", "Pop-up Bus Stop Shade Canopy", 25000, 3, 0, 35.0, 3, json.dumps({"slum_dwellers": 20, "outdoor_laborers": 70, "elderly_infants": 10})),
            ("cool_roof_coating", "Slum Cool Roof Painting", 35000, 5, 100, 65.0, 3, json.dumps({"slum_dwellers": 80, "outdoor_laborers": 0, "elderly_infants": 20})),
            ("water_tanker_dispatch", "Mobile Water Tanker Dispatch", 10000, 2, 5000, 50.0, 2, json.dumps({"slum_dwellers": 50, "outdoor_laborers": 30, "elderly_infants": 20}))
        ]
        cursor.executemany("""
        INSERT INTO interventions (id, name, cost_inr, crew_req, water_req_l, base_risk_reduction, max_per_ward, vulnerable_impact_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, interventions)

    # Check if sample historical outcome records seeded
    cursor.execute("SELECT COUNT(*) as count FROM outcome_records;")
    if cursor.fetchone()["count"] == 0:
        sample_outcomes = [
            ("2026-05-15", "W1", 14, 2, 8, 22, "AMC_HEALTH_SURVEILLANCE"),
            ("2026-05-15", "W2", 12, 1, 6, 18, "AMC_HEALTH_SURVEILLANCE"),
            ("2026-05-15", "W4", 10, 1, 5, 15, "AMC_HEALTH_SURVEILLANCE"),
            ("2026-05-15", "W7", 11, 2, 7, 20, "AMC_HEALTH_SURVEILLANCE"),
            ("2026-05-15", "W9", 2, 0, 1, 3, "AMC_HEALTH_SURVEILLANCE")
        ]
        cursor.executemany("""
        INSERT INTO outcome_records (record_date, ward_id, hospital_heat_admissions, mortality_count, emergency_108_calls, water_scarcity_complaints, reported_by)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """, sample_outcomes)

    # Check if initial baseline model version v1.0.0 is seeded
    cursor.execute("SELECT COUNT(*) as count FROM model_versions;")
    if cursor.fetchone()["count"] == 0:
        default_params = {
            "ward_vulnerability_offsets": {},
            "intervention_efficacy_multipliers": {
                "cooling_center": 1.0,
                "hydration_kiosk": 1.0,
                "shade_canopy": 1.0,
                "cool_roof_coating": 1.0,
                "heat_alert_outreach": 1.0,
                "drainage_inspection_clean": 1.0,
                "flood_barricade_warning": 1.0,
                "mobile_pumping": 1.0,
                "water_tanker_dispatch": 1.0,
                "piped_supply_priority": 1.0
            },
            "hazard_weights": {"heat": 0.50, "water": 0.50}
        }
        cursor.execute("""
        INSERT INTO model_versions (version_id, version_number, is_active, parameters_json, approved_by, approved_at, change_summary)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """, ("v1.0.0", 1, 1, json.dumps(default_params), "SYSTEM_INITIALIZATION", datetime.now(timezone.utc).isoformat(), "Initial baseline model version with uncalibrated prior parameters."))

    conn.commit()
    conn.close()


def get_all_wards() -> List[Dict[str, Any]]:
    """Returns all ward records as dictionaries."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM wards ORDER BY baseline_heat_risk DESC;")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_all_interventions() -> List[Dict[str, Any]]:
    """Returns the interventions catalog."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM interventions;")
    rows = []
    for r in cursor.fetchall():
        item = dict(r)
        item["vulnerable_impact"] = json.loads(item["vulnerable_impact_json"])
        del item["vulnerable_impact_json"]
        rows.append(item)
    conn.close()
    return rows


def insert_outcome_record(
    record_date: str,
    ward_id: str,
    hospital_admissions: int,
    mortality_count: int,
    emergency_108_calls: int,
    water_complaints: int,
    reported_by: str = "AMC_HEALTH_SURVEILLANCE"
) -> int:
    """Inserts a new ground-truth municipal outcome record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO outcome_records (record_date, ward_id, hospital_heat_admissions, mortality_count, emergency_108_calls, water_scarcity_complaints, reported_by)
    VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (record_date, ward_id, hospital_admissions, mortality_count, emergency_108_calls, water_complaints, reported_by))
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return record_id


class DuplicateAssessmentError(ValueError):
    """Raised when attempting to insert an assessment that already exists without explicit update."""
    pass


def _row_to_assessment_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Helper to convert a database row to an assessment dictionary with parsed JSON fields."""
    d = dict(row)
    d["is_synthetic"] = bool(d.get("is_synthetic", 0))
    for json_field, target_key in [
        ("baseline_period_json", "baseline_period"),
        ("follow_up_period_json", "follow_up_period"),
        ("indicators_json", "indicators"),
        ("calculated_changes_json", "calculated_changes"),
        ("data_quality_warnings_json", "data_quality_warnings"),
        ("summary_json", "summary"),
    ]:
        if json_field in d and d[json_field] is not None:
            try:
                d[target_key] = json.loads(d[json_field])
            except Exception:
                d[target_key] = {}
            del d[json_field]
    return d


def save_impact_assessment_record(
    record: Dict[str, Any],
    allow_update: bool = False,
    change_reason: Optional[str] = None
) -> Dict[str, Any]:
    """
    Saves an impact assessment to the baseline database.
    - Prevents accidental duplicates by checking assessment_id.
    - If assessment_id already exists and incoming payload is identical, returns existing record idempotently.
    - If assessment_id already exists and allow_update is False, raises DuplicateAssessmentError.
    - If allow_update is True, archives current version to impact_assessment_history and increments version.
    """
    assessment_id = record.get("assessment_id")
    if not assessment_id:
        raise ValueError("Cannot save assessment: 'assessment_id' is required.")

    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if record already exists
    cursor.execute("SELECT * FROM impact_assessments WHERE assessment_id = ?;", (assessment_id,))
    existing_row = cursor.fetchone()

    # Prepare serialized JSON fields
    indicators_val = record.get("indicators", record.get("results_by_indicator", {}))
    calculated_changes_val = record.get("calculated_changes", {})
    if not calculated_changes_val and isinstance(indicators_val, dict):
        calculated_changes_val = {
            k: {
                "difference": v.get("difference"),
                "percentage_change": v.get("percentage_change"),
                "unit": v.get("unit"),
                "is_improvement": v.get("is_improvement")
            }
            for k, v in indicators_val.items() if isinstance(v, dict)
        }

    baseline_period_json = json.dumps(record.get("baseline_period", {}), sort_keys=True)
    follow_up_period_json = json.dumps(record.get("follow_up_period", {}), sort_keys=True)
    indicators_json = json.dumps(indicators_val, sort_keys=True)
    calculated_changes_json = json.dumps(calculated_changes_val, sort_keys=True)
    data_quality_warnings_json = json.dumps(record.get("data_quality_warnings", []), sort_keys=True)
    summary_json = json.dumps(record.get("summary", {}), sort_keys=True)
    attribution_disclaimer = record.get("attribution_disclaimer", "")
    provenance_mode = record.get("provenance_mode", "MEASURED")
    is_synthetic = 1 if record.get("is_synthetic", False) else 0
    execution_status = record.get("execution_status", "COMPLETED")
    verification_status = record.get("verification_status", "VERIFIED")
    intervention_id = record.get("intervention_id", "")
    ward_id = record.get("ward_id", "")
    intervention_type = record.get("intervention_type", "")

    if existing_row:
        existing_dict = _row_to_assessment_dict(existing_row)

        # Idempotency check: compare core payload
        is_identical = (
            existing_row["intervention_id"] == intervention_id and
            existing_row["ward_id"] == ward_id and
            existing_row["intervention_type"] == intervention_type and
            existing_row["indicators_json"] == indicators_json and
            existing_row["calculated_changes_json"] == calculated_changes_json and
            existing_row["execution_status"] == execution_status
        )

        if is_identical:
            conn.close()
            existing_dict["save_status"] = "IDEMPOTENT_UNCHANGED"
            return existing_dict

        if not allow_update:
            conn.close()
            raise DuplicateAssessmentError(
                f"Assessment ID '{assessment_id}' already exists in database. "
                "Silently overwriting historical records is forbidden. "
                "To update or re-evaluate, specify allow_update=True."
            )

        # Archive existing version to audit history
        current_version = existing_row["version"]
        snapshot_json = json.dumps(dict(existing_row))
        cursor.execute("""
        INSERT INTO impact_assessment_history (assessment_id, version, snapshot_json, archived_at, change_reason)
        VALUES (?, ?, ?, ?, ?);
        """, (assessment_id, current_version, snapshot_json, now_iso, change_reason or "Updated via save_impact_assessment_record"))

        # Update current record with incremented version
        new_version = current_version + 1
        cursor.execute("""
        UPDATE impact_assessments
        SET intervention_id = ?,
            ward_id = ?,
            intervention_type = ?,
            execution_status = ?,
            verification_status = ?,
            provenance_mode = ?,
            is_synthetic = ?,
            baseline_period_json = ?,
            follow_up_period_json = ?,
            indicators_json = ?,
            calculated_changes_json = ?,
            data_quality_warnings_json = ?,
            attribution_disclaimer = ?,
            summary_json = ?,
            version = ?,
            updated_at = ?
        WHERE assessment_id = ?;
        """, (
            intervention_id, ward_id, intervention_type, execution_status, verification_status,
            provenance_mode, is_synthetic, baseline_period_json, follow_up_period_json,
            indicators_json, calculated_changes_json, data_quality_warnings_json,
            attribution_disclaimer, summary_json, new_version, now_iso, assessment_id
        ))
        conn.commit()
        cursor.execute("SELECT * FROM impact_assessments WHERE assessment_id = ?;", (assessment_id,))
        updated_row = cursor.fetchone()
        conn.close()
        res = _row_to_assessment_dict(updated_row)
        res["save_status"] = "UPDATED_AND_ARCHIVED"
        return res

    # Insert new record
    created_at = record.get("created_at") or now_iso
    updated_at = now_iso
    cursor.execute("""
    INSERT INTO impact_assessments (
        assessment_id, intervention_id, ward_id, intervention_type, execution_status,
        verification_status, provenance_mode, is_synthetic, baseline_period_json,
        follow_up_period_json, indicators_json, calculated_changes_json,
        data_quality_warnings_json, attribution_disclaimer, summary_json,
        version, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?);
    """, (
        assessment_id, intervention_id, ward_id, intervention_type, execution_status,
        verification_status, provenance_mode, is_synthetic, baseline_period_json,
        follow_up_period_json, indicators_json, calculated_changes_json,
        data_quality_warnings_json, attribution_disclaimer, summary_json,
        created_at, updated_at
    ))
    conn.commit()
    cursor.execute("SELECT * FROM impact_assessments WHERE assessment_id = ?;", (assessment_id,))
    new_row = cursor.fetchone()
    conn.close()
    res = _row_to_assessment_dict(new_row)
    res["save_status"] = "CREATED"
    return res


def get_impact_assessment_by_id(assessment_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves an impact assessment record by its unique ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM impact_assessments WHERE assessment_id = ?;", (assessment_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_assessment_dict(row)


def get_all_impact_assessments(
    ward_id: Optional[str] = None,
    intervention_id: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Retrieves impact assessments with optional filtering by ward or intervention."""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM impact_assessments WHERE 1=1"
    params: List[Any] = []

    if ward_id:
        query += " AND ward_id = ?"
        params.append(ward_id.strip().upper())
    if intervention_id:
        query += " AND intervention_id = ?"
        params.append(intervention_id.strip())

    query += " ORDER BY updated_at DESC LIMIT ?;"
    params.append(limit)

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    return [_row_to_assessment_dict(r) for r in rows]


def get_impact_assessment_history(assessment_id: str) -> List[Dict[str, Any]]:
    """Retrieves the complete audit history of all previous versions for an assessment ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT history_id, assessment_id, version, snapshot_json, archived_at, change_reason
    FROM impact_assessment_history
    WHERE assessment_id = ?
    ORDER BY version ASC;
    """, (assessment_id,))
    rows = cursor.fetchall()
    conn.close()

    history: List[Dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        try:
            item["snapshot"] = json.loads(item["snapshot_json"])
        except Exception:
            item["snapshot"] = {}
        del item["snapshot_json"]
        history.append(item)
    return history


def record_action_verification(data: Dict[str, Any]) -> Dict[str, Any]:
    """Records an intervention evidence verification in SQLite."""
    conn = get_db_connection()
    cursor = conn.cursor()
    verification_id = data.get("verification_id") or f"VERIF-{uuid.uuid4().hex[:8].upper()}"
    checklist_json = json.dumps(data.get("checklist", []))
    now = datetime.now(timezone.utc).isoformat()
    verified_at = data.get("verified_at") or now

    cursor.execute("""
    INSERT OR REPLACE INTO action_verifications (
        verification_id, action_id, ward_id, overall_status, checklist_json, verified_by, verified_at, notes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        verification_id,
        data["action_id"],
        data["ward_id"],
        data["overall_status"],
        checklist_json,
        data.get("verified_by", "Municipal Incident Commander"),
        verified_at,
        data.get("notes"),
    ))
    conn.commit()
    conn.close()

    result = dict(data)
    result["verification_id"] = verification_id
    result["verified_at"] = verified_at
    return result


def get_action_verification(action_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves the latest verification report for an action ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT verification_id, action_id, ward_id, overall_status, checklist_json, verified_by, verified_at, notes, created_at
    FROM action_verifications
    WHERE action_id = ?
    ORDER BY verified_at DESC LIMIT 1;
    """, (action_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    res = dict(row)
    try:
        res["checklist"] = json.loads(res["checklist_json"])
    except Exception:
        res["checklist"] = []
    del res["checklist_json"]
    return res


def record_action_audit_event(
    action_id: str,
    event_type: str,
    actor: str,
    ward_id: Optional[str] = None,
    old_status: Optional[str] = None,
    new_status: Optional[str] = None,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Records an immutable audit event for an action (creation, verification, status change, dispatch, blocker)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(metadata or {})

    cursor.execute("""
    INSERT INTO action_audit_events (
        event_id, action_id, ward_id, event_type, old_status, new_status, actor, reason, metadata_json, timestamp
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        event_id, action_id, ward_id, event_type, old_status, new_status, actor, reason, meta_json, ts
    ))
    conn.commit()
    conn.close()

    return {
        "event_id": event_id,
        "action_id": action_id,
        "ward_id": ward_id,
        "event_type": event_type,
        "old_status": old_status,
        "new_status": new_status,
        "actor": actor,
        "reason": reason,
        "metadata": metadata or {},
        "timestamp": ts,
    }


def list_action_audit_events(action_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Retrieves immutable audit events, optionally filtered by action_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if action_id:
        cursor.execute("""
        SELECT event_id, action_id, ward_id, event_type, old_status, new_status, actor, reason, metadata_json, timestamp, created_at
        FROM action_audit_events
        WHERE action_id = ?
        ORDER BY timestamp ASC, created_at ASC LIMIT ?;
        """, (action_id, limit))
    else:
        cursor.execute("""
        SELECT event_id, action_id, ward_id, event_type, old_status, new_status, actor, reason, metadata_json, timestamp, created_at
        FROM action_audit_events
        ORDER BY timestamp DESC, created_at DESC LIMIT ?;
        """, (limit,))
    rows = cursor.fetchall()
    conn.close()

    results = []
    for r in rows:
        item = dict(r)
        try:
            item["metadata"] = json.loads(item["metadata_json"])
        except Exception:
            item["metadata"] = {}
        del item["metadata_json"]
        results.append(item)
    return results


# -------------------------------------------------------------
# GROUNDWATER DATA OPERATIONS (CGWB IN-SITU MONITORING)
# -------------------------------------------------------------

def insert_groundwater_observations(records: List[Dict[str, Any]]) -> Tuple[int, int]:
    """
    Inserts a list of normalized groundwater observation dictionaries into SQLite.
    Skips duplicates using (station_name, acquisition_timestamp) unique constraint.
    Returns (inserted_count, skipped_count).
    """
    if not records:
        return 0, 0

    conn = get_db_connection()
    cursor = conn.cursor()

    insert_sql = """
    INSERT OR IGNORE INTO groundwater_observations (
        source_row_id, station_name, agency, state, district,
        tehsil, block, village, latitude, longitude,
        observation_date, acquisition_timestamp, quarter_season,
        water_level_mbgl, has_water_level, is_historical, provenance
    ) VALUES (
        ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?,
        ?, ?, ?,
        ?, ?, ?, ?
    );
    """

    data_tuples = [
        (
            r.get("source_row_id"),
            r["station_name"],
            r.get("agency", "CGWB"),
            r.get("state", "Gujarat"),
            r.get("district", ""),
            r.get("tehsil"),
            r.get("block"),
            r.get("village"),
            r.get("latitude"),
            r.get("longitude"),
            r["observation_date"],
            r.get("acquisition_timestamp", f"{r['observation_date']}T00:00:00"),
            r.get("quarter_season", "UNKNOWN"),
            r.get("water_level_mbgl"),
            1 if r.get("has_water_level", True) else 0,
            1 if r.get("is_historical", True) else 0,
            r.get("provenance", "REAL_MANUAL_CGWB")
        )
        for r in records
    ]

    initial_count = cursor.execute("SELECT COUNT(*) FROM groundwater_observations;").fetchone()[0]
    cursor.executemany(insert_sql, data_tuples)
    conn.commit()
    final_count = cursor.execute("SELECT COUNT(*) FROM groundwater_observations;").fetchone()[0]
    conn.close()

    inserted = final_count - initial_count
    skipped = len(records) - inserted
    return inserted, skipped


def get_groundwater_stations(district: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns unique monitoring stations with geographic coordinates, latest reading,
    monitoring date, and total observation count.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
    SELECT 
        station_name,
        district,
        tehsil,
        block,
        village,
        latitude,
        longitude,
        agency,
        COUNT(*) as total_observations,
        SUM(CASE WHEN has_water_level = 1 THEN 1 ELSE 0 END) as valid_readings_count,
        MIN(observation_date) as earliest_date,
        MAX(observation_date) as latest_date
    FROM groundwater_observations
    WHERE 1=1
    """
    params: List[Any] = []
    if district:
        query += " AND LOWER(district) = LOWER(?)"
        params.append(district.strip())

    query += " GROUP BY station_name ORDER BY district ASC, station_name ASC;"
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()

    stations = []
    for r in rows:
        d = dict(r)
        # Fetch latest reading value specifically
        cursor.execute("""
            SELECT water_level_mbgl, observation_date, quarter_season 
            FROM groundwater_observations 
            WHERE station_name = ? AND has_water_level = 1 
            ORDER BY observation_date DESC LIMIT 1;
        """, (d["station_name"],))
        latest_row = cursor.fetchone()
        if latest_row:
            d["latest_water_level_mbgl"] = latest_row["water_level_mbgl"]
            d["latest_quarter_season"] = latest_row["quarter_season"]
        else:
            d["latest_water_level_mbgl"] = None
            d["latest_quarter_season"] = None
        stations.append(d)

    conn.close()
    return stations


def get_groundwater_observations(
    station_name: Optional[str] = None,
    district: Optional[str] = None,
    season: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Retrieves filtered groundwater observation history records.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM groundwater_observations WHERE 1=1"
    params: List[Any] = []

    if station_name:
        query += " AND LOWER(station_name) = LOWER(?)"
        params.append(station_name.strip())
    if district:
        query += " AND LOWER(district) = LOWER(?)"
        params.append(district.strip())
    if season:
        query += " AND UPPER(quarter_season) = UPPER(?)"
        params.append(season.strip())
    if start_date:
        query += " AND observation_date >= ?"
        params.append(start_date.strip())
    if end_date:
        query += " AND observation_date <= ?"
        params.append(end_date.strip())

    query += " ORDER BY observation_date DESC, station_name ASC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    cursor.execute(query, tuple(params))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for r in rows:
        r["has_water_level"] = bool(r.get("has_water_level", 1))
        r["is_historical"] = bool(r.get("is_historical", 1))

    return rows


def get_groundwater_trends(
    district: Optional[str] = "Ahmedabad",
    station_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculates empirical water table depth statistics, seasonal recharge/depletion,
    and multi-year aquifer drawdown trends.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    where_clauses = ["has_water_level = 1"]
    params: List[Any] = []

    if station_name:
        where_clauses.append("LOWER(station_name) = LOWER(?)")
        params.append(station_name.strip())
    elif district:
        where_clauses.append("LOWER(district) = LOWER(?)")
        params.append(district.strip())

    where_sql = " AND ".join(where_clauses)

    # Basic stats
    cursor.execute(f"""
        SELECT 
            COUNT(*) as reading_count,
            COUNT(DISTINCT station_name) as station_count,
            MIN(water_level_mbgl) as min_depth,
            MAX(water_level_mbgl) as max_depth,
            AVG(water_level_mbgl) as avg_depth,
            MIN(observation_date) as earliest_date,
            MAX(observation_date) as latest_date
        FROM groundwater_observations
        WHERE {where_sql};
    """, tuple(params))
    base_stats = dict(cursor.fetchone() or {})

    if not base_stats or base_stats.get("reading_count", 0) == 0:
        conn.close()
        return {
            "status": "NO_OBSERVATIONS",
            "scope": {"district": district, "station_name": station_name},
            "reading_count": 0,
            "message": "No validated groundwater observations found for specified criteria."
        }

    # Seasonal breakdown
    cursor.execute(f"""
        SELECT 
            quarter_season,
            COUNT(*) as count,
            AVG(water_level_mbgl) as avg_mbgl
        FROM groundwater_observations
        WHERE {where_sql}
        GROUP BY quarter_season;
    """, tuple(params))
    seasonal_rows = cursor.fetchall()
    seasonal_averages = {r["quarter_season"]: round(r["avg_mbgl"], 2) for r in seasonal_rows}

    # Annual breakdown
    cursor.execute(f"""
        SELECT 
            SUBSTR(observation_date, 1, 4) as obs_year,
            COUNT(*) as count,
            AVG(water_level_mbgl) as avg_mbgl
        FROM groundwater_observations
        WHERE {where_sql}
        GROUP BY obs_year
        ORDER BY obs_year ASC;
    """, tuple(params))
    annual_rows = cursor.fetchall()
    annual_series = [
        {
            "year": r["obs_year"],
            "count": r["count"],
            "avg_depth_mbgl": round(r["avg_mbgl"], 2)
        }
        for r in annual_rows
    ]

    # Annual decline / recovery rate calculation
    annual_decline_rate = 0.0
    if len(annual_series) >= 2:
        y_first = annual_series[0]
        y_last = annual_series[-1]
        try:
            year_gap = int(y_last["year"]) - int(y_first["year"])
            if year_gap > 0:
                annual_decline_rate = round((y_last["avg_depth_mbgl"] - y_first["avg_depth_mbgl"]) / year_gap, 3)
        except Exception:
            annual_decline_rate = 0.0

    avg_mbgl = round(base_stats.get("avg_depth", 0.0) or 0.0, 2)
    pre_monsoon = seasonal_averages.get("PRE_MONSOON")
    post_monsoon = seasonal_averages.get("POST_MONSOON")
    seasonal_recharge_m = round(pre_monsoon - post_monsoon, 2) if (pre_monsoon is not None and post_monsoon is not None) else None

    # Stress Tier Classification
    if avg_mbgl > 35.0 or annual_decline_rate > 1.5:
        stress_tier = "CRITICAL_AQUIFER_DEPLETION"
        stress_color = "#EF4444"
        risk_description = "Severe regional water table depression. Deep borewells under severe draft stress."
    elif avg_mbgl > 20.0 or annual_decline_rate > 0.5:
        stress_tier = "HIGH_AQUIFER_STRESS"
        stress_color = "#F59E0B"
        risk_description = "Significant water table drawdown. Buffer capacity during prolonged summer heatwaves is constrained."
    elif avg_mbgl > 10.0:
        stress_tier = "MODERATE_WATER_TABLE"
        stress_color = "#3B82F6"
        risk_description = "Intermediate groundwater depth with seasonal recharge responsiveness."
    else:
        stress_tier = "SHALLOW_WATER_TABLE"
        stress_color = "#10B981"
        risk_description = "Shallow water table with active monsoon recharge; low drought vulnerability."

    conn.close()

    return {
        "status": "SUCCESS",
        "scope": {
            "target": station_name if station_name else (district or "ALL_GUJARAT"),
            "is_station_specific": bool(station_name),
            "district": district
        },
        "statistics": {
            "total_observations": base_stats.get("reading_count", 0),
            "station_count": base_stats.get("station_count", 0),
            "earliest_observation": base_stats.get("earliest_date"),
            "latest_observation": base_stats.get("latest_date"),
            "average_depth_mbgl": avg_mbgl,
            "shallowest_depth_mbgl": round(base_stats.get("min_depth", 0.0) or 0.0, 2),
            "deepest_depth_mbgl": round(base_stats.get("max_depth", 0.0) or 0.0, 2),
            "seasonal_recharge_potential_m": seasonal_recharge_m,
            "annual_decline_rate_m_per_year": annual_decline_rate
        },
        "aquifer_stress_assessment": {
            "tier": stress_tier,
            "color": stress_color,
            "summary": risk_description
        },
        "seasonal_averages_mbgl": seasonal_averages,
        "annual_trend_series": annual_series,
        "scientific_integrity": {
            "source_agency": "Central Ground Water Board (CGWB)",
            "measurement_mode": "In-situ Quarterly Manual Telemetry (Piezometers & Dugwells)",
            "provenance": "REAL_MANUAL_CGWB",
            "spatial_disclaimer": "Measurements reflect discrete regional aquifer observation wells and do not measure localized piped municipal supply at ward level."
        }
    }


def seed_groundwater_data(csv_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Seeds groundwater observations into SQLite from raw CSV if table is currently empty.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM groundwater_observations;")
    existing_count = cursor.fetchone()[0]
    conn.close()

    if existing_count > 0:
        return {
            "status": "ALREADY_SEEDED",
            "existing_records": existing_count,
            "message": "Groundwater table already populated. Skipping duplicate seed."
        }

    from backend.data_sources.groundwater_parser import GroundwaterParser
    parser = GroundwaterParser(csv_path)
    res = parser.parse()

    if not res.get("success"):
        return {
            "status": "PARSE_ERROR",
            "error": res.get("error", "Unknown parse error")
        }

    inserted, skipped = insert_groundwater_observations(res["valid_records"])
    return {
        "status": "SUCCESS_SEEDED",
        "total_parsed": res["valid_records_count"],
        "inserted_records": inserted,
        "skipped_duplicates": skipped,
        "unique_stations": res["stations_count"]
    }


# -------------------------------------------------------------
# RESERVOIR DATA OPERATIONS (CWC WEEKLY STORAGE BULLETINS)
# -------------------------------------------------------------

def insert_reservoir_observations(records: List[Dict[str, Any]]) -> Tuple[int, int]:
    """
    Inserts a list of normalized reservoir observation dictionaries into SQLite.
    Skips duplicates using (reservoir_name, observation_date) unique constraint.
    Returns (inserted_count, skipped_count).
    """
    if not records:
        return 0, 0

    conn = get_db_connection()
    cursor = conn.cursor()

    insert_sql = """
    INSERT OR IGNORE INTO reservoir_observations (
        reservoir_name, state, basin, district, observation_date,
        frl_meters, total_capacity_bcm, current_live_storage_bcm,
        storage_percentage, last_year_storage_bcm, ten_year_avg_storage_bcm,
        is_live, is_stale, data_freshness, source, provenance
    ) VALUES (
        ?, ?, ?, ?, ?,
        ?, ?, ?,
        ?, ?, ?,
        ?, ?, ?, ?, ?
    );
    """

    data_tuples = [
        (
            r["reservoir_name"],
            r.get("state", "Gujarat"),
            r.get("basin"),
            r.get("district"),
            r["observation_date"],
            r.get("frl_meters"),
            r.get("total_capacity_bcm"),
            r.get("current_live_storage_bcm"),
            r.get("storage_percentage"),
            r.get("last_year_storage_bcm"),
            r.get("ten_year_avg_storage_bcm"),
            0,  # is_live: Never present weekly bulletin or historical data as live telemetry
            1 if r.get("is_stale", False) else 0,
            r.get("data_freshness", "VERIFIED_OBSERVATION"),
            r.get("source", "Central Water Commission (CWC) Weekly Reservoir Storage Bulletin"),
            r.get("provenance", "OFFICIAL_CWC_BULLETIN")
        )
        for r in records
    ]

    initial_count = cursor.execute("SELECT COUNT(*) FROM reservoir_observations;").fetchone()[0]
    cursor.executemany(insert_sql, data_tuples)
    conn.commit()
    final_count = cursor.execute("SELECT COUNT(*) FROM reservoir_observations;").fetchone()[0]
    conn.close()

    inserted = final_count - initial_count
    skipped = len(records) - inserted
    return inserted, skipped


def get_reservoir_observations(
    reservoir_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Retrieves filtered reservoir observations, ordered by observation date descending.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    clauses = []
    params: List[Any] = []

    if reservoir_name:
        clauses.append("LOWER(reservoir_name) = ?")
        params.append(reservoir_name.strip().lower())

    if start_date:
        clauses.append("observation_date >= ?")
        params.append(start_date.strip())

    if end_date:
        clauses.append("observation_date <= ?")
        params.append(end_date.strip())

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
    SELECT 
        id, reservoir_name, state, basin, district, observation_date,
        frl_meters, total_capacity_bcm, current_live_storage_bcm,
        storage_percentage, last_year_storage_bcm, ten_year_avg_storage_bcm,
        is_live, is_stale, data_freshness, source, provenance, created_at
    FROM reservoir_observations
    {where_sql}
    ORDER BY observation_date DESC, reservoir_name ASC
    LIMIT ? OFFSET ?;
    """
    params.extend([max(1, limit), max(0, offset)])

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return [dict(r) for r in rows]


def get_latest_reservoir_observations(
    reservoir_names: Optional[List[str]] = None,
    max_age_days: int = 30
) -> List[Dict[str, Any]]:
    """
    Returns the most recent valid observation for each monitored reservoir.
    Recalculates staleness dynamically against the observation date.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
    SELECT r1.*
    FROM reservoir_observations r1
    INNER JOIN (
        SELECT reservoir_name, MAX(observation_date) as max_date
        FROM reservoir_observations
        GROUP BY reservoir_name
    ) r2 ON r1.reservoir_name = r2.reservoir_name AND r1.observation_date = r2.max_date
    ORDER BY r1.reservoir_name ASC;
    """

    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    today_dt = datetime.now().date()
    results = []

    for r in rows:
        item = dict(r)
        # Evaluate staleness
        try:
            obs_dt = datetime.strptime(item["observation_date"], "%Y-%m-%d").date()
            age_days = (today_dt - obs_dt).days
        except Exception:
            age_days = 9999

        is_stale = age_days > max_age_days
        item["is_stale"] = 1 if is_stale else 0
        item["is_live"] = 0  # Never live
        item["observation_age_days"] = age_days
        if is_stale:
            item["data_freshness"] = "HISTORICAL_STALE"
        elif age_days <= 7:
            item["data_freshness"] = "RECENT_WEEKLY_BULLETIN"
        else:
            item["data_freshness"] = "VERIFIED_OBSERVATION"

        if reservoir_names:
            normalized_targets = [n.strip().lower() for n in reservoir_names]
            if item["reservoir_name"].lower() in normalized_targets:
                results.append(item)
        else:
            results.append(item)

    return results


def get_ahmedabad_bulk_reservoir_summary(max_age_days: int = 30) -> Dict[str, Any]:
    """
    Calculates verified bulk reservoir storage for Ahmedabad Municipal Corporation (AMC).
    Combines Sardar Sarovar (Narmada Canal lifeline, ~80% supply weight) and
    Dharoi Reservoir (Sabarmati River lifeline, ~20% supply weight).
    Guarantees that historical or stale data is NEVER presented as live.
    """
    latest_records = get_latest_reservoir_observations(
        reservoir_names=["Sardar Sarovar", "Dharoi"],
        max_age_days=max_age_days
    )

    sardar = next((r for r in latest_records if "sardar" in r["reservoir_name"].lower()), None)
    dharoi = next((r for r in latest_records if "dharoi" in r["reservoir_name"].lower()), None)

    if not sardar and not dharoi:
        return {
            "status": "UNAVAILABLE",
            "message": "No verified reservoir observations found for Sardar Sarovar or Dharoi in database.",
            "composite_storage_pct": None,
            "has_measured_data": False,
            "is_live": False,
            "is_stale": True,
            "data_freshness": "NO_DATA",
            "disclaimer": "Reservoir observations missing from baseline database. Requires official CWC bulletin import."
        }

    # Extract individual percentages
    s_pct = sardar["storage_percentage"] if sardar else None
    d_pct = dharoi["storage_percentage"] if dharoi else None

    # Calculate supply-weighted composite percentage
    # Standard AMC water supply allocation: Narmada Main Canal (~80%), Sabarmati/Dharoi (~20%)
    if s_pct is not None and d_pct is not None:
        composite_pct = round((0.80 * s_pct) + (0.20 * d_pct), 1)
        s_cap = sardar.get("total_capacity_bcm") or 0.0
        d_cap = dharoi.get("total_capacity_bcm") or 0.0
        s_stor = sardar.get("current_live_storage_bcm") or 0.0
        d_stor = dharoi.get("current_live_storage_bcm") or 0.0
        total_cap = s_cap + d_cap
        total_stor = s_stor + d_stor
        cap_weighted_pct = round((total_stor / total_cap * 100.0), 1) if total_cap > 0 else composite_pct
    elif s_pct is not None:
        composite_pct = round(s_pct, 1)
        cap_weighted_pct = composite_pct
    else:
        composite_pct = round(d_pct, 1)
        cap_weighted_pct = composite_pct

    any_stale = (sardar.get("is_stale", 0) == 1 if sardar else True) or (dharoi.get("is_stale", 0) == 1 if dharoi else True)
    latest_obs_date = max([r["observation_date"] for r in (sardar, dharoi) if r is not None])

    freshness_status = "HISTORICAL_STALE" if any_stale else "RECENT_VERIFIED_OBSERVATION"

    return {
        "status": "SUCCESS",
        "city": "Ahmedabad",
        "composite_storage_pct": composite_pct,
        "capacity_weighted_storage_pct": cap_weighted_pct,
        "supply_weighting_rule": "80% Sardar Sarovar (Narmada Canal Main Lifeline) + 20% Dharoi (Sabarmati)",
        "has_measured_data": True,
        "is_live": False,  # CRITICAL: Official CWC bulletins are verified observational reports, not live SCADA telemetry
        "is_stale": any_stale,
        "data_freshness": freshness_status,
        "latest_observation_date": latest_obs_date,
        "reservoirs": {
            "sardar_sarovar": sardar,
            "dharoi": dharoi
        },
        "source": "Central Water Commission (CWC) Weekly Reservoir Storage Bulletin / Gujarat NWRWS",
        "provenance": "OFFICIAL_CWC_BULLETIN",
        "spatial_disclaimer": "Reservoir metrics reflect bulk surface water availability in major upstream storage reservoirs supplying Ahmedabad; not municipal distribution pipe pressure."
    }


def seed_reservoir_data(csv_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Seeds reservoir observations into SQLite from raw CSV if table is currently empty.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM reservoir_observations;")
    existing_count = cursor.fetchone()[0]
    conn.close()

    if existing_count > 0:
        return {
            "status": "ALREADY_SEEDED",
            "existing_records": existing_count,
            "message": "Reservoir observations table already populated. Skipping duplicate seed."
        }

    from backend.data_sources.reservoir_parser import ReservoirParser
    parser = ReservoirParser(csv_path)
    res = parser.parse()

    if not res.get("success"):
        return {
            "status": "PARSE_ERROR",
            "error": res.get("error", "Unknown parse error")
        }

    inserted, skipped = insert_reservoir_observations(res["valid_records"])
    return {
        "status": "SUCCESS_SEEDED",
        "total_parsed": res["valid_records_count"],
        "inserted_records": inserted,
        "skipped_duplicates": skipped,
        "unique_reservoirs": res["reservoirs_count"]
    }


# Auto-initialize and seed when module loaded
init_db()
seed_baseline_data()
seed_groundwater_data()
seed_reservoir_data()



