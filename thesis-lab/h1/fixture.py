"""Protocol comparison through shaped TCP HTTP proxy; separate from real Flutter recovery cases."""

import asyncio
import copy
from datetime import UTC, datetime, timedelta
import json
import random
import sqlite3
import sys
import time

from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal
from app.modules.training.assessment.services.sync_state import compact_training_state
from app.modules.training.assessment_models import (
    MistakeReport,
    TrainingSessionCrewAssignmentEvent,
    TrainingSession,
)
from app.modules.training.assessment_schemas import (
    CrewFinalizeBlock,
    MistakeReportInput,
)
from app.modules.training.crew_timeline import new_uuid7, submission_manifest_hash
from tests.test_quick_comment_draft_v3 import _payload, _request
from tests.test_training_crew_runtime import (
    _create_runtime_training,
    _event_with_hash,
    _run_with_hash,
)
from h1.common import OUT, append, client, login
from benchmarks.common import (
    UniqueFixtureClient,
)

def realistic_text(size):
    words = "briefing observation assessment workload communication coordination instructor participant scenario session review timing checklist discussion evidence exercise module approach departure planning situational awareness процедуры экипаж оценка взаимодействие разбор наблюдение".split()
    rng = random.Random(160919)
    lines = []
    while len("\n".join(lines).encode()) < size:
        lines.append(
            f"Exercise note {len(lines)+1}: " + " ".join(rng.choices(words, k=18)) + "."
        )
    return "\n".join(lines).encode()[:size].decode("utf-8", errors="ignore")


