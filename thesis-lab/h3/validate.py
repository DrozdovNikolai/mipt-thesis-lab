"""Database integration checks in a disposable thesis_exp_validation clone."""
import asyncio
import json
import time
from datetime import date
from sqlalchemy import text
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal, engine
from app.modules.commander import analytics_incremental as inc, analytics_optimized
from app.modules.commander.service import get_airline_competency_grade_distribution as source_query
from expanded.common import OUT, append, save


async def query(session, **kwargs):
    options = dict(pilot_public_id=None, aircraft_id=None, age_from_years=None,
                   age_to_years=None, position_id=None, as_of_date=None)
    options.update(kwargs)
    return await source_query(session, **options)


async def sql(statement, params=None):
    async with AsyncSessionLocal() as s:
        result = await s.execute(text(statement), params or {})
        rows = result.mappings().all() if result.returns_rows else []
        await s.commit()
        return [dict(r) for r in rows]


async def pending():
    return (await sql("""SELECT (SELECT count(*) FROM commander_dirty_assessment)+
        (SELECT count(*) FROM commander_dirty_training) n"""))[0]["n"]


async def drain():
    for _ in range(1000):
        async with AsyncSessionLocal() as s:
            await inc.process_batch(s, 100)
        if not await pending():
            return
    raise AssertionError("Queue did not drain")


async def parity(label, data):
    await drain()
    # Full persisted facts, including grades outside the currently selected latest assessment.
    expected_facts = await sql("""SELECT a.id assessment_id,a.user_id,t.id training_id,
        coalesce(t.completed_at,t.updated_at,t.created_at) effective_at,a.created_at assessment_created_at
        FROM crew_member_assessment a JOIN training_session t ON t.id=a.training_session_id
        WHERE a.user_id IS NOT NULL AND t.status='COMPLETED' ORDER BY a.id""")
    actual_facts = await sql("SELECT * FROM commander_assessment_fact ORDER BY assessment_id")
    assert actual_facts == expected_facts, (label, "facts")
    expected_grades = await sql("""SELECT DISTINCT ON(r.assessment_id,r.competence_id)
        r.assessment_id,r.competence_id,coalesce(r.grade_code_snapshot,r.grade) grade_code,
        r.grade_label_snapshot grade_label,r.grade_score_snapshot grade_score_numeric,
        r.grade_color_hex_snapshot grade_color_hex
        FROM final_report r JOIN crew_member_assessment a ON a.id=r.assessment_id
        JOIN training_session t ON t.id=a.training_session_id
        WHERE a.user_id IS NOT NULL AND t.status='COMPLETED'
        ORDER BY r.assessment_id,r.competence_id,r.updated_at DESC,r.created_at DESC,r.id DESC""")
    actual_grades = await sql("SELECT * FROM commander_grade_fact ORDER BY assessment_id,competence_id")
    assert actual_grades == expected_grades, (label, "grades")
    filters = [{}, {"as_of_date": date(2020,1,1)}, {"as_of_date": date(2020,1,2)},
        {"as_of_date": date(2019,12,31)}, {"aircraft_id": data["aircraft_id"]},
        {"position_id": data["position_id"]}, {"age_from_years": 30,"age_to_years":40}]
    airlines = [data["airline_id"], *[n["airline_id"] for n in data.get("noise",[])]]
    checks = 0
    async with AsyncSessionLocal() as s:
        for aid in airlines:
            for f in filters:
                source = await query(s, airline_id=aid, **f)
                projected = await query(s, airline_id=aid, use_projection=True, **f)
                assert source == projected, (label, aid, f)
                checks += 1
    append("incremental-validation.jsonl", {"case":label,"passed":True,"query_pairs":checks,
        "facts":len(actual_facts),"grades":len(actual_grades)})
    print("VALIDATED", label, flush=True)


