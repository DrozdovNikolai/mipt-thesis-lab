from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal
from app.modules.training.assessment_models import (
    TrainingSession,
    CrewMemberAssessment,
    TrainingSessionCrewAssignmentEvent,
)
from expanded.common import client
from benchmarks.common import UniqueFixtureClient
from tests.test_training_crew_runtime import _create_runtime_training


async def fixture(headers):
    async with client() as c:
        aid, module, exercise, users = await _create_runtime_training(
            UniqueFixtureClient(c), headers
        )
        comp = await c.post(
            "/api/training/competences",
            headers=headers,
            json={"code": "EXP1", "name": "Expanded observation"},
        )
        assert comp.status_code == 201, comp.text
        bi = await c.post(
            f"/api/training/competences/{comp.json()['id']}/behavioural-indicators",
            headers=headers,
            json={
                "code": "EXP_OB",
                "shortName": "Observe",
                "name": "Follows the stated procedure",
            },
        )
        assert bi.status_code == 201, bi.text
        return dict(
            scenarioDayModuleId=module,
            exerciseId=exercise,
            cm1Id=users[0],
            cm2Id=users[1],
            competenceId=comp.json()["id"],
            indicatorId=bi.json()["id"],
        )


async def check(tid, user):
    async with AsyncSessionLocal() as s:
        t = await s.get(TrainingSession, tid)
        assert t is not None and t.instructor_id == user.id
        assessments = (
            await s.scalars(
                select(CrewMemberAssessment)
                .where(CrewMemberAssessment.training_session_id == tid)
                .order_by(CrewMemberAssessment.id)
            )
        ).all()
        count = await s.scalar(
            select(func.count())
            .select_from(TrainingSessionCrewAssignmentEvent)
            .where(TrainingSessionCrewAssignmentEvent.training_session_id == tid)
        )
        return dict(
            trainingId=tid,
            status=t.status,
            eventCount=count,
            assessments=[dict(id=a.id, summary=a.summary) for a in assessments],
        )
