"""Paused-worker bursts: maintenance cost and final-state parity, not freshness."""
import asyncio
import json
import sys
import time
from sqlalchemy import text
from app.db.session import AsyncSessionLocal, engine
from app.modules.commander import analytics_projection, analytics_incremental
from app.modules.commander.service import get_airline_competency_grade_distribution as source_query
from expanded.common import OUT, append


async def query(session, **kwargs):
    options = dict(pilot_public_id=None, aircraft_id=None, age_from_years=None,
                   age_to_years=None, position_id=None, as_of_date=None)
    options.update(kwargs)
    return await source_query(session, **options)


async def metrics(s):
    return dict((await s.execute(text("""SELECT sum(wal_bytes) wal_bytes,
        sum(total_exec_time) execution_ms FROM pg_stat_statements
        WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database())
        AND query NOT LIKE '%pg_stat_statements%'"""))).mappings().one())


async def main(variant):
    assert variant in ('projection','incremental')
    module=analytics_incremental if variant=='incremental' else analytics_projection
    queue='commander_dirty_assessment' if variant=='incremental' else 'commander_dirty_pilot'
    data=json.loads((OUT/'dataset.json').read_text())
    rid=data['probes'][0]['report_id']
    async def drain():
        async with AsyncSessionLocal() as s:
            while await module.process_batch(s,25): pass
    await drain()
    for rep in range(10):
        async with AsyncSessionLocal() as s:
            start_grade=int(await s.scalar(text('SELECT grade FROM final_report WHERE id=:id'),{'id':rid}))
            await s.commit()
            before=await metrics(s); await s.commit()
            started=time.perf_counter()
            for i in range(20):
                # Every write differs from its predecessor; final state differs from the initial state.
                grade=str((start_grade+i+(1 if i==19 else 0))%4+1)
                await s.execute(text('''UPDATE final_report SET grade=:g,grade_code_snapshot=:g,
                    grade_score_snapshot=:score,updated_at=clock_timestamp() WHERE id=:id'''),
                    {'g':grade,'score':int(grade),'id':rid})
                await s.commit()
            count=await s.scalar(text('SELECT count(*) FROM '+queue)); await s.commit()
            assert count==1,(variant,rep,count)
        await drain()
        elapsed=(time.perf_counter()-started)*1000
        async with AsyncSessionLocal() as s:
            after=await metrics(s); await s.commit()
            original=await query(s,airline_id=data['airline_id'])
            projected=await query(s,airline_id=data['airline_id'],use_projection=True)
            assert original==projected
        append('coalescing.jsonl',{'variant':variant,'rep':rep,'accepted_updates':20,
            'pending_before_drain':count,'elapsed_ms':elapsed,'final_grade':grade,'correct':True,
            'sql_delta':{k:float(after[k]-before[k]) for k in before}})
    await engine.dispose()


if __name__=='__main__': asyncio.run(main(sys.argv[1]))
