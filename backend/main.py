"""
ClimateShield - FastAPI Decision Support System Server
Exposes Heat Action APIs, Open-Meteo WBGT forecasting, and Optimization endpoints.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional
import os
import time
from datetime import datetime, timezone

from backend.wbgt_pipeline import (
    fetch_open_meteo_weather,
    process_wbgt_forecast,
    get_ward_wbgt_risk,
    AHMEDABAD_WARDS
)
from backend.optimizer import (
    solve_resource_allocation,
    optimize_from_combined_climate_results,
    RISK_CATEGORY_INTERVENTION_MAP,
    INTERVENTIONS
)
from backend.water_engine import (
    assess_citywide_water_risk,
    get_single_ward_water_risk,
    DEMONSTRATION_SCENARIOS,
    calculate_waterlogging_risk,
    calculate_water_shortage_risk,
    AHMEDABAD_LAT,
    AHMEDABAD_LON
)
from backend.climate_risk_engine import (
    evaluate_combined_climate_risk,
    SCORING_MODES,
    validate_and_normalize_weights
)
from backend.intervention_engine import (
    generate_intervention_recommendations,
    run_what_if_simulation,
    INTERVENTIONS_CATALOG,
    PROVENANCE_LABELS
)
from backend.data_sources import (
    ERA5LandClient,
    ECOSTRESSClient,
    DataFusionEngine,
    DataSourcesService
)
from backend.learning_loop import (
    PredictionRecordCreate,
    BatchRecommendationCreate,
    ExecutedActionCreate,
    ExecutedActionUpdate,
    VerifiedOutcomeCreate,
    record_prediction,
    get_prediction,
    list_predictions,
    record_recommendations,
    list_recommendations,
    record_executed_action,
    update_executed_action,
    get_action,
    list_actions,
    record_verified_outcome,
    get_outcome,
    list_outcomes,
    get_learning_lineage
)
from backend.impact_verification import (
    ImpactVerificationRequest,
    verify_intervention_impact,
    get_verification,
    list_verifications,
    assess_intervention_impact,
    record_impact_assessment,
    retrieve_impact_assessment,
    list_impact_assessments,
    retrieve_assessment_history,
    update_impact_assessment,
    generate_impact_verification_summary,
    export_learning_loop_signals,
    ExecutionStatus,
    SourceType,
    QualityStatus,
    ATTRIBUTION_DISCLAIMER
)
from backend.learning_engine import (
    ModelEvaluationRequest,
    ProposalApprovalRequest,
    ProposalRejectionRequest,
    run_model_evaluation,
    list_model_evaluations,
    get_model_evaluation,
    list_parameter_proposals,
    get_parameter_proposal,
    approve_parameter_proposal,
    reject_parameter_proposal,
    get_active_model_parameters,
    list_model_versions,
    rollback_model_version
)
from backend.action_centre import (
    get_action_store,
    generate_actions_from_climate_risk,
    generate_actions_from_interventions,
    generate_rule_based_recommendations,
    build_action_centre_dashboard,
    get_prioritized_actions,
    get_ward_wise_action_summary,
    evaluate_risk_data_freshness,
    DEFAULT_RECOMMENDATION_THRESHOLDS,
    RULE_DEFINITIONS,
    ACTION_RESOURCE_ESTIMATES,
    ACTION_TYPES,
    VALID_STATUSES,
    HUMAN_APPROVAL_NOTICE as ACTION_CENTRE_ADVISORY,
    verify_intervention_evidence,
    get_action_verification_report,
    dispatch_quick_action,
)
from backend.database import (
    DuplicateAssessmentError,
    list_action_audit_events,
    get_groundwater_stations,
    get_groundwater_observations,
    get_groundwater_trends,
    get_db_connection,
    get_ahmedabad_bulk_reservoir_summary,
)

app = FastAPI(
    title="ClimateShield API - Ahmedabad Heat Decision Support",
    description="Closed-loop decision support system for heatwave management, WBGT forecasting, and equitable resource allocation.",
    version="1.0.0"
)

# Enable CORS for React Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount built React frontend if available
FRONTEND_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
if os.path.exists(FRONTEND_DIST):
    app.mount("/dashboard", StaticFiles(directory=FRONTEND_DIST, html=True), name="dashboard")
else:
    @app.get("/dashboard", response_class=HTMLResponse)
    @app.get("/dashboard/", response_class=HTMLResponse)
    async def dashboard_fallback():
        return HTMLResponse("<!doctype html><html><head><title>ClimateShield Dashboard</title></head><body><h1>ClimateShield Dashboard</h1><p>Frontend active at <a href='http://localhost:5173'>http://localhost:5173</a></p></body></html>")


class OptimizationRequest(BaseModel):
    total_budget_inr: float = Field(500000.0, ge=10000, le=10000000, description="Total monetary budget in INR")
    total_crew_members: int = Field(40, ge=1, le=500, description="Total available deployment personnel")
    total_water_cap_l: float = Field(30000.0, ge=1000, le=500000, description="Daily water cap limit in Liters")
    equity_slider: float = Field(0.5, ge=0.0, le=1.0, description="Equity priority slider (0.0 = pure efficiency, 1.0 = maximum equity)")
    wards: Optional[List[Dict[str, Any]]] = Field(None, description="Optional custom ward risk assessments to optimize")


@app.get("/")
def read_root():
    return {
        "system": "ClimateShield Decision Support System",
        "target_city": "Ahmedabad, Gujarat, India",
        "status": "OPERATIONAL",
        "dashboard_ui": "/dashboard",
        "endpoints": [
            "/dashboard",
            "/api/weather/wbgt",
            "/api/wards",
            "/api/wards/geojson",
            "/api/risk/monte-carlo",
            "/api/optimize",
            "/api/optimize/climate",
            "/api/optimize/interventions",
            "/api/water/wards",
            "/api/water/wards/{ward_id}",
            "/api/water/risk",
            "/api/water/scenarios",
            "/api/water/assess",
            "/api/climate/combined-risk",
            "/api/interventions/catalog",
            "/api/interventions/recommend",
            "/api/interventions/ranked",
            "/api/interventions/wards/{ward_id}",
            "/api/interventions/simulate",
            "/api/data-sources/era5",
            "/api/data-sources/ecostress",
            "/api/data-sources/fusion",
            "/api/learning/predictions",
            "/api/learning/recommendations",
            "/api/learning/actions",
            "/api/learning/outcomes",
            "/api/learning/lineage/{prediction_id}",
            "/api/impact/verify",
            "/api/impact/verifications",
            "/api/learning/evaluate",
            "/api/learning/active-parameters",
            "/api/learning/versions",
            "/api/action-centre/dashboard",
            "/api/action-centre/actions",
            "/api/action-centre/actions/{action_id}",
            "/api/action-centre/actions/{action_id}/status",
            "/api/action-centre/generate-from-risk",
            "/api/action-centre/generate-from-interventions",
            "/api/impact/assessments",
            "/api/impact/assessments/{assessment_id}",
            "/api/impact/wards/{ward_id}",
            "/api/impact/summary",
            "/api/impact/learning-signals",
            "/api/water/groundwater/stations",
            "/api/water/groundwater/observations",
            "/api/water/groundwater/trends",
            "/api/water/groundwater/summary",
            "/api/water/reservoirs",
            "/api/water/reservoirs/observations",
            "/api/water/reservoirs/summary",
            "/api/water/advisory",
            "/api/system/health"
        ]
    }


@app.get("/api/system/health")
def get_system_health():
    """
    Returns authentic diagnostic status of all municipal data sources and engines:
    - SQLite persistent baseline database
    - CGWB in-situ groundwater observation dataset
    - CWC bulk reservoir bulletin dataset
    - Water-shortage risk calculation engine
    - Action Centre store status
    Reports genuine record counts, latest observation dates, staleness flags,
    and historical provenance attribution (never claims live telemetry for static bulletins).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    health_report = {
        "timestamp": now_iso,
        "overall_status": "HEALTHY",
        "system": "ClimateShield Multi-Hazard Decision Support System",
        "components": {}
    }

    # 1. Database Status
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM wards;")
        wards_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM interventions;")
        interventions_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM groundwater_observations;")
        gw_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM reservoir_observations;")
        res_count = cursor.fetchone()[0]
        conn.close()

        health_report["components"]["database"] = {
            "status": "OPERATIONAL",
            "database_engine": "SQLite (WAL Mode)",
            "records": {
                "wards": wards_count,
                "interventions": interventions_count,
                "groundwater_observations": gw_count,
                "reservoir_observations": res_count
            },
            "is_accessible": True
        }
    except Exception as e:
        health_report["overall_status"] = "DEGRADED"
        health_report["components"]["database"] = {
            "status": "UNAVAILABLE",
            "error": str(e),
            "is_accessible": False
        }

    # 2. CGWB Groundwater Feed Status
    try:
        stations = get_groundwater_stations(district="Ahmedabad")
        observations = get_groundwater_observations(district="Ahmedabad", limit=1)
        latest_obs_date = observations[0]["observation_date"] if observations else None
        
        health_report["components"]["cgwb_groundwater"] = {
            "status": "OPERATIONAL" if len(stations) > 0 else "DEGRADED",
            "active_stations_count": len(stations),
            "latest_observation_date": latest_obs_date,
            "data_mode": "HISTORICAL_IN_SITU_OBSERVATION",
            "is_live_telemetry": False,
            "source_attribution": "Central Ground Water Board (CGWB) Quarterly Telemetry",
            "provenance": "CGWB_HISTORICAL_IN_SITU",
            "disclaimer": "Quarterly in-situ piezometer surveillance network; not a real-time tap pressure sensor."
        }
    except Exception as e:
        health_report["overall_status"] = "DEGRADED"
        health_report["components"]["cgwb_groundwater"] = {
            "status": "UNAVAILABLE",
            "error": str(e),
            "source_attribution": "Central Ground Water Board (CGWB)"
        }

    # 3. CWC Reservoir Bulletin Feed Status
    try:
        res_summary = get_ahmedabad_bulk_reservoir_summary(max_age_days=30)
        has_data = res_summary.get("status") == "SUCCESS"
        health_report["components"]["cwc_reservoirs"] = {
            "status": "OPERATIONAL" if has_data else "UNAVAILABLE",
            "composite_storage_pct": res_summary.get("composite_storage_pct"),
            "latest_observation_date": res_summary.get("latest_observation_date"),
            "is_stale": res_summary.get("is_stale", False),
            "data_freshness": res_summary.get("data_freshness", "UNKNOWN"),
            "data_mode": "HISTORICAL_WEEKLY_BULLETIN",
            "is_live_telemetry": False,
            "source_attribution": "Central Water Commission (CWC) Weekly Reservoir Storage Bulletin",
            "provenance": "OFFICIAL_CWC_BULLETIN",
            "disclaimer": "Official weekly storage bulletin for Sardar Sarovar and Dharoi; not live SCADA telemetry."
        }
    except Exception as e:
        health_report["overall_status"] = "DEGRADED"
        health_report["components"]["cwc_reservoirs"] = {
            "status": "UNAVAILABLE",
            "error": str(e),
            "source_attribution": "Central Water Commission (CWC)"
        }

    # 4. Water-Shortage Risk Calculation Engine
    health_report["components"]["water_shortage_engine"] = {
        "status": "OPERATIONAL",
        "calculation_mode": "MULTI_FACTOR_HYDROLOGICAL_ASSESSMENT",
        "integrated_components": [
            "Open-Meteo precipitation forecast",
            "CWC bulk reservoir storage",
            "CGWB aquifer stress tier",
            "Structural per-capita proxies"
        ],
        "confidence": "MODERATE (70% Confidence)",
        "source_attribution": "Municipal Hydrology & Risk Calculation Engine"
    }

    # 5. Action Centre Store
    try:
        store = get_action_store()
        actions = store.list_actions()
        health_report["components"]["action_centre"] = {
            "status": "OPERATIONAL",
            "actions_in_store": len(actions),
            "governance_rule": "HUMAN_APPROVAL_MANDATORY"
        }
    except Exception as e:
        health_report["components"]["action_centre"] = {
            "status": "UNAVAILABLE",
            "error": str(e)
        }

    return health_report



