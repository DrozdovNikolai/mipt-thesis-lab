"""TCP benchmark against existing split/unified APIs; durable Python driver.

The driver is NOT the Flutter runtime. Native/browser recovery tests accompany it.
Lost acknowledgements are deliberately discarded at the client boundary.
"""

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
from benchmarks.common import (
    OUT,
    append,
    client,
    login,
    measured,
    UniqueFixtureClient,
)


async def main(repeats=2, steps=4):
    async with client() as c:
        headers = await login(c)
        airline, module, exercise, users = await _create_runtime_training(
            UniqueFixtureClient(c), headers
        )
        comp = await c.post(
            "/api/training/competences",
            headers=headers,
            json={"code": "TH1", "name": "Thesis observation"},
        )
        assert comp.status_code == 201, comp.text
        comp_id = comp.json()["id"]
        bi = await c.post(
            f"/api/training/competences/{comp_id}/behavioural-indicators",
            headers=headers,
            json={
                "code": "TH1_OB",
                "shortName": "Observe",
                "name": "Synthetic observation",
            },
        )
        assert bi.status_code == 201, bi.text
        bi_id = bi.json()["id"]
        owner = (await c.get("/api/auth/me", headers=headers)).json()["id"]
        scenarios = [
            (rep, cache, fault)
            for rep in range(repeats)
            for cache in (0, 16384)
            for fault in ("clean", "lost_ack_restart", "offline_restart")
        ]
        random.Random(160916).shuffle(scenarios)
        for rep, cache, fault in scenarios:
            variants = ["split_full", "split_compact", "unified_compact"]
            random.Random(rep + cache + len(fault)).shuffle(variants)
            for variant in variants:
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
                prefix = (
                    "http://baseline:8000" if variant == "split_full" else ""
                ) + f"/api/training/trainings/{tid}"
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
                full["exercises"] = [{"id": exercise, "guidancePlainText": "x" * cache}]
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
                dbpath = OUT / f"h1-queue-{tid}.sqlite"
                db = sqlite3.connect(dbpath)
                db.execute(
                    "CREATE TABLE queue (id INTEGER PRIMARY KEY, path TEXT, body TEXT)"
                )
                db.executemany(
                    "INSERT INTO queue(path,body) VALUES (?,?)",
                    [(p, json.dumps(b)) for p, b in queue],
                )
                db.commit()
                if fault == "offline_restart":
                    db.close()
                    await asyncio.sleep(0.1)
                    db = sqlite3.connect(dbpath)
                ctx = dict(
                    hypothesis="H1",
                    rep=rep,
                    cache_bytes=cache,
                    fault=fault,
                    variant=variant,
                    training_id=tid,
                )
                start = time.perf_counter()
                n = 0
                total_bytes = 0
                if fault == "lost_ack_restart":
                    db.close()
                    for crash in (True, False):
                        proc = await asyncio.create_subprocess_exec(
                            sys.executable,
                            "-m",
                            "benchmarks.outbox_worker",
                            stdin=asyncio.subprocess.PIPE,
                        )
                        await proc.communicate(
                            json.dumps(
                                dict(
                                    queue=str(dbpath),
                                    headers=headers,
                                    context=ctx,
                                    crash=crash,
                                )
                            ).encode()
                        )
                        assert proc.returncode == (77 if crash else 0), proc.returncode
                    db = sqlite3.connect(dbpath)
                    worker_rows = [
                        json.loads(x)
                        for x in (OUT / "h1-worker.jsonl").read_text().splitlines()
                    ]
                    own = [x for x in worker_rows if x["training_id"] == tid]
                    n = len(own)
                    total_bytes = sum(x["body_bytes"] for x in own)
                while row := db.execute(
                    "SELECT id,path,body FROM queue ORDER BY id LIMIT 1"
                ).fetchone():
                    r, _, size = await measured(
                        c, "POST", row[1], json.loads(row[2]), headers, ctx
                    )
                    assert r.status_code == 200, r.text
                    n += 1
                    total_bytes += size
                    db.execute("DELETE FROM queue WHERE id=?", (row[0],))
                    db.commit()
                delivery_ms = (time.perf_counter() - start) * 1000
                recovered = (await c.get(prefix + "/draft", headers=headers)).json()[
                    "payload"
                ]
                recovered_compact = compact_training_state(recovered, version=2)
                assert recovered_compact == state, (recovered_compact, state)
                runtime_state = (
                    await c.get(prefix + "/runtime", headers=headers)
                ).json()["state"]
                assert runtime_state["serverRevision"] == steps
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
                r = await c.post(
                    prefix + "/runtime/sync",
                    headers=headers,
                    json=dict(
                        writerInstanceId=str(writer),
                        writerEpoch=1,
                        baseServerRevision=steps,
                        baseServerEventId=str(previous),
                        crewAssignmentEvents=[],
                        runSnapshots=[terminal.model_dump(mode="json", by_alias=True)],
                    ),
                )
                assert r.status_code == 200, r.text
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
                        grades={},
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
                receipt = None
                for _ in range(2):
                    r = await c.post(prefix + "/submit", headers=headers, json=submit)
                    assert r.status_code == 200, r.text
                    assert r.json()["trainingStatus"] == "COMPLETED", r.text
                    if receipt is not None:
                        assert r.json()["submitReceipt"] == receipt
                    receipt = r.json()["submitReceipt"]
                async with AsyncSessionLocal() as s:
                    saved = list(
                        (
                            await s.execute(
                                select(MistakeReport).where(
                                    MistakeReport.assessment_id
                                    == created["cm1AssessmentId"]
                                )
                            )
                        ).scalars()
                    )
                    assert {str(q.client_report_id): q.comment for q in saved} == {
                        q["clientReportId"]: q["comment"] for q in reports
                    }
                    count = await s.scalar(
                        select(func.count())
                        .select_from(TrainingSessionCrewAssignmentEvent)
                        .where(
                            TrainingSessionCrewAssignmentEvent.training_session_id
                            == tid
                        )
                    )
                    assert count == steps + 1
                db.close()
                append(
                    "h1.jsonl",
                    {
                        **ctx,
                        "requests": n,
                        "body_bytes": total_bytes,
                        "delivery_ms": delivery_ms,
                        "correct_recovery": True,
                        "correct_completion": True,
                        "comment_count": steps,
                        "duplicate_events": 0,
                    },
                )
                print(
                    "H1",
                    rep,
                    cache,
                    fault,
                    variant,
                    n,
                    total_bytes,
                    round(delivery_ms),
                    flush=True,
                )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--steps", type=int, default=4)
    a = p.parse_args()
    asyncio.run(main(a.repeats, a.steps))