async def main():
    assert get_settings().database_url.rsplit("/",1)[-1] == "thesis_exp_validation"
    data = json.loads((OUT/"dataset.json").read_text())
    async with AsyncSessionLocal() as s:
        await analytics_optimized.install(s)
        await inc.install(s)
        await inc.enqueue_rebuild(s)
    await parity("initial", data)
    r = (await sql("""SELECT r.*,a.user_id,a.training_session_id FROM final_report r
        JOIN crew_member_assessment a ON a.id=r.assessment_id JOIN users u ON u.id=a.user_id
        WHERE u.airline_id=:company ORDER BY a.id DESC,r.id LIMIT 1""", {"company":data["airline_id"]}))[0]
    rid, aid, tid = r["id"],r["assessment_id"],r["training_session_id"]
    params={"rid":rid,"aid":aid,"tid":tid}
    async def change(label, stmt, p=None):
        await sql(stmt, p or params)
        await parity(label,data)
    # Fresh training/assessment/report after trigger installation, removed again after checks.
    created_tid=(await sql("""INSERT INTO training_session(instructor_id,grading_scheme_id,status,
        submission_status,completed_at,created_at,updated_at,comment_contract_version)
        SELECT instructor_id,grading_scheme_id,'COMPLETED','COMPLETED','2022-01-01',
          '2022-01-01','2022-01-01',0 FROM training_session WHERE id=:tid RETURNING id""",params))[0]['id']
    created_aid=(await sql("""INSERT INTO crew_member_assessment(training_session_id,user_id,training_role)
        VALUES(:tid,:uid,'cm1') RETURNING id""",{'tid':created_tid,'uid':r['user_id']}))[0]['id']
    await sql("""INSERT INTO final_report(assessment_id,competence_id,grade,grade_code_snapshot,grade_score_snapshot)
        VALUES(:aid,:comp,'3','3',3)""",{'aid':created_aid,'comp':r['competence_id']})
    await parity('insert_completed_training_and_assessment',data)
    await change('delete_new_training','DELETE FROM training_session WHERE id=:tid',{'tid':created_tid})
    # Tenant filters use authoritative user metadata; reassignment must not expose old-tenant rows.
    if data.get('noise'):
        neighbor=data['noise'][0]['airline_id']
        await change('user_changes_airline','UPDATE users SET airline_id=:company WHERE id=:uid',{'company':neighbor,'uid':r['user_id']})
        await change('user_returns_to_airline','UPDATE users SET airline_id=:company WHERE id=:uid',{'company':data['airline_id'],'uid':r['user_id']})
    await change("correct_grade", "UPDATE final_report SET grade='4',grade_code_snapshot='4',grade_score_snapshot=4 WHERE id=:rid")
    # 100 committed edits while processing is paused coalesce into one durable key.
    for i in range(100):
        await sql("UPDATE final_report SET grade=:g,grade_code_snapshot=:g WHERE id=:rid", {"rid":rid,"g":str(i%4+1)})
    assert await pending() == 1
    await parity("100_updates_one_queue_key",data)
    async with AsyncSessionLocal() as s:
        await s.execute(text("UPDATE final_report SET grade='1',grade_code_snapshot='1' WHERE id=:rid"),params)
        assert await s.scalar(text("SELECT count(*) FROM commander_dirty_assessment")) == 1
        await s.rollback()
    assert await pending() == 0
    await parity("source_rollback",data)
    duplicate=(await sql("""INSERT INTO final_report(assessment_id,competence_id,grade,grade_code_snapshot,
        grade_score_snapshot,created_at,updated_at) SELECT assessment_id,competence_id,'2','2',2,created_at,updated_at
        FROM final_report WHERE id=:rid RETURNING id""", params))[0]["id"]
    await parity("duplicate_timestamp_tie_uses_id",data)
    await change("delete_winning_report_falls_back","DELETE FROM final_report WHERE id=:rid",{"rid":duplicate})
    comp=data["competences"][1]
    await change("move_competence","UPDATE final_report SET competence_id=:comp WHERE id=:rid",{"rid":rid,"comp":comp})
    await change("restore_competence","UPDATE final_report SET competence_id=:comp WHERE id=:rid",{"rid":rid,"comp":r["competence_id"]})
    other=(await sql("SELECT id FROM crew_member_assessment WHERE user_id=:uid AND id<>:aid ORDER BY id LIMIT 1",{"uid":r["user_id"],"aid":aid}))[0]["id"]
    await change("move_report_to_older_assessment","UPDATE final_report SET assessment_id=:aid WHERE id=:rid",{"aid":other,"rid":rid})
    await change("restore_report_owner","UPDATE final_report SET assessment_id=:aid WHERE id=:rid")
    new_user=next(u["id"] for u in data["users"] if u["id"]!=r["user_id"])
    await change("reassign_pilot","UPDATE crew_member_assessment SET user_id=:uid WHERE id=:aid",{"uid":new_user,"aid":aid})
    await change("null_pilot","UPDATE crew_member_assessment SET user_id=NULL WHERE id=:aid")
    await change("restore_pilot","UPDATE crew_member_assessment SET user_id=:uid WHERE id=:aid",{"uid":r["user_id"],"aid":aid})
    await change("change_effective_date","UPDATE training_session SET completed_at='2019-12-30' WHERE id=:tid")
    await change("remove_completion","UPDATE training_session SET status='IN_PROGRESS' WHERE id=:tid")
    await change("restore_completion","UPDATE training_session SET status='COMPLETED',completed_at='2021-01-01' WHERE id=:tid")
    # A worker failure after all writes but before commit must roll back facts and queue acknowledgement.
    await sql("UPDATE final_report SET grade='1',grade_code_snapshot='1' WHERE id=:rid",params)
    class Crash(Exception): pass
    async with AsyncSessionLocal() as s:
        async def crash(): raise Crash()
        s.commit=crash
        try: await inc.process_batch(s)
        except Crash: await s.rollback()
        else: raise AssertionError("Crash did not happen")
    assert await pending() == 1
    await parity("worker_rollback_before_commit",data)
    # Writer arriving while a batch owns the key must publish another key after commit.
    await sql("UPDATE final_report SET grade='2',grade_code_snapshot='2' WHERE id=:rid",params)
    reached=asyncio.Event(); release=asyncio.Event(); writer_started=asyncio.Event()
    async def held_worker():
        async with AsyncSessionLocal() as s:
            commit=s.commit
            first=True
            async def held_commit():
                nonlocal first
                if first:
                    first=False; reached.set(); await release.wait()
                await commit()
            s.commit=held_commit
            await inc.process_batch(s)
    async def writer():
        writer_started.set()
        await sql("UPDATE final_report SET grade='3',grade_code_snapshot='3' WHERE id=:rid",params)
    task=asyncio.create_task(held_worker()); await asyncio.wait_for(reached.wait(),10)
    write=asyncio.create_task(writer()); await writer_started.wait(); await asyncio.sleep(.1)
    assert not write.done(), "Expected transactional queue lock to hold the writer"
    release.set(); await asyncio.wait_for(asyncio.gather(task,write),10)
    assert await pending() == 1
    await parity("writer_reenqueues_after_worker_commit",data)
    # Training commit and a concurrently committed new assessment: expansion must occur after commit.
    async with AsyncSessionLocal() as training_tx:
        await training_tx.execute(text("UPDATE training_session SET status='IN_PROGRESS' WHERE id=:tid"),params)
        inserted=(await sql("""INSERT INTO crew_member_assessment(training_session_id,user_id,training_role)
            VALUES(:tid,:uid,'cm2') RETURNING id""",{'tid':tid,'uid':new_user}))[0]['id']
        await drain()  # New assessment was visible while the old COMPLETED status was still committed.
        await training_tx.commit()
    assert await pending() > 0
    await parity('training_change_expands_concurrent_assessment',data)
    await change('restore_after_training_race',"UPDATE training_session SET status='COMPLETED' WHERE id=:tid")
    # Competing workers converge on the same latest pointer across many assessments of one pilot.
    await sql("UPDATE final_report SET grade='4',grade_code_snapshot='4' WHERE assessment_id IN (SELECT id FROM crew_member_assessment WHERE user_id=:uid)",{"uid":r["user_id"]})
    async def process():
        async with AsyncSessionLocal() as s: return await inc.process_batch(s,3)
    await asyncio.wait_for(asyncio.gather(process(),process()),10)
    await parity("two_workers_one_pilot",data)
    await change("delete_latest_assessment","DELETE FROM crew_member_assessment WHERE id=:aid")
    await change("delete_training_cascades","DELETE FROM training_session WHERE id=(SELECT min(training_session_id) FROM crew_member_assessment)")
    await change("delete_all_assessments_of_pilot","DELETE FROM crew_member_assessment WHERE user_id=:uid",{"uid":r["user_id"]})
    # Rebuild is idempotent even after deletes and reassignments.
    async with AsyncSessionLocal() as s: await inc.enqueue_rebuild(s)
    await parity("rebuild_idempotent",data)
    rows=[json.loads(line) for line in (OUT/"incremental-validation.jsonl").read_text().splitlines()]
    save("incremental-validation-complete.json",{"passed":True,"cases":len(rows),"query_pairs":sum(r["query_pairs"] for r in rows),"completed_at":time.time()})
    await engine.dispose()


if __name__=='__main__':
    asyncio.run(main())