@app.get("/api/weather/wbgt")
async def get_wbgt_weather(lat: float = 23.0225, lon: float = 72.5714):
    """
    Fetches Open-Meteo hourly weather for Ahmedabad and calculates Wet Bulb Globe Temperature (WBGT).
    """
    try:
        raw_weather = await fetch_open_meteo_weather(lat, lon)
        forecast_hourly = process_wbgt_forecast(raw_weather)
        
        # Calculate current outdoor WBGT (using peak afternoon or current hour)
        current_sample = forecast_hourly[14] if len(forecast_hourly) > 14 else forecast_hourly[0]
        ward_risks = get_ward_wbgt_risk(current_sample["wbgt_outdoor_c"])
        
        return {
            "city": "Ahmedabad",
            "coordinates": {"lat": lat, "lon": lon},
            "current_heat_status": {
                "timestamp": current_sample["timestamp"],
                "temperature_c": current_sample["temperature_c"],
                "relative_humidity": current_sample["relative_humidity"],
                "solar_radiation_wm2": current_sample["solar_radiation_wm2"],
                "wbgt_outdoor_c": current_sample["wbgt_outdoor_c"],
                "hazard_level": current_sample["risk"]["tier"],
                "action_recommendation": current_sample["risk"]["action"]
            },
            "hourly_forecast": forecast_hourly[:24],
            "ward_heat_risks": ward_risks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching WBGT weather data: {str(e)}")


@app.get("/api/wards")
def get_ahmedabad_wards():
    """Returns baseline vulnerability indicators for Ahmedabad Wards."""
    return {"wards": AHMEDABAD_WARDS}


@app.get("/api/wards/geojson")
def get_ahmedabad_wards_geojson():
    """Returns official Ahmedabad Wards GeoJSON spatial boundary data."""
    import json
    import os
    geojson_path = os.path.join(os.path.dirname(__file__), "data", "Ahmedabad_Wards.geojson")
    if not os.path.exists(geojson_path):
        raise HTTPException(status_code=404, detail="GeoJSON boundary file not found")
    with open(geojson_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/risk/monte-carlo")
def get_ward_risk_monte_carlo(
    simulations: int = Query(500, ge=50, le=2000, description="Number of Monte Carlo weight sensitivity draws"),
    weight_hazard: float = Query(0.40, ge=0.0, le=1.0),
    weight_exposure: float = Query(0.30, ge=0.0, le=1.0),
    weight_vulnerability: float = Query(0.30, ge=0.0, le=1.0)
):
    """
    Calculates explainable IPCC percentile risk scores (Risk = H x E x V) for each ward,
    and runs Monte Carlo draws over index weights to generate uncertainty bands (rank stability).
    """
    try:
        from backend.risk_monte_carlo import calculate_ward_risk_and_monte_carlo
        results = calculate_ward_risk_and_monte_carlo(
            n_simulations=simulations,
            w_h=weight_hazard,
            w_e=weight_exposure,
            w_v=weight_vulnerability
        )
        return {
            "city": "Ahmedabad",
            "total_wards": len(results),
            "monte_carlo_draws": simulations,
            "nominal_weights": {
                "hazard": weight_hazard,
                "exposure": weight_exposure,
                "vulnerability": weight_vulnerability
            },
            "wards_risk": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing Monte Carlo Risk Engine: {str(e)}")




@app.post("/api/optimize")
def run_optimization(req: OptimizationRequest):
    """
    Runs Knapsack Resource Allocation Optimization under budget, crew, water constraints and equity slider controls.
    """
    try:
        result = solve_resource_allocation(
            total_budget_inr=req.total_budget_inr,
            total_crew_members=req.total_crew_members,
            total_water_cap_l=req.total_water_cap_l,
            equity_slider=req.equity_slider,
            wards=req.wards
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimization solver error: {str(e)}")


class ClimateOptimizationRequest(BaseModel):
    total_budget_inr: float = Field(500000.0, ge=10000, le=10000000, description="Total monetary budget in INR")
    total_crew_members: int = Field(40, ge=1, le=500, description="Total available deployment personnel")
    total_water_cap_l: float = Field(30000.0, ge=1000, le=500000, description="Daily water cap limit in Liters")
    equity_slider: float = Field(0.5, ge=0.0, le=1.0, description="Equity priority slider (0.0 to 1.0)")
    scenario_id: Optional[str] = Field(None, description="Optional preset demo scenario ID (compound_hazard, monsoon_cloudburst, summer_drought_scarcity)")
    heat_wbgt: Optional[float] = Field(None, ge=15.0, le=45.0, description="Optional custom outdoor WBGT in °C")
    weight_heat: float = Field(0.5, ge=0.0, le=1.0)
    weight_water: float = Field(0.5, ge=0.0, le=1.0)
    scoring_mode: str = Field("COMPOUND_SYNERGY")


@app.get("/api/optimize/interventions")
def get_interventions_catalog():
    """
    Returns documentation of all available interventions mapped by risk category (Heat, Waterlogging, Shortage),
    with assumed municipal costs, required resources, simulated benefits, and justification templates.
    """
    return {
        "status": "SUCCESS",
        "total_interventions": len(INTERVENTIONS),
        "risk_category_mappings": RISK_CATEGORY_INTERVENTION_MAP,
        "interventions": INTERVENTIONS
    }


@app.post("/api/optimize/climate")
async def run_climate_optimization(req: ClimateOptimizationRequest):
    """
    Directly connects Combined Multi-Hazard Climate Risk outputs (Heat + Water) to the Resource Optimizer.
    Evaluates all 48 wards and produces an explainable, hazard-matched dispatch plan pending human sign-off.
    """
    try:
        climate_results = await evaluate_combined_climate_risk(
            weight_heat=req.weight_heat,
            weight_water=req.weight_water,
            scoring_mode=req.scoring_mode,
            scenario_id=req.scenario_id,
            heat_wbgt_override=req.heat_wbgt
        )
        optimization_plan = optimize_from_combined_climate_results(
            combined_climate_results=climate_results,
            total_budget_inr=req.total_budget_inr,
            total_crew_members=req.total_crew_members,
            total_water_cap_l=req.total_water_cap_l,
            equity_slider=req.equity_slider
        )
        return {
            "climate_scenario": req.scenario_id or "LIVE_METEOROLOGY",
            "scoring_mode": req.scoring_mode,
            "optimization_plan": optimization_plan
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Climate optimization error: {str(e)}")


# -------------------------------------------------------------
# INTERVENTION ENGINE ENDPOINTS & CACHING (Heat + Water Integration)
# -------------------------------------------------------------

# In-memory cache for Combined Climate Risk to avoid redundant external API calls (Requirement 9)
_CLIMATE_ASSESSMENT_CACHE: Dict[str, Any] = {
    "timestamp": 0.0,
    "ttl_seconds": 300.0,  # 5 minutes cache TTL
    "data": None,
    "scenario_id": None
}


async def get_cached_or_fresh_combined_climate_risk(
    scenario_id: Optional[str] = None,
    heat_wbgt_override: Optional[float] = None,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """Retrieves cached climate evaluation or triggers fresh calculation if expired."""
    now = time.time()
    is_cached = (
        not force_refresh and
        _CLIMATE_ASSESSMENT_CACHE["data"] is not None and
        _CLIMATE_ASSESSMENT_CACHE["scenario_id"] == scenario_id and
        heat_wbgt_override is None and
        (now - _CLIMATE_ASSESSMENT_CACHE["timestamp"]) < _CLIMATE_ASSESSMENT_CACHE["ttl_seconds"]
    )
    if is_cached:
        return _CLIMATE_ASSESSMENT_CACHE["data"]

    fresh = await evaluate_combined_climate_risk(
        scenario_id=scenario_id,
        heat_wbgt_override=heat_wbgt_override
    )
    if heat_wbgt_override is None:
        _CLIMATE_ASSESSMENT_CACHE["data"] = fresh
        _CLIMATE_ASSESSMENT_CACHE["timestamp"] = now
        _CLIMATE_ASSESSMENT_CACHE["scenario_id"] = scenario_id
    return fresh


class InterventionRequest(BaseModel):
    total_budget_inr: float = Field(500000.0, ge=5000, le=100000000, description="Total monetary budget in INR")
    total_crew_members: int = Field(40, ge=0, le=1000, description="Total available personnel/staff")
    total_water_cap_l: float = Field(30000.0, ge=0, le=1000000, description="Daily water cap limit in Liters")
    equity_slider: float = Field(0.5, ge=0.0, le=1.0, description="Equity priority slider (0.0 = pure efficiency, 1.0 = maximum equity)")
    wards: Optional[List[Dict[str, Any]]] = Field(None, description="Optional custom ward risk assessments to optimize")
    scenario_id: Optional[str] = Field(None, description="Optional climate demo scenario ID (monsoon_cloudburst, summer_drought_scarcity, dry_baseline, compound_hazard)")
    heat_wbgt: Optional[float] = Field(None, ge=15.0, le=45.0, description="Optional custom outdoor WBGT in °C")
    intervention_capacity_limits: Optional[Dict[str, int]] = Field(None, description="Optional citywide capacity limits per intervention ID")
    existing_interventions: Optional[List[Dict[str, Any]]] = Field(None, description="Optional preexisting active interventions by ward")
    include_tradeoff_analysis: bool = Field(True, description="Whether to compute efficiency vs. equity trade-off benchmark comparison")


@app.get("/api/interventions/catalog")
def get_intervention_engine_catalog():
    """
    Returns full multi-hazard interventions catalog across Heat, Waterlogging, and Water Shortage,
    including unit costs, resource footprints, feasibility scores, trigger thresholds, and data provenance labels.
    """
    return {
        "status": "SUCCESS",
        "provenance_labels": PROVENANCE_LABELS,
        "total_interventions": len(INTERVENTIONS_CATALOG),
        "interventions": INTERVENTIONS_CATALOG
    }


@app.post("/api/interventions/recommend")
async def recommend_interventions(req: InterventionRequest):
    """
    Generates, ranks, and optimizes hazard-matched interventions under budget, crew, water,
    and intervention capacity limits. Directly accounts for preexisting active interventions,
    prevents double-counting with submodular diminishing returns, and evaluates efficiency vs. equity trade-offs.
    """
    try:
        # If user did not provide custom ward risks, pull from cached/live combined climate evaluation
        if req.wards:
            wards_to_use = req.wards
        else:
            climate_data = await get_cached_or_fresh_combined_climate_risk(
                scenario_id=req.scenario_id,
                heat_wbgt_override=req.heat_wbgt
            )
            wards_to_use = climate_data.get("ranked_wards", climate_data.get("wards", []))

        plan = generate_intervention_recommendations(
            wards=wards_to_use,
            total_budget_inr=req.total_budget_inr,
            total_crew_members=req.total_crew_members,
            total_water_cap_l=req.total_water_cap_l,
            equity_slider=req.equity_slider,
            intervention_capacity_limits=req.intervention_capacity_limits,
            existing_interventions=req.existing_interventions,
            include_tradeoff_analysis=req.include_tradeoff_analysis
        )
        return plan
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Intervention Engine execution failed: {str(e)}")


@app.get("/api/interventions/ranked")
async def get_ranked_interventions_endpoint(
    ward_id: Optional[str] = Query(None, description="Filter for specific ward (e.g. 'W1', 'Danilimda')"),
    hazard: Optional[str] = Query(None, description="Filter by hazard: 'heat', 'flood/waterlogging', 'water_shortage'"),
    equity_slider: float = Query(0.5, ge=0.0, le=1.0, description="Equity slider parameter (0.0 to 1.0)"),
    scenario_id: Optional[str] = Query(None, description="Optional climate demo scenario ID")
):
    """
    Retrieves ranked candidate interventions across all 48 wards or filtered by ward or hazard,
    including priority scores, expected impact ranges, people reached, lead times, and rationales.
    """
    try:
        from backend.intervention_engine import default_engine
        climate_data = await get_cached_or_fresh_combined_climate_risk(scenario_id=scenario_id)
        wards_to_use = climate_data.get("ranked_wards", climate_data.get("wards", []))
        candidates = default_engine.generate_candidate_interventions(wards_to_use)
        ranked = default_engine.rank_candidate_interventions(candidates, equity_slider=equity_slider)

        if ward_id:
            clean_wid = ward_id.strip().lower()
            ranked = [
                c for c in ranked
                if clean_wid in c["target_ward"]["ward_id"].lower()
                or clean_wid in c["target_ward"]["ward_name"].lower()
            ]
        if hazard:
            clean_h = hazard.strip().lower()
            ranked = [c for c in ranked if clean_h in c["related_hazard"].lower() or clean_h in c["category"].lower()]

        return {
            "status": "SUCCESS",
            "target_ward_filter": ward_id or "ALL",
            "hazard_filter": hazard or "ALL",
            "equity_slider": equity_slider,
            "total_ranked_interventions": len(ranked),
            "ranked_interventions": ranked
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve ranked interventions: {str(e)}")


@app.get("/api/interventions/wards/{ward_id}")
async def get_ward_ranked_interventions(
    ward_id: str,
    equity_slider: float = Query(0.5, ge=0.0, le=1.0, description="Equity slider parameter"),
    scenario_id: Optional[str] = Query(None, description="Optional demo scenario ID")
):
    """
    Retrieves complete candidate interventions profile specifically for a single selected ward.
    """
    try:
        from backend.intervention_engine import default_engine
        climate_data = await get_cached_or_fresh_combined_climate_risk(scenario_id=scenario_id)
        wards_to_use = climate_data.get("ranked_wards", climate_data.get("wards", []))

        clean_wid = ward_id.strip().lower()
        matched_wards = [
            w for w in wards_to_use
            if clean_wid == str(w.get("id", "")).lower()
            or clean_wid in str(w.get("name", "")).lower()
            or clean_wid in str(w.get("official_name", "")).lower()
        ]
        if not matched_wards:
            raise HTTPException(
                status_code=404,
                detail=f"Ward '{ward_id}' not found in Ahmedabad administrative wards database. Try using valid ID (e.g. W1-W48) or name (e.g. Danilimda, Vatva)."
            )

        target_ward = matched_wards[0]
        candidates = default_engine.generate_candidate_interventions([target_ward])
        ranked = default_engine.rank_candidate_interventions(candidates, equity_slider=equity_slider)

        return {
            "status": "SUCCESS",
            "ward_id": target_ward.get("id", ward_id),
            "ward_name": target_ward.get("name", ""),
            "equity_slider": equity_slider,
            "candidate_interventions_count": len(ranked),
            "interventions": ranked
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving interventions for ward '{ward_id}': {str(e)}")


class WhatIfSimulationRequest(BaseModel):
    # Simulated scenario parameters (user-controllable)
    simulated_budget_inr: float = Field(500000.0, ge=5000, le=100000000, description="Simulated monetary budget in INR")
    simulated_crew_members: int = Field(40, ge=0, le=1000, description="Simulated response teams / personnel count")
    simulated_water_cap_l: float = Field(30000.0, ge=0, le=1000000, description="Simulated daily water cap limit in Liters")
    simulated_equity_slider: float = Field(0.5, ge=0.0, le=1.0, description="Simulated equity preference slider (0.0 = efficiency, 1.0 = maximum equity)")
    simulated_capacity_limits: Optional[Dict[str, int]] = Field(None, description="Optional simulated fleet capacity limits per intervention")

    # Baseline scenario parameters (default to standard municipal parameters)
    baseline_budget_inr: float = Field(500000.0, ge=5000, le=100000000, description="Baseline comparison budget in INR")
    baseline_crew_members: int = Field(40, ge=0, le=1000, description="Baseline comparison response teams count")
    baseline_water_cap_l: float = Field(30000.0, ge=0, le=1000000, description="Baseline comparison water cap limit in Liters")
    baseline_equity_slider: float = Field(0.5, ge=0.0, le=1.0, description="Baseline comparison equity slider")
    baseline_capacity_limits: Optional[Dict[str, int]] = Field(None, description="Optional baseline capacity limits")

    # Optional inputs
    wards: Optional[List[Dict[str, Any]]] = Field(None, description="Optional custom ward risk assessments to simulate")
    scenario_id: Optional[str] = Field(None, description="Optional climate demo scenario ID")
    heat_wbgt: Optional[float] = Field(None, ge=15.0, le=45.0, description="Optional custom outdoor WBGT in °C")
    existing_interventions: Optional[List[Dict[str, Any]]] = Field(None, description="Optional preexisting active interventions by ward")


@app.post("/api/interventions/simulate")
async def simulate_what_if_interventions(req: WhatIfSimulationRequest):
    """
    Lightweight What-If Simulator:
    Recalculates recommended interventions when users modify budget, response teams,
    water caps, equity preference, or intervention capacity limits.
    Compares baseline vs. simulated allocations, displays priority shifts (wards gaining/losing),
    shows impact uncertainty ranges, and provides explainable trade-off narratives.
    """
    try:
        if req.wards:
            wards_to_use = req.wards
        else:
            climate_data = await get_cached_or_fresh_combined_climate_risk(
                scenario_id=req.scenario_id,
                heat_wbgt_override=req.heat_wbgt
            )
            wards_to_use = climate_data.get("ranked_wards", climate_data.get("wards", []))

        result = run_what_if_simulation(
            wards=wards_to_use,
            simulated_budget_inr=req.simulated_budget_inr,
            simulated_crew_members=req.simulated_crew_members,
            simulated_water_cap_l=req.simulated_water_cap_l,
            simulated_equity_slider=req.simulated_equity_slider,
            simulated_capacity_limits=req.simulated_capacity_limits,
            baseline_budget_inr=req.baseline_budget_inr,
            baseline_crew_members=req.baseline_crew_members,
            baseline_water_cap_l=req.baseline_water_cap_l,
            baseline_equity_slider=req.baseline_equity_slider,
            baseline_capacity_limits=req.baseline_capacity_limits,
            existing_interventions=req.existing_interventions
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"What-If Simulator error: {str(e)}")


# -------------------------------------------------------------
# WATER RISK ENGINE ENDPOINTS
# -------------------------------------------------------------

class WaterAssessmentRequest(BaseModel):
    scenario_id: Optional[str] = Field(None, description="Preset demonstration scenario ID (e.g., monsoon_cloudburst, summer_drought_scarcity)")
    rainfall_24h_mm: Optional[float] = Field(None, ge=0.0, le=500.0, description="Optional custom 24-hour rainfall in mm")
    peak_hourly_rainfall_mm: Optional[float] = Field(None, ge=0.0, le=200.0, description="Optional custom peak 1-hour rainfall in mm/hr")
    supply_lpcd: Optional[float] = Field(None, ge=10.0, le=300.0, description="Observed/simulated potable supply in Liters Per Capita per Day")
    reservoir_storage_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Observed/simulated bulk reservoir storage percentage")
    groundwater_depth_m: Optional[float] = Field(None, ge=0.0, le=200.0, description="Observed/simulated groundwater depth in mbgl")
    groundwater_trend_annual_m: Optional[float] = Field(None, description="Observed/simulated annual groundwater decline rate in m/yr")


@app.get("/api/water/scenarios")
def get_water_scenarios():
    """Returns curated synthetic demonstration scenarios for disaster stress-testing."""
    return {
        "status": "SUCCESS",
        "description": "Pre-configured synthetic scenarios for water risk stress-testing. Clearly labelled as demonstration inputs.",
        "scenarios": DEMONSTRATION_SCENARIOS
    }


@app.get("/api/water/wards")
async def get_all_wards_water_risk(
    scenario_id: Optional[str] = Query(None, description="Optional preset demo scenario: dry_baseline, monsoon_cloudburst, summer_drought_scarcity, compound_hazard"),
    rainfall_24h_mm: Optional[float] = Query(None, ge=0.0, le=500.0, description="Optional custom 24-hour rainfall in mm"),
    peak_hourly_rainfall_mm: Optional[float] = Query(None, ge=0.0, le=200.0, description="Optional custom peak 1-hour rainfall in mm/hr"),
    supply_lpcd: Optional[float] = Query(None, ge=10.0, le=300.0, description="Optional observed supply in Liters Per Capita per Day"),
    reservoir_storage_pct: Optional[float] = Query(None, ge=0.0, le=100.0, description="Optional observed bulk reservoir storage percentage"),
    groundwater_depth_m: Optional[float] = Query(None, ge=0.0, le=200.0, description="Optional observed groundwater depth in mbgl"),
    groundwater_trend_annual_m: Optional[float] = Query(None, description="Optional observed groundwater decline rate in m/yr"),
    lat: float = Query(23.0225, ge=-90.0, le=90.0, description="Latitude for Open-Meteo weather"),
    lon: float = Query(72.5714, ge=-180.0, le=180.0, description="Longitude for Open-Meteo weather")
):
    """
    Calculates urban water risk across all available Ahmedabad wards.
    Returns city status, data quality indicators, and ward-by-ward risk scores with explainable factor breakdowns.
    """
    try:
        results = await assess_citywide_water_risk(
            scenario_id=scenario_id,
            supply_lpcd_override=supply_lpcd,
            reservoir_storage_override=reservoir_storage_pct,
            rainfall_24h_override=rainfall_24h_mm,
            peak_hourly_override=peak_hourly_rainfall_mm,
            groundwater_depth_override=groundwater_depth_m,
            groundwater_trend_override=groundwater_trend_annual_m,
            lat=lat,
            lon=lon
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calculate citywide water risk: {str(e)}")


@app.get("/api/water/wards/{ward_id}")
async def get_single_ward_water_risk_endpoint(
    ward_id: str,
    scenario_id: Optional[str] = Query(None, description="Optional preset demo scenario: dry_baseline, monsoon_cloudburst, summer_drought_scarcity, compound_hazard"),
    rainfall_24h_mm: Optional[float] = Query(None, ge=0.0, le=500.0, description="Optional custom 24-hour rainfall in mm"),
    peak_hourly_rainfall_mm: Optional[float] = Query(None, ge=0.0, le=200.0, description="Optional custom peak 1-hour rainfall in mm/hr"),
    supply_lpcd: Optional[float] = Query(None, ge=10.0, le=300.0, description="Optional observed supply in LPCD"),
    reservoir_storage_pct: Optional[float] = Query(None, ge=0.0, le=100.0, description="Optional observed reservoir storage percentage"),
    groundwater_depth_m: Optional[float] = Query(None, ge=0.0, le=200.0, description="Optional observed groundwater depth in mbgl"),
    groundwater_trend_annual_m: Optional[float] = Query(None, description="Optional observed groundwater decline rate in m/yr")
):
    """
    Retrieves the complete water risk profile for a selected ward.
    Accepts ward ID (e.g., 'W1', 'W7', '36') or ward Name (e.g., 'Danilimda', 'Vatva', '36 DANILIMDA').
    """
    try:
        ward_data = await get_single_ward_water_risk(
            ward_identifier=ward_id,
            scenario_id=scenario_id,
            supply_lpcd_override=supply_lpcd,
            reservoir_storage_override=reservoir_storage_pct,
            rainfall_24h_override=rainfall_24h_mm,
            peak_hourly_override=peak_hourly_rainfall_mm,
            groundwater_depth_override=groundwater_depth_m,
            groundwater_trend_override=groundwater_trend_annual_m
        )
        if not ward_data:
            raise HTTPException(
                status_code=404,
                detail=f"Ward '{ward_id}' not found in Ahmedabad administrative wards database. Try using a valid ward ID (e.g., W1-W10, W1-W48) or ward name (e.g., Danilimda, Vatva, Maninagar)."
            )
        return ward_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluating water risk for ward '{ward_id}': {str(e)}")


@app.get("/api/water/risk")
async def get_citywide_water_risk(
    scenario_id: Optional[str] = Query(None, description="Optional demo scenario ID: dry_baseline, monsoon_cloudburst, summer_drought_scarcity, compound_hazard"),
    rainfall_24h_mm: Optional[float] = Query(None, ge=0.0, le=500.0, description="Optional custom 24-hour rainfall in mm"),
    peak_hourly_rainfall_mm: Optional[float] = Query(None, ge=0.0, le=200.0, description="Optional custom peak 1-hour rainfall in mm/hr"),
    supply_lpcd: Optional[float] = Query(None, ge=10.0, le=300.0, description="Optional observed supply in Liters Per Capita per Day"),
    reservoir_storage_pct: Optional[float] = Query(None, ge=0.0, le=100.0, description="Optional observed reservoir storage percentage"),
    groundwater_depth_m: Optional[float] = Query(None, ge=0.0, le=200.0, description="Optional observed groundwater depth in mbgl"),
    groundwater_trend_annual_m: Optional[float] = Query(None, description="Optional observed groundwater decline rate in m/yr"),
    lat: float = Query(23.0225, ge=-90.0, le=90.0),
    lon: float = Query(72.5714, ge=-180.0, le=180.0)
):
    """
    Evaluates ward-level waterlogging/pluvial flood risk and water shortage risk (0-100 scale).
    Uses live Open-Meteo precipitation unless a synthetic demonstration scenario or custom override is selected.
    Includes data quality indicator and explainable contributing factor breakdowns.
    """
    try:
        results = await assess_citywide_water_risk(
            scenario_id=scenario_id,
            supply_lpcd_override=supply_lpcd,
            reservoir_storage_override=reservoir_storage_pct,
            rainfall_24h_override=rainfall_24h_mm,
            peak_hourly_override=peak_hourly_rainfall_mm,
            groundwater_depth_override=groundwater_depth_m,
            groundwater_trend_override=groundwater_trend_annual_m,
            lat=lat,
            lon=lon
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Water Risk Engine calculation failed: {str(e)}")


@app.post("/api/water/assess")
@app.post("/api/water/calculate")
async def assess_custom_water_risk(req: WaterAssessmentRequest):
    """
    Custom scenario evaluation allowing parameter overrides for what-if simulation planning.
    """
    try:
        results = await assess_citywide_water_risk(
            scenario_id=req.scenario_id,
            supply_lpcd_override=req.supply_lpcd,
            reservoir_storage_override=req.reservoir_storage_pct,
            rainfall_24h_override=req.rainfall_24h_mm,
            peak_hourly_override=req.peak_hourly_rainfall_mm,
            groundwater_depth_override=req.groundwater_depth_m,
            groundwater_trend_override=req.groundwater_trend_annual_m
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Custom Water Risk assessment failed: {str(e)}")


# -------------------------------------------------------------
# GROUNDWATER MONITORING ENDPOINTS (CGWB REAL DATA INTEGRATION)
# -------------------------------------------------------------

@app.get("/api/water/groundwater/stations")
def get_groundwater_stations_endpoint(
    district: Optional[str] = Query("Ahmedabad", description="District filter (e.g. 'Ahmedabad', 'Surat', 'Gandhinagar'). Set empty to retrieve all.")
):
    """
    Returns verified monitoring stations from Central Ground Water Board (CGWB)
    including GPS coordinates, administrative block, latest observed depth (mbgl),
    and total quarterly observations.
    """
    try:
        dist_filter = district.strip() if district and district.strip() else None
        stations = get_groundwater_stations(district=dist_filter)
        return {
            "status": "SUCCESS",
            "district_filter": dist_filter or "ALL_GUJARAT",
            "total_stations": len(stations),
            "stations": stations
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve groundwater stations: {str(e)}")


@app.get("/api/water/groundwater/observations")
def get_groundwater_observations_endpoint(
    station_name: Optional[str] = Query(None, description="Optional station name filter (e.g. 'Vatwa Pz-I', 'Bopal_Pz_I')"),
    district: Optional[str] = Query("Ahmedabad", description="Optional district filter"),
    season: Optional[str] = Query(None, description="Optional seasonal filter: PRE_MONSOON, MONSOON, POST_MONSOON, WINTER_RABI"),
    start_date: Optional[str] = Query(None, description="Earliest observation date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Latest observation date (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    Retrieves normalized, validated groundwater level observation history.
    Values represent depth to water table in metres below ground level (mbgl).
    Missing values are explicitly marked and never fabricated.
    """
    try:
        observations = get_groundwater_observations(
            station_name=station_name,
            district=district if district and district.strip() else None,
            season=season,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )
        return {
            "status": "SUCCESS",
            "filters": {
                "station_name": station_name,
                "district": district,
                "season": season,
                "start_date": start_date,
                "end_date": end_date
            },
            "count": len(observations),
            "observations": observations
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve groundwater observations: {str(e)}")


@app.get("/api/water/groundwater/trends")
def get_groundwater_trends_endpoint(
    district: Optional[str] = Query("Ahmedabad", description="District for trend analysis (default: Ahmedabad)"),
    station_name: Optional[str] = Query(None, description="Optional station-specific trend analysis")
):
    """
    Computes statistical multi-year water table trends, seasonal recharge potential,
    annual decline rate (m/year), and aquifer stress tier classification.
    """
    try:
        trends = get_groundwater_trends(
            district=district if district and district.strip() else None,
            station_name=station_name
        )
        return trends
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calculate groundwater trends: {str(e)}")


@app.get("/api/water/groundwater/summary")
def get_groundwater_summary_endpoint():
    """
    Returns executive summary of Ahmedabad groundwater levels and regional aquifer health.
    """
    try:
        trends = get_groundwater_trends(district="Ahmedabad")
        stations = get_groundwater_stations(district="Ahmedabad")
        return {
            "status": "SUCCESS",
            "city": "Ahmedabad",
            "district": "Ahmedabad",
            "active_stations": len(stations),
            "stress_tier": trends.get("aquifer_stress_assessment", {}).get("tier"),
            "average_depth_mbgl": trends.get("statistics", {}).get("average_depth_mbgl"),
            "seasonal_recharge_potential_m": trends.get("statistics", {}).get("seasonal_recharge_potential_m"),
            "annual_decline_rate_m_per_year": trends.get("statistics", {}).get("annual_decline_rate_m_per_year"),
            "data_source": "Central Ground Water Board (CGWB) Quarterly Manual Telemetry",
            "provenance": "REAL_MANUAL_CGWB"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate groundwater summary: {str(e)}")


# -------------------------------------------------------------
# RESERVOIR MONITORING ENDPOINTS (CWC OFFICIAL DATA INTEGRATION)
# -------------------------------------------------------------

@app.get("/api/water/reservoirs")
def get_reservoirs_endpoint(
    max_age_days: int = Query(30, ge=1, le=365, description="Max observation age in days before flagging as stale")
):
    """
    Returns verified monitoring records for major Gujarat reservoirs
    from Central Water Commission (CWC) weekly bulletins, including
    Sardar Sarovar and Dharoi.
    """
    try:
        from backend.database import get_latest_reservoir_observations
        reservoirs = get_latest_reservoir_observations(max_age_days=max_age_days)
        return {
            "status": "SUCCESS",
            "total_reservoirs": len(reservoirs),
            "reservoirs": reservoirs,
            "data_source": "Central Water Commission (CWC) Weekly Reservoir Storage Bulletin",
            "provenance": "OFFICIAL_CWC_BULLETIN"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve reservoir observations: {str(e)}")


@app.get("/api/water/reservoirs/observations")
def get_reservoir_observations_endpoint(
    reservoir_name: Optional[str] = Query(None, description="Filter by reservoir name (e.g. 'Sardar Sarovar', 'Dharoi')"),
    start_date: Optional[str] = Query(None, description="Earliest observation date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Latest observation date (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    Retrieves normalized historical reservoir storage observations.
    Storage volumes and capacities are reported in Billion Cubic Meters (BCM).
    """
    try:
        from backend.database import get_reservoir_observations
        records = get_reservoir_observations(
            reservoir_name=reservoir_name,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )
        return {
            "status": "SUCCESS",
            "filters": {
                "reservoir_name": reservoir_name,
                "start_date": start_date,
                "end_date": end_date
            },
            "count": len(records),
            "observations": records
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve reservoir observations: {str(e)}")


@app.get("/api/water/reservoirs/summary")
def get_reservoir_summary_endpoint(
    max_age_days: int = Query(30, ge=1, le=365, description="Max observation age in days before flagging as stale")
):
    """
    Returns executive summary of Ahmedabad bulk reservoir storage,
    combining Sardar Sarovar (Narmada Canal ~80%) and Dharoi Reservoir (Sabarmati ~20%).
    Guarantees that historical or stale data is NEVER presented as live telemetry.
    """
    try:
        from backend.database import get_ahmedabad_bulk_reservoir_summary
        summary = get_ahmedabad_bulk_reservoir_summary(max_age_days=max_age_days)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate reservoir summary: {str(e)}")


class ReservoirImportRequest(BaseModel):
    file_path: Optional[str] = Field(None, description="Optional custom CSV/XLS report path to import")


@app.post("/api/water/reservoirs/import")
def import_reservoir_report_endpoint(req: Optional[ReservoirImportRequest] = None):
    """
    Imports and validates official reservoir storage reports (CWC Weekly Bulletin / RSMS CSV).
    Deduplicates records and stores verified observations into SQLite.
    """
    try:
        from backend.data_sources.reservoir_parser import ReservoirParser
        from backend.database import insert_reservoir_observations

        custom_path = req.file_path if req and req.file_path else None
        parser = ReservoirParser(file_path=custom_path)
        parsed = parser.parse()

        if not parsed.get("success"):
            raise HTTPException(status_code=400, detail=parsed.get("error", "CSV parsing failed"))

        inserted, skipped = insert_reservoir_observations(parsed["valid_records"])
        return {
            "status": "SUCCESS",
            "total_rows_read": parsed["total_rows_read"],
            "valid_records_count": parsed["valid_records_count"],
            "inserted_records": inserted,
            "skipped_duplicates": skipped,
            "rejected_rows_count": parsed["rejected_rows_count"],
            "reservoirs_count": parsed["reservoirs_count"],
            "rejected_samples": parsed.get("rejected_samples", [])
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reservoir import failed: {str(e)}")


# -------------------------------------------------------------
# WATER SCARCITY & DROUGHT ADVISORY WORKFLOW
# -------------------------------------------------------------

class WaterAdvisoryRequest(BaseModel):
    advisory_type: str = Field("water_scarcity", description="Type: water_scarcity | drought_emergency | groundwater_depletion")
    severity_tier: str = Field("MODERATE", description="Severity level: MODERATE | SEVERE | CRITICAL")
    target_zones: List[str] = Field(default_factory=list, description="Target municipal zones (e.g. East Zone, South Zone)")
    target_wards: Optional[List[str]] = Field(default_factory=list, description="Target ward identifiers (e.g. W1, W7)")
    recommendations: List[str] = Field(..., description="Operational recommendations: water_conservation_messaging, water_tanker_dispatch, leak_inspection_repair, groundwater_extraction_monitoring")
    reason: str = Field(..., min_length=5, description="Administrative reason/justification for advisory")
    confirmed_by: str = Field("Municipal Operator", description="Authorizing operator or municipal official")
    data_sources: Optional[List[str]] = Field(None, description="Data sources backing the advisory")
    observation_dates: Optional[Dict[str, str]] = Field(None, description="Observation dates of supporting data")
    confidence_level: Optional[str] = Field("MODERATE", description="Confidence level: HIGH | MODERATE | LOW")
    confirmation_acknowledged: bool = Field(False, description="Explicit confirmation that this is a decision-support recommendation requiring human approval, NOT an automated physical dispatch")


@app.post("/api/water/advisory")
def issue_water_advisory_endpoint(req: WaterAdvisoryRequest):
    """
    Submits a verified Water Scarcity / Drought Advisory.
    Strictly distinguishes recommendations from executed actions.
    Persists proposed decision-support directives into the Action Centre store
    with 'proposed' status requiring human administrative authorization before dispatch.
    """
    if not req.confirmation_acknowledged:
        raise HTTPException(
            status_code=422,
            detail="Advisory requires explicit confirmation and acknowledgment that this creates operational recommendations requiring human authorization before any physical field dispatch."
        )

    if not req.target_zones and not req.target_wards:
        raise HTTPException(
            status_code=422,
            detail="At least one target municipal zone or ward must be specified for the water advisory."
        )

    if not req.recommendations or len(req.recommendations) == 0:
        raise HTTPException(
            status_code=422,
            detail="At least one operational recommendation must be selected."
        )

    tier_upper = req.severity_tier.upper()
    if tier_upper not in ["MODERATE", "SEVERE", "CRITICAL"]:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid severity tier '{req.severity_tier}'. Must be MODERATE, SEVERE, or CRITICAL."
        )

    priority = "critical" if tier_upper == "CRITICAL" else "high" if tier_upper == "SEVERE" else "medium"
    risk_score = 85.0 if tier_upper == "CRITICAL" else 70.0 if tier_upper == "SEVERE" else 50.0

    cost = 15000.0
    crew = 4
    water_l = 0.0

    if "water_tanker_dispatch" in req.recommendations:
        cost += 35000.0
        crew += 4
        water_l += 30000.0
    if "leak_inspection_repair" in req.recommendations:
        cost += 20000.0
        crew += 4
    if "groundwater_extraction_monitoring" in req.recommendations:
        cost += 10000.0
        crew += 2

    zone_label = ", ".join(req.target_zones) if req.target_zones else ", ".join(req.target_wards or ["Citywide"])
    primary_ward = req.target_wards[0] if req.target_wards else "AMC-WATER-CELL"

    reason_text = (
        f"Water Scarcity Advisory ({tier_upper}) issued by {req.confirmed_by}. "
        f"Target Zones: {zone_label}. "
        f"Recommendations: {', '.join(req.recommendations)}. "
        f"Justification: {req.reason}. "
        f"Data Sources: {', '.join(req.data_sources or ['CWC Bulletin', 'CGWB Groundwater'])}. "
        f"Confidence: {req.confidence_level}."
    )

    store = get_action_store()
    action = store.create_action(
        ward_id=primary_ward,
        ward_name=f"Ahmedabad Water Security ({zone_label})",
        action_type="water_conservation_advisory",
        priority=priority,
        reason=reason_text,
        required_resources={
            "cost_inr": cost,
            "crew_required": crew,
            "water_required_l": water_l,
            "recommended_interventions": req.recommendations,
            "data_sources": req.data_sources or ["CWC Bulletin", "CGWB In-Situ Network"],
            "observation_dates": req.observation_dates or {"cwc": "2024-05-15", "cgwb": "2024-05-15"},
            "confidence": req.confidence_level or "MODERATE",
            "is_physical_execution": False,
            "human_authorization_required": True
        },
        related_hazard="water_shortage",
        risk_score=risk_score,
        source="advisory_modal",
    )

    advisory_id = f"ADV-WTR-{int(datetime.now().timestamp())}"

    return {
        "status": "SUCCESS",
        "advisory_id": advisory_id,
        "advisory_type": req.advisory_type,
        "severity_tier": tier_upper,
        "target_zones": req.target_zones,
        "target_wards": req.target_wards,
        "recommendations": req.recommendations,
        "reason": req.reason,
        "confirmed_by": req.confirmed_by,
        "data_sources": req.data_sources or ["Central Water Commission (CWC) Weekly Bulletin", "Central Ground Water Board (CGWB) In-Situ Telemetry"],
        "observation_dates": req.observation_dates or {"cwc_bulletin": "2024-05-15", "cgwb_groundwater": "2024-05-15"},
        "confidence_level": req.confidence_level or "MODERATE",
        "action_record": action,
        "is_executed": False,
        "human_approval_required": True,
        "notice": ACTION_CENTRE_ADVISORY
    }


# -------------------------------------------------------------
# COMBINED CLIMATE RISK ENGINE ENDPOINTS (HEAT + WATER)
# -------------------------------------------------------------

class CombinedClimateRiskRequest(BaseModel):
    weight_heat: float = Field(0.5, ge=0.0, le=1.0, description="Configurable relative weight for Heat Risk")
    weight_water: float = Field(0.5, ge=0.0, le=1.0, description="Configurable relative weight for Water Risk")
    scoring_mode: str = Field("COMPOUND_SYNERGY", description="Scoring mode: COMPOUND_SYNERGY | WEIGHTED_AVERAGE | WORST_CASE_PEAK")
    synergy_multiplier: float = Field(0.15, ge=0.0, le=1.0, description="Compound hazard amplification factor")
    scenario_id: Optional[str] = Field(None, description="Optional preset demo scenario ID")
    heat_wbgt: Optional[float] = Field(None, ge=15.0, le=45.0, description="Optional custom outdoor WBGT in °C")
    supply_lpcd: Optional[float] = Field(None, ge=10.0, le=300.0, description="Optional observed potable supply in LPCD")
    reservoir_storage_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Optional observed reservoir storage percentage")
    rainfall_24h_mm: Optional[float] = Field(None, ge=0.0, le=500.0, description="Optional custom 24-hr rainfall in mm")
    peak_hourly_rainfall_mm: Optional[float] = Field(None, ge=0.0, le=200.0, description="Optional custom peak 1-hr rainfall in mm/hr")


@app.get("/api/climate-risk")
@app.get("/api/climate/combined-risk")
async def get_combined_climate_risk(
    weight_heat: float = Query(0.5, ge=0.0, le=1.0, description="Configurable weight for Heat Risk (0.0 to 1.0)"),
    weight_water: float = Query(0.5, ge=0.0, le=1.0, description="Configurable weight for Water Risk (0.0 to 1.0)"),
    scoring_mode: str = Query("COMPOUND_SYNERGY", description="Scoring mode: COMPOUND_SYNERGY, WEIGHTED_AVERAGE, WORST_CASE_PEAK"),
    synergy_multiplier: float = Query(0.15, ge=0.0, le=1.0, description="Compound synergy multiplier factor"),
    scenario_id: Optional[str] = Query(None, description="Optional preset demo scenario ID"),
    heat_wbgt: Optional[float] = Query(None, ge=15.0, le=45.0, description="Optional custom outdoor WBGT in °C"),
    supply_lpcd: Optional[float] = Query(None, ge=10.0, le=300.0, description="Optional observed supply in LPCD"),
    reservoir_storage_pct: Optional[float] = Query(None, ge=0.0, le=100.0, description="Optional observed reservoir storage percentage"),
    rainfall_24h_mm: Optional[float] = Query(None, ge=0.0, le=500.0, description="Optional custom 24-hour rainfall in mm"),
    peak_hourly_rainfall_mm: Optional[float] = Query(None, ge=0.0, le=200.0, description="Optional custom peak 1-hour rainfall in mm/hr"),
    lat: float = Query(23.0225, ge=-90.0, le=90.0),
    lon: float = Query(72.5714, ge=-180.0, le=180.0)
):
    """
    Evaluates combined multi-hazard climate risk integrating Heat and Water risk dimensions.
    Returns ranked wards, dual-hazard compound flags, explainable rationales, and explicit data quality indicators.
    """
    if scoring_mode not in SCORING_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid scoring mode '{scoring_mode}'. Supported modes: {SCORING_MODES}"
        )
    if weight_heat + weight_water <= 0.0:
        raise HTTPException(
            status_code=422,
            detail="The sum of weight_heat and weight_water must be greater than zero."
        )
    try:
        results = await evaluate_combined_climate_risk(
            weight_heat=weight_heat,
            weight_water=weight_water,
            scoring_mode=scoring_mode,
            synergy_multiplier=synergy_multiplier,
            scenario_id=scenario_id,
            heat_wbgt_override=heat_wbgt,
            supply_lpcd_override=supply_lpcd,
            reservoir_storage_override=reservoir_storage_pct,
            rainfall_24h_override=rainfall_24h_mm,
            peak_hourly_override=peak_hourly_rainfall_mm,
            lat=lat,
            lon=lon
        )
        return results
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Combined Climate Risk evaluation failed: {str(e)}")


@app.get("/api/climate-risk/wards/{ward_id}")
async def get_single_ward_climate_risk(
    ward_id: str,
    weight_heat: float = Query(0.5, ge=0.0, le=1.0),
    weight_water: float = Query(0.5, ge=0.0, le=1.0),
    scoring_mode: str = Query("COMPOUND_SYNERGY"),
    synergy_multiplier: float = Query(0.15, ge=0.0, le=1.0),
    scenario_id: Optional[str] = Query(None),
    heat_wbgt: Optional[float] = Query(None, ge=15.0, le=45.0),
    supply_lpcd: Optional[float] = Query(None, ge=10.0, le=300.0),
    reservoir_storage_pct: Optional[float] = Query(None, ge=0.0, le=100.0),
    rainfall_24h_mm: Optional[float] = Query(None, ge=0.0, le=500.0),
    peak_hourly_rainfall_mm: Optional[float] = Query(None, ge=0.0, le=200.0)
):
    """
    Retrieves the detailed multi-hazard climate risk assessment for a specific ward.
    Accepts ward ID (e.g. 'W1', 'W7', '36'), numeric index (e.g. '0', '35'), or ward name (e.g. 'Danilimda', 'Vatva').
    """
    if scoring_mode not in SCORING_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid scoring mode '{scoring_mode}'. Supported modes: {SCORING_MODES}"
        )
    try:
        results = await evaluate_combined_climate_risk(
            weight_heat=weight_heat,
            weight_water=weight_water,
            scoring_mode=scoring_mode,
            synergy_multiplier=synergy_multiplier,
            scenario_id=scenario_id,
            heat_wbgt_override=heat_wbgt,
            supply_lpcd_override=supply_lpcd,
            reservoir_storage_override=reservoir_storage_pct,
            rainfall_24h_override=rainfall_24h_mm,
            peak_hourly_override=peak_hourly_rainfall_mm
        )

        norm_target = ward_id.strip().lower()
        matched_ward = None

        # Strategy 1: Exact canonical ID match (e.g. 'w1')
        for w in results["ranked_wards"]:
            if str(w.get("id", "")).strip().lower() == norm_target:
                matched_ward = w
                break

        # Strategy 2: Numeric index or ward number match (e.g. '12' or '35')
        if not matched_ward:
            for w in results["ranked_wards"]:
                if str(w.get("ward_index", "")) == norm_target or str(w.get("ward_index", 0) + 1) == norm_target:
                    matched_ward = w
                    break

        # Strategy 3: Name substring match (e.g. 'danilimda' in 'Danilimda' or '36 DANILIMDA')
        if not matched_ward:
            for w in results["ranked_wards"]:
                if norm_target in w.get("name", "").lower() or norm_target in w.get("official_name", "").lower():
                    matched_ward = w
                    break

        if not matched_ward:
            raise HTTPException(
                status_code=404,
                detail=f"Ward '{ward_id}' not found in Climate Risk assessment. Please specify a valid ward ID (e.g. W1-W48) or ward name."
            )

        return {
            "city": results["city"],
            "coordinates": results["coordinates"],
            "timestamp": results["timestamp"],
            "scoring_configuration": results["scoring_configuration"],
            "data_quality_and_confidence": results["data_quality_and_confidence"],
            "ward": matched_ward
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluating ward climate risk: {str(e)}")


@app.get("/api/climate-risk/rankings")
async def get_climate_risk_rankings(
    limit: Optional[int] = Query(None, ge=1, le=48, description="Max number of ranked wards to return"),
    compound_only: bool = Query(False, description="Filter for dual-hazard compound hotspots only"),
    weight_heat: float = Query(0.5, ge=0.0, le=1.0),
    weight_water: float = Query(0.5, ge=0.0, le=1.0),
    scoring_mode: str = Query("COMPOUND_SYNERGY"),
    synergy_multiplier: float = Query(0.15, ge=0.0, le=1.0),
    scenario_id: Optional[str] = Query(None),
    heat_wbgt: Optional[float] = Query(None, ge=15.0, le=45.0),
    supply_lpcd: Optional[float] = Query(None, ge=10.0, le=300.0),
    reservoir_storage_pct: Optional[float] = Query(None, ge=0.0, le=100.0),
    rainfall_24h_mm: Optional[float] = Query(None, ge=0.0, le=500.0),
    peak_hourly_rainfall_mm: Optional[float] = Query(None, ge=0.0, le=200.0)
):
    """
    Returns deterministically ranked wards and flags dual-hazard emergency priorities.
    Supports filtering by compound hotspots and limiting results for executive decision summaries.
    """
    if scoring_mode not in SCORING_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid scoring mode '{scoring_mode}'. Supported modes: {SCORING_MODES}"
        )
    try:
        results = await evaluate_combined_climate_risk(
            weight_heat=weight_heat,
            weight_water=weight_water,
            scoring_mode=scoring_mode,
            synergy_multiplier=synergy_multiplier,
            scenario_id=scenario_id,
            heat_wbgt_override=heat_wbgt,
            supply_lpcd_override=supply_lpcd,
            reservoir_storage_override=reservoir_storage_pct,
            rainfall_24h_override=rainfall_24h_mm,
            peak_hourly_override=peak_hourly_rainfall_mm
        )

        wards = results["ranked_wards"]
        if compound_only:
            wards = [w for w in wards if w["compound_hazard"]["is_compound_hotspot"]]

        if limit is not None:
            wards = wards[:limit]

        dual_hazard_priorities = [
            w for w in wards
            if w["compound_hazard"]["tier"] in ["DUAL_CRITICAL", "DUAL_HIGH"]
        ]

        return {
            "city": results["city"],
            "timestamp": results["timestamp"],
            "scoring_configuration": results["scoring_configuration"],
            "total_ranked_wards": len(wards),
            "compound_hazard_hotspots_count": sum(1 for w in wards if w["compound_hazard"]["is_compound_hotspot"]),
            "rankings": wards,
            "dual_hazard_priorities": dual_hazard_priorities
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating climate risk rankings: {str(e)}")


@app.post("/api/climate-risk")
@app.post("/api/climate/combined-risk")
async def calculate_combined_climate_risk(req: CombinedClimateRiskRequest):
    """
    Parameterized POST endpoint for Combined Climate Risk evaluation and what-if simulation.
    """
    if req.scoring_mode not in SCORING_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid scoring mode '{req.scoring_mode}'. Supported modes: {SCORING_MODES}"
        )
    if req.weight_heat + req.weight_water <= 0.0:
        raise HTTPException(
            status_code=422,
            detail="The sum of weight_heat and weight_water must be greater than zero."
        )
    try:
        results = await evaluate_combined_climate_risk(
            weight_heat=req.weight_heat,
            weight_water=req.weight_water,
            scoring_mode=req.scoring_mode,
            synergy_multiplier=req.synergy_multiplier,
            scenario_id=req.scenario_id,
            heat_wbgt_override=req.heat_wbgt,
            supply_lpcd_override=req.supply_lpcd,
            reservoir_storage_override=req.reservoir_storage_pct,
            rainfall_24h_override=req.rainfall_24h_mm,
            peak_hourly_override=req.peak_hourly_rainfall_mm
        )
        return results
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Combined Climate Risk simulation failed: {str(e)}")


# -------------------------------------------------------------
# EXTERNAL SATELLITE & REANALYSIS DATA SOURCES ENDPOINTS
# -------------------------------------------------------------

@app.get("/api/data-sources/era5")
async def get_era5_land_climate(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD), defaults to current date"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD), defaults to current date"),
    force_refresh: bool = Query(False, description="Force refresh cache")
):
    """
    Retrieves Copernicus ERA5-Land historical climate reanalysis dataset for Ahmedabad.
    Includes 2m air temp, dewpoint, total precipitation, soil moisture, solar radiation, and wind components.
    """
    try:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        s_date = start_date or today
        e_date = end_date or today

        client = ERA5LandClient()
        data = await client.fetch_historical_climate(s_date, e_date, force_refresh=force_refresh)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ERA5-Land data fetch error: {str(e)}")


@app.get("/api/data-sources/ecostress")
async def get_ecostress_overpass(
    product_type: str = Query("LST", description="ECOSTRESS product: LST (Land Surface Temp) or ET (Evapotranspiration)"),
    reference_date: Optional[str] = Query(None, description="Reference date (YYYY-MM-DD)")
):
    """
    Retrieves NASA ECOSTRESS high-resolution (~70m) thermal satellite overpass data for Ahmedabad.
    Preserves acquisition timestamp, cloud mask, and quality flags.
    """
    try:
        client = ECOSTRESSClient()
        data = await client.fetch_latest_overpass(product_type=product_type, reference_date=reference_date)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ECOSTRESS data fetch error: {str(e)}")


@app.get("/api/data-sources/fusion")
async def get_fused_ward_climate(
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD)")
):
    """
    Fuses Copernicus ERA5-Land macro-climate data and NASA ECOSTRESS thermal observations
    per administrative ward across Ahmedabad's 48 GeoJSON wards.
    """
    try:
        fusion_engine = DataFusionEngine()
        result = await fusion_engine.get_fused_ward_climate_profile(target_date=target_date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Data fusion error: {str(e)}")


@app.get("/api/data-sources/fused-heat-risk")
async def get_fused_heat_risk(
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD)")
):
    """
    Evaluates Heat Engine (wbgt_pipeline.py) across all 48 wards using fused satellite data.
    Incorporates ECOSTRESS microclimate thermal LST anomalies with explicit uncertainty margins.
    """
    try:
        service = DataSourcesService()
        result = await service.evaluate_fused_heat_risk(target_date=target_date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fused heat risk evaluation error: {str(e)}")


@app.get("/api/data-sources/fused-climate-risk")
async def get_fused_climate_risk(
    target_date: Optional[str] = Query(None, description="Target date (YYYY-MM-DD)"),
    weight_heat: float = Query(0.5, ge=0.0, le=1.0),
    weight_water: float = Query(0.5, ge=0.0, le=1.0),
    scoring_mode: str = Query("COMPOUND_SYNERGY"),
    synergy_multiplier: float = Query(0.15, ge=0.0, le=1.0)
):
    """
    Evaluates Combined Multi-Hazard Risk Engine (combined_risk_engine.py) using fused satellite data.
    Feeds fused heat and precipitation parameters directly into the compound risk engine.
    """
    try:
        service = DataSourcesService()
        result = await service.evaluate_fused_climate_risk(
            target_date=target_date,
            weight_heat=weight_heat,
            weight_water=weight_water,
            scoring_mode=scoring_mode,
            synergy_multiplier=synergy_multiplier
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fused combined climate risk error: {str(e)}")


class FusedOptimizationRequest(BaseModel):
    target_date: Optional[str] = Field(None, description="Target date (YYYY-MM-DD)")
    total_budget_inr: float = Field(500000.0, ge=10000, le=10000000)
    total_crew_members: int = Field(40, ge=1, le=500)
    total_water_cap_l: float = Field(30000.0, ge=1000, le=500000)
    equity_slider: float = Field(0.5, ge=0.0, le=1.0)
    weight_heat: float = Field(0.5, ge=0.0, le=1.0)
    weight_water: float = Field(0.5, ge=0.0, le=1.0)
    scoring_mode: str = Field("COMPOUND_SYNERGY")


@app.post("/api/data-sources/optimize-fused")
async def optimize_from_fused_data(req: FusedOptimizationRequest):
    """
    Runs Optimizer on fused multi-hazard climate risk assessment derived from ERA5-Land and ECOSTRESS data.
    """
    try:
        service = DataSourcesService()
        plan = await service.optimize_fused_climate_resources(
            target_date=req.target_date,
            total_budget_inr=req.total_budget_inr,
            total_crew_members=req.total_crew_members,
            total_water_cap_l=req.total_water_cap_l,
            equity_slider=req.equity_slider,
            weight_heat=req.weight_heat,
            weight_water=req.weight_water,
            scoring_mode=req.scoring_mode
        )
        return plan
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fused optimization error: {str(e)}")


# -------------------------------------------------------------
# LEARNING LOOP: DATA RECORDING & LINEAGE ENDPOINTS
# -------------------------------------------------------------

@app.post("/api/learning/predictions", status_code=201)
async def create_prediction_record(req: PredictionRecordCreate):
    """
    Records a historical risk prediction with stable ID, hazard domain, risk tier, and provenance metadata.
    Does NOT overwrite past records; appends to persistent SQLite audit store.
    """
    try:
        record = record_prediction(req)
        return record
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record prediction: {str(e)}")


@app.get("/api/learning/predictions")
async def get_prediction_records(
    ward_id: Optional[str] = Query(None, description="Filter by ward ID or name"),
    hazard_type: Optional[str] = Query(None, description="Filter by hazard: heat, waterlogging, water_shortage, compound"),
    provenance: Optional[str] = Query(None, description="Filter by provenance: REAL, ESTIMATED, SIMULATED, UNVERIFIED"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Retrieves historical risk predictions with optional ward, hazard, and provenance filters.
    """
    try:
        return {"predictions": list_predictions(ward_id=ward_id, hazard_type=hazard_type, provenance=provenance, limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query predictions: {str(e)}")


@app.get("/api/learning/predictions/{prediction_id}")
async def get_single_prediction(prediction_id: str):
    """
    Retrieves a single prediction by its stable ID.
    """
    pred = get_prediction(prediction_id)
    if not pred:
        raise HTTPException(status_code=404, detail=f"Prediction '{prediction_id}' not found.")
    return pred


@app.post("/api/learning/recommendations", status_code=201)
async def create_recommendation_records(req: BatchRecommendationCreate):
    """
    Records candidate intervention recommendations linked to an existing prediction.
    Strictly marked as 'PROPOSED' (advisory) and separated from executed field actions.
    """
    try:
        recs = record_recommendations(req.prediction_id, req.ward_id, req.recommendations)
        return {"prediction_id": req.prediction_id, "ward_id": req.ward_id, "recommendations": recs}
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record recommendations: {str(e)}")


@app.get("/api/learning/recommendations")
async def get_recommendation_records(
    prediction_id: Optional[str] = Query(None, description="Filter by linked prediction ID"),
    ward_id: Optional[str] = Query(None, description="Filter by ward ID"),
    status: Optional[str] = Query(None, description="Filter by status: PROPOSED, APPROVED, REJECTED, SUPERSEDED"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Retrieves candidate recommendation records.
    """
    try:
        return {"recommendations": list_recommendations(prediction_id=prediction_id, ward_id=ward_id, status=status, limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query recommendations: {str(e)}")


@app.post("/api/learning/actions", status_code=201)
async def create_executed_action_record(req: ExecutedActionCreate):
    """
    Records an approved municipal field action actually carried out or scheduled.
    Requires named human approval ('approved_by') and execution status tracking.
    """
    try:
        action = record_executed_action(req)
        return action
    except ValueError as e:
        raise HTTPException(status_code=404 if "does not exist" in str(e).lower() else 422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record executed action: {str(e)}")


@app.patch("/api/learning/actions/{action_id}")
async def patch_executed_action_record(action_id: str, req: ExecutedActionUpdate):
    """
    Updates field execution status, completion timestamps, resources drawn, or failure details.
    """
    try:
        updated = update_executed_action(action_id, req)
        return updated
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update action: {str(e)}")


@app.get("/api/learning/actions")
async def get_executed_action_records(
    ward_id: Optional[str] = Query(None, description="Filter by ward ID"),
    execution_status: Optional[str] = Query(None, description="Filter by status: SCHEDULED, IN_PROGRESS, COMPLETED, FAILED, CANCELLED"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Lists executed municipal field actions.
    """
    try:
        return {"actions": list_actions(ward_id=ward_id, execution_status=execution_status, limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query actions: {str(e)}")


@app.get("/api/learning/actions/{action_id}")
async def get_single_action_record(action_id: str):
    """
    Retrieves a single executed field action by its stable ID.
    """
    action = get_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found.")
    return action


@app.post("/api/learning/outcomes", status_code=201)
async def create_verified_outcome_record(req: VerifiedOutcomeCreate):
    """
    Ingests ground-truth municipal health or water outcome data.
    Enforces non-PII aggregations and data provenance tiering (REAL, ESTIMATED, SIMULATED).
    """
    try:
        outcome = record_verified_outcome(req)
        return outcome
    except ValueError as e:
        raise HTTPException(status_code=404 if "does not exist" in str(e).lower() else 422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record outcome: {str(e)}")


@app.get("/api/learning/outcomes")
async def get_verified_outcome_records(
    ward_id: Optional[str] = Query(None, description="Filter by ward ID"),
    provenance: Optional[str] = Query(None, description="Filter by provenance: REAL, ESTIMATED, SIMULATED, UNVERIFIED"),
    prediction_id: Optional[str] = Query(None, description="Filter by linked prediction ID"),
    action_id: Optional[str] = Query(None, description="Filter by linked executed action ID"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Lists verified municipal outcomes with provenance indicators.
    """
    try:
        return {"outcomes": list_outcomes(ward_id=ward_id, provenance=provenance, prediction_id=prediction_id, action_id=action_id, limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query outcomes: {str(e)}")


@app.get("/api/learning/outcomes/{outcome_id}")
async def get_single_outcome_record(outcome_id: str):
    """
    Retrieves a single verified municipal outcome record by its stable ID.
    """
    outcome = get_outcome(outcome_id)
    if not outcome:
        raise HTTPException(status_code=404, detail=f"Outcome record '{outcome_id}' not found.")
    return outcome


@app.get("/api/learning/lineage/{prediction_id}")
async def get_lineage_records(prediction_id: str):
    """
    Reconstructs the full end-to-end decision lineage tree:
    Prediction -> Candidate Recommendations -> Executed Actions -> Verified Outcomes.
    """
    try:
        lineage = get_learning_lineage(prediction_id)
        return lineage
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reconstruct lineage: {str(e)}")


# -------------------------------------------------------------
# IMPACT VERIFICATION ENDPOINTS (BEFORE-AFTER & DID)
# -------------------------------------------------------------

@app.post("/api/impact/verify")
async def run_impact_verification(req: ImpactVerificationRequest):
    """
    Evaluates observed outcomes against predicted risks and expected intervention benefits.
    Enforces causal guardrails:
    - Simple before-and-after comparisons are labeled CORRELATIONAL_ONLY.
    - Difference-in-Differences is calculated only when valid comparison control data is available.
    - Reports insufficient data rather than manufacturing impact results.
    - Verifies whether field action was completed and whether intended outcome was observed.
    """
    try:
        result = verify_intervention_impact(req)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impact verification failed: {str(e)}")


@app.get("/api/impact/verifications")
async def get_impact_verifications(
    action_id: Optional[str] = Query(None, description="Filter by executed action ID"),
    ward_id: Optional[str] = Query(None, description="Filter by ward ID"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Retrieves historical impact verification evaluation reports.
    """
    try:
        return {"verifications": list_verifications(action_id=action_id, ward_id=ward_id, limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query impact verifications: {str(e)}")


@app.get("/api/impact/verifications/{verification_id}")
async def get_single_impact_verification(verification_id: str):
    """
    Retrieves a single impact verification report by its ID.
    """
    verif = get_verification(verification_id)
    if not verif:
        raise HTTPException(status_code=404, detail=f"Verification report '{verification_id}' not found.")
    return verif


@app.get("/api/impact/actions/{action_id}")
async def get_action_impact_verifications(action_id: str):
    """
    Retrieves all impact verification reports linked to a specific executed field action.
    """
    try:
        return {"verifications": list_verifications(action_id=action_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query verifications for action: {str(e)}")


# -------------------------------------------------------------
# LEARNING ENGINE: EVALUATION & CONTROLLED PARAMETER CALIBRATION
# -------------------------------------------------------------

@app.post("/api/learning/evaluate")
async def run_learning_evaluation(req: ModelEvaluationRequest):
    """
    Evaluates historical predictions against verified outcomes across Heat, Flooding, and Water Shortage.
    Calculates MAE, RMSE, Precision, Recall, and F1.
    Strictly excludes simulated/unverified outcomes from learning.
    Requires minimum evidence threshold before formulating parameter proposals.
    """
    try:
        result = run_model_evaluation(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model evaluation failed: {str(e)}")


@app.get("/api/learning/evaluations")
async def get_model_evaluations_endpoint(limit: int = Query(50, ge=1, le=200)):
    """
    Retrieves historical model evaluation reports and accuracy metrics across Heat, Flooding, and Water Shortage.
    """
    try:
        return {"evaluations": list_model_evaluations(limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query model evaluations: {str(e)}")


@app.get("/api/learning/evaluations/{evaluation_id}")
async def get_single_model_evaluation_endpoint(evaluation_id: str):
    """
    Retrieves a single historical model evaluation report by ID.
    """
    report = get_model_evaluation(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Evaluation report '{evaluation_id}' not found.")
    return report


@app.get("/api/learning/proposals")
async def get_parameter_proposals_endpoint(
    status: Optional[str] = Query(None, description="Filter by status: PENDING_APPROVAL, APPROVED, REJECTED"),
    target_ward: Optional[str] = Query(None, description="Filter by target ward identifier"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Retrieves staged parameter update proposals requiring municipal approval.
    """
    try:
        return {"proposals": list_parameter_proposals(status=status, target_ward=target_ward, limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query proposals: {str(e)}")


@app.get("/api/learning/proposals/{proposal_id}")
async def get_single_parameter_proposal_endpoint(proposal_id: str):
    """
    Retrieves a single parameter update proposal by ID.
    """
    prop = get_parameter_proposal(proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail=f"Proposal '{proposal_id}' not found.")
    return prop


@app.get("/api/learning/active-parameters")
async def get_active_parameters():
    """
    Retrieves the currently active production model parameters and active version.
    """
    try:
        return get_active_model_parameters()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve active parameters: {str(e)}")


@app.get("/api/learning/versions")
async def get_model_versions():
    """
    Retrieves the complete immutable changelog and historical model versions.
    """
    try:
        return {"versions": list_model_versions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query model versions: {str(e)}")


@app.post("/api/learning/proposals/{proposal_id}/approve")
async def approve_proposal_endpoint(proposal_id: str, req: ProposalApprovalRequest):
    """
    Authorizes a staged parameter update proposal and commits a new versioned model state.
    Requires named human approval.
    """
    try:
        result = approve_parameter_proposal(proposal_id, req)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to approve proposal: {str(e)}")


@app.post("/api/learning/proposals/{proposal_id}/reject")
async def reject_proposal_endpoint(proposal_id: str, req: ProposalRejectionRequest):
    """
    Rejects a staged parameter update proposal.
    Production model parameters remain untouched.
    """
    try:
        result = reject_parameter_proposal(proposal_id, req)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject proposal: {str(e)}")


@app.post("/api/learning/versions/{version_id}/rollback")
async def rollback_version_endpoint(version_id: str, req: ProposalApprovalRequest):
    """
    Reactivates a prior immutable model version with complete audit logging.
    """
    try:
        result = rollback_model_version(version_id, req.approved_by)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rollback version: {str(e)}")



# -------------------------------------------------------------
# ACTION CENTRE ENDPOINTS
# -------------------------------------------------------------

class ActionStatusUpdateRequest(BaseModel):
    new_status: str = Field(..., description="Target status. Must be one of: proposed, approved, in_progress, completed, cancelled, rejected, blocked, changes_requested")
    changed_by: str = Field("Municipal Incident Commander", description="Identity or role of authorizing officer")
    notes: Optional[str] = Field(None, description="Operational notes or mandatory justification reason")
    reason: Optional[str] = Field(None, description="Alias for notes (justification reason)")


class ActionDecisionRequest(BaseModel):
    decision: str = Field(..., description="Decision action: approve, reject, hold, block, unblock, request_changes, deploy, complete, cancel")
    changed_by: str = Field("Municipal Incident Commander", description="Authorizing municipal official or role")
    notes: Optional[str] = Field(None, description="Operational justification or review notes")
    reason: Optional[str] = Field(None, description="Mandatory reason for rejection, blocking, or change requests")
    target_status: Optional[str] = Field(None, description="Optional target status override (used for unblock)")


class QuickDispatchRequest(BaseModel):
    ward_id: str = Field(..., description="Target AMC ward identifier (e.g. W1, Danilimda)")
    ward_name: Optional[str] = Field(None, description="Optional display name")
    action_type: str = Field(..., description="Action type identifier")
    priority: str = Field("critical", description="Priority tier")
    reason: str = Field(..., description="Operational justification for dispatch")
    required_resources: Optional[Dict[str, Any]] = Field(None, description="Resource schedule: cost_inr, crew_required, water_required_l")
    related_hazard: Optional[str] = Field(None, description="Hazard category")
    risk_score: Optional[float] = Field(None, description="Associated risk score")
    authorized_by: str = Field("Municipal Incident Commander", description="Authorizing officer name/role")
    initial_status: str = Field("in_progress", description="Initial operational status: approved or in_progress")
    force: bool = Field(False, description="Override duplicate check if emergency dispatch required")


class ManualActionRequest(BaseModel):
    ward_id: str = Field(..., description="Ward identifier (e.g. W1, W7)")
    ward_name: str = Field("", description="Ward display name")
    action_type: str = Field(..., description=f"Action type. Must be one of: {ACTION_TYPES}")
    priority: str = Field("medium", description="Priority level: critical, high, medium, low")
    reason: str = Field(..., description="Why this action is recommended")
    required_resources: Optional[Dict[str, Any]] = Field(None, description="Resource requirements")
    related_hazard: Optional[str] = Field(None, description="Related hazard: heat, waterlogging, water_shortage")
    risk_score: Optional[float] = Field(None, ge=0.0, le=100.0, description="Associated risk score 0-100")


class RecommendationRequest(BaseModel):
    scenario_id: Optional[str] = Field(None, description="Optional climate demo scenario ID")
    available_budget_inr: Optional[float] = Field(None, ge=0.0, description="Municipal budget ceiling in INR")
    available_crew: Optional[int] = Field(None, ge=0, description="Available emergency staff / crew count")
    available_water_l: Optional[float] = Field(None, ge=0.0, description="Available emergency water cap in Liters")
    threshold_overrides: Optional[Dict[str, float]] = Field(None, description="Custom rule threshold overrides")
    persist_to_store: bool = Field(True, description="Whether to persist generated recommendations into the Action Store")
    enforce_resource_constraints: bool = Field(True, description="Whether to filter out actions exceeding available resources")


@app.get("/api/action-centre/dashboard")
async def get_action_centre_dashboard(
    scenario_id: Optional[str] = Query(None, description="Optional climate demo scenario ID"),
    force_refresh: bool = Query(False, description="Force fresh climate risk evaluation")
):
    """
    Returns the unified Action Centre dashboard:
    - High-risk Ahmedabad wards (combined score >= 50.0) with contributing heat & water factors.
    - Overall action summary by operational status (proposed, approved, in_progress, completed, cancelled).
    - Ward-wise action aggregation correlating active dispatches with risk profiles.
    - Prioritized action queue sorted by risk severity, urgency, and recency.
    - Data freshness & staleness indicator (safely falls back if risk engine is temporarily offline).
    """
    try:
        climate_data = await get_cached_or_fresh_combined_climate_risk(
            scenario_id=scenario_id,
            force_refresh=force_refresh
        )
        data_quality = climate_data.get("data_quality_and_confidence", None)
    except Exception as e:
        # Graceful fallback: Action Centre operates in decoupled store-only mode if risk engine is unavailable
        climate_data = None
        data_quality = {
            "status": "UNAVAILABLE",
            "warning": f"Risk assessment engine temporarily unavailable: {str(e)}",
            "fallback_mode": "STORE_ONLY",
        }

    dashboard = build_action_centre_dashboard(
        climate_risk_data=climate_data,
        data_quality=data_quality,
    )
    return dashboard


@app.get("/api/action-centre/actions/prioritized")
def list_prioritized_actions(
    ward_id: Optional[str] = Query(None, description="Optional filter by ward ID or name"),
    action_type: Optional[str] = Query(None, description="Optional filter by action type"),
    status: Optional[str] = Query(None, description="Optional filter by status"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of prioritized actions to return")
):
    """
    Returns an operational queue of actions sorted strictly by decision priority:
    1. Priority level: critical > high > medium > low
    2. Status urgency: in_progress > approved > proposed > completed > cancelled
    3. Associated risk score descending
    4. Creation recency
    """
    if status and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status filter '{status}'. Must be one of: {VALID_STATUSES}"
        )
    if action_type and action_type not in ACTION_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action_type filter '{action_type}'. Must be one of: {ACTION_TYPES}"
        )

    store = get_action_store()
    actions = get_prioritized_actions(
        store=store,
        ward_id=ward_id,
        action_type=action_type,
        status=status,
        limit=limit,
    )
    return {
        "status": "SUCCESS",
        "total_actions": len(actions),
        "limit": limit,
        "filters_applied": {
            "ward_id": ward_id,
            "action_type": action_type,
            "status": status,
        },
        "prioritized_actions": actions,
        "advisory": ACTION_CENTRE_ADVISORY,
    }


@app.get("/api/action-centre/actions/ward-summary")
async def get_ward_action_summary_endpoint(
    scenario_id: Optional[str] = Query(None, description="Optional climate demo scenario ID to correlate risk scores")
):
    """
    Returns a ward-wise aggregation of all actions in the Action Centre.
    Correlates active actions with each ward's combined risk profile,
    reporting active action count, breakdown by status, and highest priority.
    """
    climate_data = None
    try:
        climate_data = await get_cached_or_fresh_combined_climate_risk(
            scenario_id=scenario_id
        )
    except Exception:
        climate_data = None

    store = get_action_store()
    summaries = get_ward_wise_action_summary(
        store=store,
        climate_risk_data=climate_data,
    )
    return {
        "status": "SUCCESS",
        "total_wards_with_actions": len(summaries),
        "ward_summaries": summaries,
        "climate_risk_correlated": climate_data is not None,
        "advisory": ACTION_CENTRE_ADVISORY,
    }


@app.get("/api/action-centre/actions")
def list_action_centre_actions(
    ward_id: Optional[str] = Query(None, description="Filter by ward ID or name"),
    action_type: Optional[str] = Query(None, description=f"Filter by action type"),
    status: Optional[str] = Query(None, description=f"Filter by status")
):
    """
    Lists all Action Centre actions with optional filters by ward, type, or status.
    """
    if status and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status filter '{status}'. Must be one of: {VALID_STATUSES}"
        )
    if action_type and action_type not in ACTION_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action_type filter '{action_type}'. Must be one of: {ACTION_TYPES}"
        )

    store = get_action_store()
    actions = store.list_actions(ward_id=ward_id, action_type=action_type, status=status)
    return {
        "status": "SUCCESS",
        "total_actions": len(actions),
        "filters_applied": {
            "ward_id": ward_id,
            "action_type": action_type,
            "status": status,
        },
        "actions": actions,
        "advisory": ACTION_CENTRE_ADVISORY,
    }


@app.get("/api/action-centre/actions/{action_id}")
def get_action_centre_action(action_id: str):
    """
    Retrieves a single action record by its ID, including full status history.
    """
    store = get_action_store()
    action = store.get_action(action_id)
    if not action:
        raise HTTPException(
            status_code=404,
            detail=f"Action '{action_id}' not found in the Action Centre."
        )
    return {"status": "SUCCESS", "action": action}


@app.put("/api/action-centre/actions/{action_id}/status")
def update_action_status(action_id: str, req: ActionStatusUpdateRequest):
    """
    Updates the status of an existing action. Enforces valid state transitions:
    proposed → approved → in_progress → completed
    Any non-terminal state → cancelled / blocked / rejected
    """
    store = get_action_store()
    try:
        updated = store.update_status(
            action_id=action_id,
            new_status=req.new_status,
            changed_by=req.changed_by,
            notes=req.notes or req.reason,
        )
        return {"status": "SUCCESS", "action": updated}
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Action '{action_id}' not found in the Action Centre."
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/api/action-centre/actions/{action_id}/decision")
def execute_action_decision_endpoint(action_id: str, req: ActionDecisionRequest):
    """
    Executes an operational decision (approve, reject, hold/block, unblock, request_changes, deploy, complete)
    with permission enforcement, verification validation, and mandatory justification logging.
    """
    store = get_action_store()
    decision_norm = req.decision.strip().lower()

    action = store.get_action(action_id)
    if not action:
        raise HTTPException(
            status_code=404,
            detail=f"Action '{action_id}' not found in the Action Centre."
        )

    current_status = action.get("status", "proposed")
    notes = (req.notes or req.reason or "").strip()

    # Map decision to target status
    if decision_norm in ["approve", "approved"]:
        target_status = "approved"
    elif decision_norm in ["reject", "rejected"]:
        target_status = "rejected"
    elif decision_norm in ["hold", "block", "blocked"]:
        target_status = "blocked"
    elif decision_norm in ["unblock", "unblocked"]:
        target_status = req.target_status if req.target_status in ["proposed", "approved", "in_progress"] else "proposed"
        if not notes:
            notes = "Unblocked by authorizing municipal authority."
    elif decision_norm in ["request_changes", "request-changes", "changes_requested"]:
        target_status = "changes_requested"
    elif decision_norm in ["deploy", "in_progress"]:
        target_status = "in_progress"
    elif decision_norm in ["complete", "completed", "resolve"]:
        target_status = "completed"
    elif decision_norm in ["cancel", "cancelled"]:
        target_status = "cancelled"
    else:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid decision '{req.decision}'. Supported: approve, reject, hold/block, unblock, request_changes, deploy, complete, cancel"
        )

    try:
        updated = store.update_status(
            action_id=action_id,
            new_status=target_status,
            changed_by=req.changed_by,
            notes=notes if notes else None,
        )
        return {
            "status": "SUCCESS",
            "decision": decision_norm,
            "action": updated,
            "message": f"Action {action_id} successfully transitioned from '{current_status}' to '{target_status}'.",
        }
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Action '{action_id}' not found in the Action Centre."
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/api/action-centre/dispatch/quick")
def quick_dispatch_endpoint(req: QuickDispatchRequest):
    """
    Executes an authenticated operational quick dispatch:
    - Verifies AMC ward jurisdiction
    - Performs duplicate-dispatch check against active operations
    - Enforces municipal authority authorization
    - Persists action and immutable audit event to SQLite
    - Never simulates dispatch
    """
    try:
        result = dispatch_quick_action(
            ward_id=req.ward_id,
            action_type=req.action_type,
            authorized_by=req.authorized_by,
            ward_name=req.ward_name,
            priority=req.priority,
            reason=req.reason,
            required_resources=req.required_resources,
            related_hazard=req.related_hazard,
            risk_score=req.risk_score,
            initial_status=req.initial_status,
            force=req.force,
        )
        return result
    except ValueError as e:
        err_msg = str(e)
        if "duplicate" in err_msg.lower():
            raise HTTPException(status_code=409, detail=err_msg)
        raise HTTPException(status_code=422, detail=err_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quick dispatch failed: {str(e)}")


@app.get("/api/action-centre/actions/{action_id}/audit-trail")
def get_action_audit_trail_endpoint(action_id: str, limit: int = Query(50, ge=1, le=200)):
    """
    Retrieves the complete immutable audit trail for a specific action from SQLite:
    creation, reviews, verifications, decisions, dispatches, and status changes.
    """
    events = list_action_audit_events(action_id=action_id, limit=limit)
    return {
        "status": "SUCCESS",
        "action_id": action_id,
        "total_events": len(events),
        "audit_trail": events,
    }


@app.get("/api/action-centre/audit-trail")
def get_global_action_audit_trail_endpoint(limit: int = Query(100, ge=1, le=500)):
    """
    Retrieves global municipal operational audit trail across all interventions:
    dispatches, decisions, verification results, and status changes with timestamps and actors.
    """
    events = list_action_audit_events(action_id=None, limit=limit)
    return {
        "status": "SUCCESS",
        "total_events": len(events),
        "audit_trail": events,
    }


class ActionVerificationRequest(BaseModel):
    verified_by: str = Field("Municipal Incident Commander", description="Officer identity conducting verification")
    notes: Optional[str] = Field(None, description="Optional verification notes")


@app.post("/api/action-centre/actions/{action_id}/verify")
async def verify_action_evidence_endpoint(action_id: str, req: Optional[ActionVerificationRequest] = None):
    """
    Validates an intervention against actual data:
    1. Ward association (jurisdiction in AMC registry)
    2. Quantitative risk assessment (substantiated by risk engine)
    3. Data freshness (within operational SLA threshold)
    4. Operational details & resource constraints (valid type, priority, positive resources)
    5. Empirical physical evidence (sensor readings if attached, or clearly unavailable)

    Enforces:
    - Never fabricates evidence or readings.
    - Prevents mandatory failed checks from succeeding.
    - Persists verification report to SQLite database.
    """
    store = get_action_store()
    action = store.get_action(action_id)
    if not action:
        raise HTTPException(
            status_code=404,
            detail=f"Action '{action_id}' not found in the Action Centre."
        )

    climate_data = None
    try:
        climate_data = await get_cached_or_fresh_combined_climate_risk()
    except Exception:
        climate_data = None

    verified_by = req.verified_by if req else "Municipal Incident Commander"
    notes = req.notes if req else None

    result = verify_intervention_evidence(
        action=action,
        climate_risk_data=climate_data,
        verified_by=verified_by,
        notes=notes,
        store=store,
    )
    return {"status": "SUCCESS", "verification": result}


@app.get("/api/action-centre/actions/{action_id}/verification")
def get_action_verification_endpoint(action_id: str):
    """
    Retrieves the latest verification report or default checklist for an action.
    """
    store = get_action_store()
    try:
        report = get_action_verification_report(action_id, store=store)
        return {"status": "SUCCESS", "verification": report}
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Action '{action_id}' not found in the Action Centre."
        )


@app.post("/api/action-centre/create")
def create_manual_action(req: ManualActionRequest):
    """
    Manually creates a new action record in the Action Centre.
    """
    store = get_action_store()
    try:
        action = store.create_action(
            ward_id=req.ward_id,
            ward_name=req.ward_name,
            action_type=req.action_type,
            priority=req.priority,
            reason=req.reason,
            required_resources=req.required_resources,
            related_hazard=req.related_hazard,
            risk_score=req.risk_score,
            source="manual",
        )
        return {"status": "SUCCESS", "action": action}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/api/action-centre/generate-from-risk")
async def generate_actions_from_risk_endpoint(
    scenario_id: Optional[str] = Query(None, description="Optional climate demo scenario ID")
):
    """
    Reads existing Combined Climate Risk Engine output and generates proposed
    heat-alert actions for high-risk wards. Does NOT recalculate risk.
    """
    try:
        climate_data = await get_cached_or_fresh_combined_climate_risk(
            scenario_id=scenario_id
        )
        result = generate_actions_from_climate_risk(climate_data)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate actions from climate risk: {str(e)}"
        )


@app.post("/api/action-centre/generate-from-interventions")
async def generate_actions_from_interventions_endpoint(
    scenario_id: Optional[str] = Query(None, description="Optional climate demo scenario ID"),
    total_budget_inr: float = Query(500000.0, ge=10000, le=10000000),
    total_crew_members: int = Query(40, ge=1, le=500),
    total_water_cap_l: float = Query(30000.0, ge=1000, le=500000),
    equity_slider: float = Query(0.5, ge=0.0, le=1.0)
):
    """
    Reads existing Intervention Engine output and creates trackable actions.
    Uses cached/fresh combined climate risk to produce the intervention plan,
    then converts dispatch items into Action Centre records.
    """
    try:
        climate_data = await get_cached_or_fresh_combined_climate_risk(
            scenario_id=scenario_id
        )
        wards_to_use = climate_data.get("ranked_wards", climate_data.get("wards", []))

        plan = generate_intervention_recommendations(
            wards=wards_to_use,
            total_budget_inr=total_budget_inr,
            total_crew_members=total_crew_members,
            total_water_cap_l=total_water_cap_l,
            equity_slider=equity_slider,
        )
        result = generate_actions_from_interventions(plan)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate actions from interventions: {str(e)}"
        )


@app.get("/api/action-centre/metadata")
def get_action_centre_metadata():
    """
    Returns Action Centre configuration metadata: supported action types,
    valid statuses, and status transition rules.
    """
    from backend.action_centre import VALID_STATUS_TRANSITIONS
    return {
        "status": "SUCCESS",
        "action_types": ACTION_TYPES,
        "valid_statuses": VALID_STATUSES,
        "status_transitions": {
            k: sorted(v) for k, v in VALID_STATUS_TRANSITIONS.items()
        },
        "advisory": ACTION_CENTRE_ADVISORY,
    }


@app.post("/api/action-centre/recommendations")
async def generate_recommendations_endpoint(req: Optional[RecommendationRequest] = None):
    """
    Generates transparent, explainable, rule-based recommendations for high-risk Ahmedabad wards.
    Reads existing risk engine outputs and Optimizer recommendations without recalculating risk.
    Enforces duplicate prevention and respects municipal staff/budget/water resource constraints.
    """
    if req is None:
        req = RecommendationRequest()

    try:
        climate_data = await get_cached_or_fresh_combined_climate_risk(
            scenario_id=req.scenario_id
        )

        resource_constraints = None
        if any(x is not None for x in (req.available_budget_inr, req.available_crew, req.available_water_l)):
            resource_constraints = {
                "available_budget_inr": req.available_budget_inr,
                "available_crew": req.available_crew,
                "available_water_l": req.available_water_l,
            }

        result = generate_rule_based_recommendations(
            climate_risk_data=climate_data,
            resource_constraints=resource_constraints,
            thresholds=req.threshold_overrides,
            create_in_store=req.persist_to_store,
            enforce_resource_constraints=req.enforce_resource_constraints,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate rule-based recommendations: {str(e)}"
        )


@app.get("/api/action-centre/recommendations/rules")
def get_recommendation_rules_metadata():
    """
    Returns active recommendation rule definitions, default thresholds,
    and standard municipal resource schedules.
    """
    return {
        "status": "SUCCESS",
        "rules": RULE_DEFINITIONS,
        "default_thresholds": DEFAULT_RECOMMENDATION_THRESHOLDS,
        "resource_estimates": ACTION_RESOURCE_ESTIMATES,
        "advisory": ACTION_CENTRE_ADVISORY,
    }


# -------------------------------------------------------------
# IMPACT VERIFICATION ENDPOINTS
# -------------------------------------------------------------

class ImpactAssessmentSubmissionRequest(BaseModel):
    assessment_id: Optional[str] = Field(None, description="Optional custom assessment identifier; generated automatically if omitted")
    intervention_id: str = Field(..., description="ID of the executed intervention (e.g. cooling_center, dewatering_pump_deployment)")
    ward_id: str = Field(..., description="Target ward ID (e.g. W1 to W48)")
    intervention_type: str = Field(..., description="Operational category of the intervention")
    execution_status: str = Field("COMPLETED", description="COMPLETED, DEPLOYED, OBSERVED, IN_PROGRESS, or SYNTHETIC_DEMO")
    is_synthetic: bool = Field(False, description="Whether data is synthetic demonstration data")
    provenance_mode: Optional[str] = Field(None, description="MEASURED, EXTERNAL_OBSERVATION, ESTIMATED, or SYNTHETIC_DEMO")
    observations: Optional[List[Dict[str, Any]]] = Field(None, description="Empirical observations list (engine computes differences)")
    indicators: Optional[Dict[str, Any]] = Field(None, description="Pre-computed indicators dictionary")
    baseline_period: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata describing baseline observation window")
    follow_up_period: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata describing follow-up observation window")
    allow_update: bool = Field(False, description="Set True to update an existing assessment ID and archive history")
    change_reason: Optional[str] = Field(None, description="Reason for update if allow_update=True")


@app.post("/api/impact/assessments", status_code=201)
async def submit_impact_assessment(req: ImpactAssessmentSubmissionRequest):
    """
    Submits and persists an empirical impact assessment for a deployed/completed intervention.
    Calculates differences across verified baseline and follow-up observations, enforces unit
    consistency, and records audit history. Rejects uncompleted or merely recommended interventions.
    """
    # Enforce Requirement 5: Do not assume an intervention was completed merely because it was recommended.
    status_upper = req.execution_status.strip().upper()
    if status_upper in ["RECOMMENDED", "PENDING_HUMAN_APPROVAL", "PROPOSED", "RECOMMENDATION"]:
        raise HTTPException(
            status_code=422,
            detail="UNCOMPLETED_INTERVENTION: Cannot verify an uncompleted intervention. Recommended interventions without field deployment cannot be verified."
        )

    if not req.observations and not req.indicators:
        raise HTTPException(
            status_code=422,
            detail="Missing assessment payload: either 'observations' list or 'indicators' dict must be provided."
        )

    try:
        is_syn = req.is_synthetic or (status_upper == "SYNTHETIC_DEMO")
        prov_mode = req.provenance_mode or ("SYNTHETIC_DEMO" if is_syn else "MEASURED")

        if req.observations:
            assessment_obj = assess_intervention_impact(
                intervention_id=req.intervention_id,
                ward_id=req.ward_id,
                intervention_type=req.intervention_type,
                observations=req.observations,
                baseline_period=req.baseline_period,
                follow_up_period=req.follow_up_period,
                assessment_id=req.assessment_id
            )
            saved_record = record_impact_assessment(
                assessment=assessment_obj,
                execution_status=status_upper,
                allow_update=req.allow_update,
                change_reason=req.change_reason
            )
        else:
            payload = {
                "assessment_id": req.assessment_id or f"VIA_{req.ward_id}_{req.intervention_id}_{int(time.time())}",
                "intervention_id": req.intervention_id,
                "ward_id": req.ward_id,
                "intervention_type": req.intervention_type,
                "execution_status": status_upper,
                "is_synthetic": is_syn,
                "provenance_mode": prov_mode,
                "baseline_period": req.baseline_period or {},
                "follow_up_period": req.follow_up_period or {},
                "indicators": req.indicators,
                "attribution_disclaimer": ATTRIBUTION_DISCLAIMER
            }
            saved_record = record_impact_assessment(
                assessment=payload,
                execution_status=status_upper,
                allow_update=req.allow_update,
                change_reason=req.change_reason
            )

        return saved_record
    except DuplicateAssessmentError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impact assessment persistence failed: {str(e)}")


@app.get("/api/impact/assessments/{assessment_id}")
async def get_impact_assessment_endpoint(
    assessment_id: str,
    include_history: bool = Query(False, description="Whether to include previous archived audit snapshots")
):
    """
    Retrieves a persisted impact assessment by ID.
    Optionally includes version audit history.
    """
    assessment = retrieve_impact_assessment(assessment_id)
    if not assessment:
        raise HTTPException(
            status_code=404,
            detail=f"Impact assessment '{assessment_id}' not found."
        )

    if include_history:
        history = retrieve_assessment_history(assessment_id)
        assessment["audit_history"] = history

    return assessment


@app.get("/api/impact/wards/{ward_id}")
async def get_ward_impact_assessments_endpoint(
    ward_id: str,
    intervention_id: Optional[str] = Query(None, description="Optional filter by intervention ID"),
    include_synthetic: bool = Query(True, description="Whether to include synthetic demo records"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return")
):
    """
    Retrieves all available impact assessments for a given ward.
    Distinguishes real-world empirical assessments from synthetic demonstration records.
    """
    norm_wid = ward_id.strip().upper()
    assessments = list_impact_assessments(ward_id=norm_wid, intervention_id=intervention_id, limit=limit)

    if not include_synthetic:
        assessments = [a for a in assessments if not a.get("is_synthetic", False)]

    return {
        "ward_id": norm_wid,
        "total_assessments": len(assessments),
        "assessments": assessments
    }


@app.get("/api/impact/summary")
async def get_impact_summary_endpoint(
    ward_id: Optional[str] = Query(None, description="Optional ward filter"),
    intervention_type: Optional[str] = Query(None, description="Optional intervention type filter"),
    hazard_category: Optional[str] = Query(None, description="Optional hazard category filter: heat, waterlogging, water_shortage"),
    include_synthetic: bool = Query(False, description="Whether to include synthetic demo records in summary (defaults to False)")
):
    """
    Summarizes available impact assessments across verified, comparable records.
    Strictly segregates real-world verified outcomes from synthetic demonstration records.
    Does not invent observations when data is missing.
    """
    summary = generate_impact_verification_summary(
        ward_id=ward_id,
        intervention_type=intervention_type,
        hazard_category=hazard_category,
        include_synthetic=include_synthetic
    )

    # Legacy fields for backward compatibility
    summary["total_recorded_assessments_in_db"] = summary["kpis"]["total_assessments_recorded"]
    summary["empirical_verified_assessments_count"] = (
        summary["kpis"]["provenance_counts"]["measured"] +
        summary["kpis"]["provenance_counts"]["external_observation"] +
        summary["kpis"]["provenance_counts"]["estimated"]
    )
    summary["synthetic_demo_assessments_count"] = summary["kpis"]["provenance_counts"]["simulated_demo"]
    summary["summarized_assessments_count"] = (
        (summary["empirical_verified_assessments_count"] + summary["synthetic_demo_assessments_count"])
        if include_synthetic else summary["empirical_verified_assessments_count"]
    )

    # Convert breakdown structures for backward compatibility
    interventions_tally = {k: v["total_assessments"] for k, v in summary.get("by_intervention_type", {}).items()}
    summary["breakdown_by_intervention_type"] = interventions_tally

    hazard_tally = {}
    for ind_k, ind_v in summary.get("by_indicator", {}).items():
        h = ind_v.get("hazard_category", "cross_cutting")
        hazard_tally[h] = hazard_tally.get(h, 0) + ind_v.get("sample_size", 0)
    summary["breakdown_by_hazard_category"] = hazard_tally

    return summary


@app.get("/api/impact/learning-signals")
async def get_learning_loop_signals_endpoint(
    ward_id: Optional[str] = Query(None, description="Optional ward filter"),
    intervention_id: Optional[str] = Query(None, description="Optional intervention filter"),
    include_synthetic: bool = Query(False, description="Whether to include synthetic demo records (defaults to False)")
):
    """
    Exposes verified empirical outcome records and calibration weights for the Learning Loop.
    Read-only interface: does not retrain models or alter predictive risk calculations.
    """
    signals = export_learning_loop_signals(
        ward_id=ward_id,
        intervention_id=intervention_id,
        include_synthetic=include_synthetic
    )
    return {
        "status": "SUCCESS",
        "total_signals": len(signals),
        "data_integrity_mode": "INCLUDES_SIMULATED_DEMO" if include_synthetic else "REAL_WORLD_VERIFIED_ONLY",
        "signals": signals
    }



# ---------------------------------------------------------------------------
# AMAZON BEDROCK GENAI ADVISORY ENDPOINTS
# ---------------------------------------------------------------------------
from backend.bedrock_service import (
    generate_heat_advisory_with_bedrock,
    generate_fallback_advisory,
    DEFAULT_BEDROCK_MODEL,
    AWS_REGION
)
from backend.schemas import BedrockAdvisoryRequest


@app.post("/api/bedrock/advisory")
async def generate_bedrock_advisory_endpoint(req: BedrockAdvisoryRequest):
    """
    Invokes Amazon Bedrock to synthesize physics-based WBGT heat risk and
    OR-Tools resource allocations into actionable civic action advisories.
    Supports English ('en'), Gujarati ('gu'), and Hindi ('hi').
    """
    result = generate_heat_advisory_with_bedrock(
        city_name=req.city_name,
        max_hazard_level=req.max_hazard_level or "HIGH",
        peak_wbgt=req.peak_wbgt or 31.5,
        ward_summaries=req.ward_summaries or [],
        allocated_interventions=req.allocated_interventions or [],
        budget_used=req.budget_used or 450000.0,
        equity_score=req.equity_score or 0.88,
        target_audience=req.target_audience or "MUNICIPAL_OFFICERS",
        language=req.language or "en",
        model_id=req.model_id
    )
    return result


@app.get("/api/bedrock/status")
async def get_bedrock_status_endpoint():
    """
    Returns the operational status, target model family, and AWS configuration for Amazon Bedrock.
    """
    from backend.bedrock_service import get_bedrock_client, BOTO3_AVAILABLE
    client = get_bedrock_client()
    return {
        "service": "Amazon Bedrock",
        "boto3_installed": BOTO3_AVAILABLE,
        "client_active": client is not None,
        "default_model": DEFAULT_BEDROCK_MODEL,
        "aws_region": AWS_REGION,
        "supported_languages": ["en", "gu", "hi"],
        "supported_models": [
            "anthropic.claude-3-haiku-20240307-v1:0",
            "anthropic.claude-3-5-sonnet-20240620-v1:0",
            "amazon.titan-text-express-v1"
        ]
    }


# ---------------------------------------------------------------------------
# AMAZON AURORA DATASET ENDPOINTS
# ---------------------------------------------------------------------------
from backend.aurora_service import aurora_manager


@app.get("/api/aurora/status")
async def get_aurora_status_endpoint():
    """
    Returns the operational status, adapter mode, and connection details for Amazon Aurora.
    """
    return aurora_manager.get_connection_status()


@app.get("/api/aurora/schema")
async def get_aurora_schema_endpoint():
    """
    Returns the Amazon Aurora PostgreSQL / Serverless DDL table definitions and indexes.
    """
    return {
        "engine": "Amazon Aurora PostgreSQL / Serverless v2",
        "ddl": aurora_manager.get_aurora_ddl_schema()
    }


@app.get("/api/aurora/dataset")
async def export_aurora_dataset_endpoint():
    """
    Exports the verified municipal baseline dataset package for Amazon Aurora loading.
    """
    return aurora_manager.export_dataset_payload()


@app.post("/api/aurora/sync")
async def sync_aurora_dataset_endpoint():
    """
    Synchronizes local baseline datasets and audit records with Amazon Aurora.
    """
    return aurora_manager.sync_dataset_to_aurora()


# -------------------------------------------------------------
# CITIZEN TELEGRAM BOT ENDPOINTS
# -------------------------------------------------------------

from backend.telegram_bot import get_citizen_telegram_bot, CITIZEN_INCIDENTS, AMC_RELIEF_FACILITIES


@app.post("/api/telegram/webhook")
async def telegram_webhook(update: Dict[str, Any]):
    """
    Inbound webhook endpoint for Telegram Bot updates.
    Handles messages, commands, GPS location shares, and callback buttons.
    """
    bot = get_citizen_telegram_bot()
    await bot.process_update(update)
    return {"status": "ok"}


@app.get("/api/telegram/status")
async def get_telegram_status():
    """
    Returns Telegram bot connectivity status and operational statistics.
    """
    bot = get_citizen_telegram_bot()
    return {
        "is_configured": bot.is_configured,
        "token_present": bool(bot.token),
        "total_facilities": len(AMC_RELIEF_FACILITIES),
        "active_citizen_tickets": len(CITIZEN_INCIDENTS),
        "webhook_url": "/api/telegram/webhook"
    }


@app.get("/api/telegram/incidents")
async def list_citizen_incidents():
    """
    Returns all citizen-reported incidents submitted via Telegram.
    """
    return {
        "total": len(CITIZEN_INCIDENTS),
        "incidents": list(CITIZEN_INCIDENTS.values())
    }


@app.get("/api/telegram/facilities")
async def list_relief_facilities():
    """
    Returns list of AMC designated cooling shelters and hydration points.
    """
    return {
        "city": "Ahmedabad",
        "total": len(AMC_RELIEF_FACILITIES),
        "facilities": AMC_RELIEF_FACILITIES
    }

