"""Simulation Mode: replay the synthetic dataset as a stream (separate from live data)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.common import audit_async
from app.auth.dependencies import get_pipeline, require_admin, require_staff
from app.database.models import User
from app.database.schemas import SimulationResetRequest, SimulationStartRequest, SimulationStepRequest
from app.services.pipeline import PipelineService

router = APIRouter(prefix="/api/simulation", tags=["Simulation mode"])


@router.get("/state", summary="Simulation state (clearly separate from the live stream)")
def state(_: User = Depends(require_staff), pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    return pipeline.simulation_state()


@router.post("/start", summary="Start streaming simulated records (runs in the background)")
async def start(body: SimulationStartRequest, request: Request, user: User = Depends(require_staff),
                pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    res = await pipeline.start_simulation(body.speed, body.pause_on_drift)
    await audit_async(request, "simulation.started", user=user, resource="simulation", stream="simulation",
                      details={"speed": body.speed, "pause_on_drift": body.pause_on_drift,
                               "pointer": res.get("pointer")})
    return res


@router.post("/pause", summary="Pause the simulation")
async def pause(request: Request, user: User = Depends(require_staff),
                pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    res = await pipeline.pause_simulation()
    await audit_async(request, "simulation.stopped", user=user, resource="simulation", stream="simulation",
                      details={"processed": res.get("processed")})
    return res


@router.post("/step", summary="Process a fixed number of simulated records now")
async def step(body: SimulationStepRequest, request: Request, user: User = Depends(require_staff),
               pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    res = await pipeline.simulate(body.count, body.stop_on_drift)
    await audit_async(request, "simulation.stepped", user=user, resource="simulation", stream="simulation",
                      details={"requested": body.count, "processed": res["processed"],
                               "drift_events": len(res["drift_events"]), "new_versions": res["new_versions"]})
    return res


@router.post("/trend-change", summary="Jump to the next fashion trend period")
async def trend_change(request: Request, user: User = Depends(require_staff),
                       pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    res = await pipeline.trend_change()
    await audit_async(request, "simulation.trend_changed", user=user, resource="simulation", stream="simulation",
                      details={k: res.get(k) for k in ("from_trend", "to_trend", "step", "skipped_records")})
    return res


@router.post("/reset", summary="Delete simulation data and retrain v1.0 (admin)")
async def reset(body: SimulationResetRequest, request: Request, admin: User = Depends(require_admin),
                pipeline: PipelineService = Depends(get_pipeline)) -> dict:
    res = await pipeline.reset_simulation(body.regenerate, body.seed)
    await audit_async(request, "simulation.reset", user=admin, resource="simulation", stream="simulation",
                      severity="warning", details={"regenerate": body.regenerate, "seed": res.get("seed")})
    return res
