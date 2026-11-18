"""Authenticated lab-only controls and read-only database oracle around real API."""
from contextvars import ContextVar
import json
import os
from pathlib import Path
from typing import Annotated
from uuid import uuid4
from fastapi import Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.main import app
from app.api.deps import require_privileges
from app.db.session import AsyncSessionLocal
from app.modules.training.assessment_models import (TrainingSession, TrainingSessionCrewState,
    CrewMemberAssessment, FinalReport, MistakeReport, TrainingSessionCrewAssignmentEvent,
    TrainingSessionExerciseRun)
from app.modules.users.models import User
from h1.common import OUT, append

INSTANCE = str(uuid4())
Writer = Annotated[User, Depends(require_privileges(['training:write']))]
_request_path = ContextVar('h1_path', default='')
_commit = AsyncSession.commit

async def controlled_commit(session):
    marker = OUT / 'crash-before-commit.json'
    if marker.exists():
        armed = json.loads(marker.read_text())
        if _request_path.get() == f"/api/training/trainings/{armed['training_id']}/submit":
            # Flush ensures the domain writes reached PostgreSQL, still uncommitted.
            await session.flush()
            marker.unlink()
            append('faults.jsonl', {'point':'submit_before_commit', 'pid':os.getpid(),
                                  'instance':INSTANCE, **armed})
            os._exit(77)
    return await _commit(session)

AsyncSession.commit = controlled_commit

@app.middleware('http')
async def request_scope(request, call_next):
    token = _request_path.set(request.url.path)
    try:
        return await call_next(request)
    finally:
        _request_path.reset(token)

app.add_middleware(CORSMiddleware,
    allow_origins=['http://127.0.0.1:14702','http://localhost:14702'],
    allow_methods=['*'], allow_headers=['*'])

@app.get('/_h1/instance')
async def instance(user: Writer):
    path = OUT/'crash-rollback-checks.jsonl'
    last = json.loads(path.read_text().splitlines()[-1]) if path.exists() else None
    return JSONResponse({'instance':INSTANCE, 'pid':os.getpid(), 'last_rollback':last})

class FixtureRequest(BaseModel):
    variant: str
    cache: int

@app.post('/_h1/fixture', response_class=JSONResponse)
async def fixture(payload: FixtureRequest, request: Request, user: Writer):
    if payload.variant not in ('split_full','split_compact','unified_compact') or payload.cache not in (1024,16384):
        raise HTTPException(400)
    from h1.fixture import build
    return await build(payload.variant, payload.cache, {'Authorization':request.headers['authorization']})

class Arm(BaseModel):
    training_id: int

@app.post('/_h1/arm')
async def arm(payload: Arm, user: Writer):
    async with AsyncSessionLocal() as s:
        t = await s.get(TrainingSession, payload.training_id)
        if t is None or t.instructor_id != user.id:
            raise HTTPException(404)
    path = OUT / 'crash-before-commit.json'
    if path.exists():
        raise HTTPException(409, 'A fault is already armed')
    path.write_text(json.dumps({'training_id':payload.training_id}))
    return {'armed':True, 'instance':INSTANCE, 'pid':os.getpid()}

@app.get('/_h1/check/{tid}', response_class=JSONResponse)
async def check(tid: int, user: Writer):
    async with AsyncSessionLocal() as s:
        t = await s.get(TrainingSession, tid)
        if t is None or t.instructor_id != user.id:
            raise HTTPException(404)
        state = await s.get(TrainingSessionCrewState, tid)
        events = (await s.scalars(select(TrainingSessionCrewAssignmentEvent)
            .where(TrainingSessionCrewAssignmentEvent.training_session_id==tid)
            .order_by(TrainingSessionCrewAssignmentEvent.server_revision))).all()
        assessments = (await s.scalars(select(CrewMemberAssessment)
            .where(CrewMemberAssessment.training_session_id==tid)
            .order_by(CrewMemberAssessment.id))).all()
        result = []
        for a in assessments:
            grades = (await s.scalars(select(FinalReport).where(FinalReport.assessment_id==a.id))).all()
            reports = (await s.scalars(select(MistakeReport).where(MistakeReport.assessment_id==a.id))).all()
            result.append({'id':a.id,'summary':a.summary,'result':a.result,
                'grades':{g.competence_code_snapshot:g.grade for g in grades},
                'reports':[{'id':str(r.client_report_id), 'comment':r.comment,
                            'event':next((str(e.public_id) for e in events
                                if e.id == r.assignment_event_id_at_observation), None)} for r in reports]})
        runs = (await s.scalars(select(TrainingSessionExerciseRun)
            .where(TrainingSessionExerciseRun.training_session_id==tid))).all()
        return {'training_id':tid,'status':t.status,'manifest':t.submit_idempotency_key,
            'submitted':t.submitted_at is not None,
            'sealed':state.sealed_at is not None if state else False,
            'assessments':result,
            'events':[{'id':str(e.public_id),'hash':e.payload_hash,'sequence':e.client_sequence,
                       'revision':e.server_revision} for e in events],
            'runs':[{'key':str(r.exercise_session_key),'hash':r.payload_hash,'status':r.status} for r in runs]}

@app.post('/_expanded/h1/fixture')
async def browser_fixture(request: Request, user: Writer):
    import expanded.h1_fixture as f
    from h1.common import client
    f.client = client
    return await f.fixture({'Authorization':request.headers['authorization']})
