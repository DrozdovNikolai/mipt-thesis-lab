"""Local-only expanded benchmark endpoints; original public routes retain their defaults."""

from datetime import date
import os
import resource
from typing import Annotated
from uuid import UUID, uuid4
from fastapi import Depends, Header, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.main import app
from app.api.deps import get_db, require_privileges
from app.modules.users.models import User
from app.modules.users.access import require_user_airline_id
from app.modules.commander.service import get_airline_competency_grade_distribution
from app.modules.commander.schemas import CompetencyGradeDistributionResponse
from app.modules.training.services.scenario_patch import ScenarioPatch, apply_patch

VARIANT = os.environ.get("THESIS_VARIANT", "original")
INSTANCE_ID = str(uuid4())
Session = Annotated[AsyncSession, Depends(get_db)]
Reader = Annotated[User, Depends(require_privileges(["pilots:read"]))]
Writer = Annotated[User, Depends(require_privileges(["training:write"]))]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:14602", "http://localhost:14602"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Thesis-Observed-At"],
)


@app.get("/_expanded/resources")
async def resources(session: Session, user: Reader):
    r = resource.getrusage(resource.RUSAGE_SELF)
    sql = None
    if os.environ.get("THESIS_VARIANT"):
        sql = dict(
            (
                await session.execute(
                    text(
                        """SELECT
            coalesce(sum(calls),0) calls, coalesce(sum(total_exec_time),0) execution_ms,
            coalesce(sum(shared_blks_hit),0) shared_hits, coalesce(sum(shared_blks_read),0) shared_reads,
            coalesce(sum(shared_blks_dirtied),0) shared_dirtied,
            coalesce(sum(shared_blks_written),0) shared_written,
            coalesce(sum(wal_bytes),0) wal_bytes
            FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database())
            AND query NOT LIKE '%pg_stat_statements%'"""
                    )
                )
            )
            .mappings()
            .one()
        )
    return dict(
        cpu_seconds=r.ru_utime + r.ru_stime,
        rss_kib=r.ru_maxrss,
        pid=os.getpid(),
        variant=VARIANT,
        instance_id=INSTANCE_ID,
        sql=sql,
    )


@app.get("/_expanded/analytics", response_model=CompetencyGradeDistributionResponse)
async def analytics(
    session: Session,
    user: Reader,
    response: Response,
    asOfDate: date | None = None,
    pilotId: UUID | None = None,
    aircraftId: int | None = None,
    positionId: int | None = None,
    ageFromYears: int | None = None,
    ageToYears: int | None = None,
    observed: bool = False,
):
    result = await get_airline_competency_grade_distribution(
        session,
        airline_id=require_user_airline_id(user),
        pilot_public_id=pilotId,
        aircraft_id=aircraftId,
        position_id=positionId,
        age_from_years=ageFromYears,
        age_to_years=ageToYears,
        as_of_date=asOfDate,
        use_projection=VARIANT == "projection",
        use_optimized=VARIANT == "optimized",
    )
    if observed:
        response.headers["X-Thesis-Observed-At"] = (
            await session.scalar(text("SELECT clock_timestamp()"))
        ).isoformat()
    return result


@app.post("/_expanded/scenarios/{scenario_id}/patch")
async def patch(
    scenario_id: int,
    payload: ScenarioPatch,
    session: Session,
    user: Writer,
    client_session_id: Annotated[str, Header(alias="X-Client-Session-Id")],
):
    return await apply_patch(scenario_id, payload, client_session_id, session, user)


class Correction(BaseModel):
    report_id: int
    grade: str


class ProbeRequest(BaseModel):
    report_ids: list[int]


@app.post("/_expanded/probe-state")
async def probe_state(payload: ProbeRequest, session: Session, user: Reader):
    rows = (
        (
            await session.execute(
                text(
                    """SELECT r.id report_id,r.grade FROM final_report r
        JOIN crew_member_assessment a ON a.id=r.assessment_id JOIN users u ON u.id=a.user_id
        WHERE u.airline_id=:aid AND r.id=ANY(:ids)"""
                ),
                {"aid": require_user_airline_id(user), "ids": payload.report_ids},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [dict(r) for r in rows]}


@app.post("/_expanded/correction")
async def correction(payload: Correction, session: Session, user: Writer):
    if payload.grade not in ("1", "2", "3", "4"):
        raise HTTPException(400, "Synthetic grade outside scale")
    rid = await session.scalar(
        text(
            """UPDATE final_report r SET grade=:g,
        grade_code_snapshot=:g,grade_score_snapshot=:score,
        updated_at=clock_timestamp()
        FROM crew_member_assessment a JOIN users u ON u.id=a.user_id
        WHERE r.id=:id AND a.id=r.assessment_id AND u.airline_id=:aid
        RETURNING r.id"""
        ),
        dict(
            g=payload.grade,
            score=int(payload.grade),
            id=payload.report_id,
            aid=require_user_airline_id(user),
        ),
    )
    if rid is None:
        raise HTTPException(404, "Synthetic report not found")
    await session.commit()
    confirmed = await session.scalar(text("SELECT clock_timestamp()"))
    await session.commit()
    return dict(
        report_id=rid, grade=payload.grade, commit_confirmed_at=confirmed.isoformat()
    )


@app.get("/_expanded/queue")
async def queue(session: Session, user: Reader):
    if VARIANT != "projection":
        return dict(pending=0, max_age_ms=0)
    result = (
        (
            await session.execute(
                text(
                    """SELECT count(*) pending,
        coalesce(extract(epoch FROM clock_timestamp()-min(changed_at))*1000,0) max_age_ms
        FROM commander_dirty_pilot"""
                )
            )
        )
        .mappings()
        .one()
    )
    state = (
        (
            await session.execute(
                text(
                    "SELECT crashes,worker_pid,last_start,crash_requested FROM thesis_worker_control WHERE id=1"
                )
            )
        )
        .mappings()
        .one()
    )
    return {**dict(result), **dict(state)}


@app.post("/_expanded/worker-crash")
async def crash(session: Session, user: Writer):
    if VARIANT != "projection":
        raise HTTPException(400, "No projection worker")
    await session.execute(
        text("UPDATE thesis_worker_control SET crash_requested=true WHERE id=1")
    )
    await session.commit()
    return dict(requested=True)


@app.post("/_expanded/h1/fixture")
async def h1_fixture(request: Request, user: Writer):
    from expanded.h1_fixture import fixture

    return await fixture({"Authorization": request.headers["authorization"]})


@app.get("/_expanded/h1/check/{tid}")
async def h1_check(tid: int, user: Writer):
    from expanded.h1_fixture import check

    return await check(tid, user)