async def build(variant, cache, headers):
    async with client() as c:
        airline, module, exercise, users = await _create_runtime_training(
            UniqueFixtureClient(c), headers
        )
        comp = await c.post(
            "/api/training/competences",
            headers=headers,
            json={"code": "H1", "name": "Thesis observation"},
        )
        assert comp.status_code == 201, comp.text
        comp_id = comp.json()["id"]
        bi = await c.post(
            f"/api/training/competences/{comp_id}/behavioural-indicators",
            headers=headers,
            json={
                "code": "H1_OB",
                "shortName": "Observe",
                "name": "Synthetic observation",
            },
        )
        assert bi.status_code == 201, bi.text
        bi_id = bi.json()["id"]
        owner = (await c.get("/api/auth/me", headers=headers)).json()["id"]
        steps = 6
        writer = new_uuid7()
        created_r = await c.post(
            "/api/training/trainings",
            headers=headers,
            json={
                "scenarioDayModuleId": module,
                "cm1Id": users[0],
                "cm2Id": users[1],
                "clientCreationId": str(new_uuid7()),
                "writerInstanceId": str(writer),
                "runtimeClientCapabilities": {
                    "liveCrewSwapVersions": [1],
                    "quickCommentVersions": [1],
                    "transactionalStore": "INDEXED_DB",
                    "offlineDurabilityReady": True,
                },
            },
        )
        assert created_r.status_code == 201, created_r.text
        created = created_r.json()
        tid = created["trainingId"]
        prefix = f"/api/training/trainings/{tid}"
        initial = created["crewRuntime"]["initialEventId"]
        run_id = new_uuid7()
        now = datetime.now(UTC)
        run = _run_with_hash(
            training_id=tid,
            writer_id=writer,
            writer_epoch=1,
            exercise_session_key=run_id,
            runtime_exercise_id=exercise,
            run_index=1,
            status="READY",
            initial_assignment_event_id=initial,
            planned_duration_ms=600000,
            active_duration_ms=0,
            started_at=None,
            ended_at=None,
            client_revision=1,
        )
        full = _payload(
            training_id=tid,
            cm1_assessment_id=created["cm1AssessmentId"],
            cm2_assessment_id=created["cm2AssessmentId"],
            owner_uid=owner,
            revision=1,
        )
        full["competenciesIndicators"]["evaluationCatalogSha256"] = created[
            "evaluationCatalogSha256"
        ]
        async with AsyncSessionLocal() as s:
            full["competenciesIndicators"]["evaluationCatalog"] = (
                await s.get(TrainingSession, tid)
            ).evaluation_catalog_snapshot
        full["exercises"] = [
            {"id": exercise, "guidancePlainText": realistic_text(cache)}
        ]
        event_hashes = [created["crewRuntime"]["initialEventHash"]]
        reports = []
        previous = initial
        queue = []
        for seq in range(1, steps + 1):
            eid = new_uuid7()
            event = _event_with_hash(
                training_id=tid,
                writer_id=writer,
                writer_epoch=1,
                client_event_id=eid,
                client_sequence=seq,
                previous_event_id=previous,
                occurred_at=now + timedelta(seconds=seq),
                scope="SESSION",
                runtime_exercise_id=None,
                exercise_session_key=None,
                exercise_offset_ms=None,
                timer_state="NONE",
                cm1_assessment_id_after=created[
                    "cm2AssessmentId" if seq % 2 else "cm1AssessmentId"
                ],
                cm2_assessment_id_after=created[
                    "cm1AssessmentId" if seq % 2 else "cm2AssessmentId"
                ],
            )
            event_hashes.append(event.payload_hash)
            report_id = str(new_uuid7())
            timestamp = (now + timedelta(seconds=seq)).isoformat()
            reports.append(
                dict(
                    schemaVersion=1,
                    id=report_id,
                    clientReportId=report_id,
                    kind="QUICK_COMMENT",
                    state="PENDING_OB",
                    participantAssessmentId=str(created["cm1AssessmentId"]),
                    participantUserId=str(users[0]),
                    participantInitialSlot="CM1",
                    slotAtObservation="CM2" if seq % 2 else "CM1",
                    crew="CM1",
                    comment=f"Observation {seq}: русский текст ✈",
                    isPositive=False,
                    color="#FF453A",
                    hashtag="",
                    exerciseId=str(exercise),
                    runtimeExerciseId=exercise,
                    exerciseName="Synthetic exercise",
                    exerciseSessionKey=str(run_id),
                    exerciseOffsetSec=0,
                    exerciseOffsetMs=0,
                    runIndex=1,
                    timelineSource="TIMELINE",
                    assignmentEventIdAtObservation=str(eid),
                    timestamp=timestamp,
                    createdAt=timestamp,
                    updatedAt=timestamp,
                )
            )
            full["participants"][0].update(
                quickComments=copy.deepcopy(reports), summary=f"Summary {seq}"
            )
            full["cm1QuickComments"] = copy.deepcopy(reports)
            full["draftRevision"] = seq
            for i, participant in enumerate(full["participants"]):
                participant["grades"] = {"H1": "4" if (seq+i)%2 == 0 else "3"}
            state = compact_training_state(full, version=2)
            runtime = dict(
                writerInstanceId=str(writer),
                writerEpoch=1,
                baseServerRevision=seq - 1,
                baseServerEventId=str(previous),
                runSnapshots=(
                    [run.model_dump(mode="json", by_alias=True)]
                    if seq == 1
                    else []
                ),
                crewAssignmentEvents=[
                    event.model_dump(mode="json", by_alias=True)
                ],
            )
            assessment = _request(
                copy.deepcopy(full if variant == "split_full" else state),
                writer_id=str(writer),
            )
            envelope = dict(
                protocolVersion=1,
                writerInstanceId=str(writer),
                writerEpoch=1,
                assessmentState=assessment,
            )
            if variant == "unified_compact":
                queue.append(
                    (prefix + "/sync", {**envelope, "runtime": runtime})
                )
            else:
                queue.extend(
                    [
                        (prefix + "/runtime/sync", runtime),
                        (
                            (prefix + "/draft", assessment)
                            if variant == "split_full"
                            else (prefix + "/sync", envelope)
                        ),
                    ]
                )
            previous = eid
        terminal = _run_with_hash(
            training_id=tid,
            writer_id=writer,
            writer_epoch=1,
            exercise_session_key=run_id,
            runtime_exercise_id=exercise,
            run_index=1,
            status="ABANDONED",
            initial_assignment_event_id=initial,
            planned_duration_ms=600000,
            active_duration_ms=0,
            started_at=None,
            ended_at=now + timedelta(seconds=steps + 1),
            client_revision=2,
        )
        queue.append((prefix + "/runtime/sync", dict(
            writerInstanceId=str(writer), writerEpoch=1,
            baseServerRevision=steps, baseServerEventId=str(previous),
            crewAssignmentEvents=[], runSnapshots=[terminal.model_dump(mode="json", by_alias=True)])))
        converted = [
            MistakeReportInput(
                client_report_id=q["clientReportId"],
                timeline_source="TIMELINE",
                exercise_id=exercise,
                timestamp=q["timestamp"],
                exercise_offset_sec=0,
                exercise_offset_ms=0,
                exercise_session_key=str(run_id),
                assignment_event_id_at_observation=q[
                    "assignmentEventIdAtObservation"
                ],
                comp_id=comp_id,
                bi_id=bi_id,
                comment=q["comment"],
                is_positive=False,
            )
            for q in reports
        ]
        blocks = [
            CrewFinalizeBlock(
                assessment_id=created[key],
                grades={"H1": "4" if i == 0 else "3"},
                mistake_reports=converted if i == 0 else [],
                unresolved_quick_comments=[],
                summary=f"Final {i}",
                result=True,
            )
            for i, key in enumerate(("cm1AssessmentId", "cm2AssessmentId"))
        ]
        digest = submission_manifest_hash(
            training_id=tid,
            writer_instance_id=writer,
            writer_epoch=1,
            expected_current_event_id=previous,
            expected_client_sequence=steps,
            crew_event_payload_hashes=event_hashes,
            terminal_run_hashes=[(run_id, terminal.payload_hash)],
            assessment_blocks=blocks,
            speech_session_id=None,
            speech_last_chunk_index=None,
            comment_contract_version=1,
        )
        submit = dict(
            idempotencyKey=digest,
            submissionManifestHash=digest,
            commentContractVersion=1,
            runtimeSeal=dict(
                writerInstanceId=str(writer),
                writerEpoch=1,
                expectedCurrentEventId=str(previous),
                expectedClientSequence=steps,
                baseServerRevision=steps,
                pendingRuntime=dict(runSnapshots=[], crewAssignmentEvents=[]),
            ),
            assessments=[
                b.model_dump(mode="json", by_alias=True) for b in blocks
            ],
        )
        queue.append((prefix + "/submit", submit))
        async with AsyncSessionLocal() as s:
            t = await s.get(TrainingSession, tid)
            expected = dict(training_id=tid, writer=str(writer), steps=steps,
                manifest=digest, last_event=str(previous), event_hashes=event_hashes,
                events=[str(initial)]+[q["assignmentEventIdAtObservation"] for q in reports],
                reports={q["clientReportId"]: q["comment"] for q in reports},
                assessments=[b.model_dump(mode="json", by_alias=True) for b in blocks],
                terminal=terminal.model_dump(mode="json", by_alias=True))
        return dict(training_id=tid, queue=[dict(path=p,body=b) for p,b in queue], expected=expected)
