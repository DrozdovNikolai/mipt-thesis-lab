"""Seed only the disposable Commander integration database, never a working DB.
Reuses synthetic fixture builders from the backend regression suite; no pytest
session/schema-reset fixture runs. Outputs IDs, never tokens or passwords.
"""
import asyncio
import json
import os
from datetime import UTC, datetime

from httpx import AsyncClient
from app.db.session import AsyncSessionLocal
from tests.test_commander_training_sessions import (
    _assign_user, _create_airline, _create_user, _load_active_grading_scheme_id,
    _load_active_grading_values_by_code, _resolve_aircraft_id,
    _resolve_internal_user_id, _seed_training_session_detail_fixture,
)

async def main():
    assert os.environ['DATABASE_URL'] == 'postgresql+asyncpg://commander_test:commander_test@db:5432/commander_test'
    async with AsyncClient(base_url='http://api:8000', timeout=60) as client:
        response = await client.post('/api/auth/login', json={'login': 'admin', 'password': 'commander-integration-only'})
        response.raise_for_status()
        headers = {'Authorization': f"Bearer {response.json()['accessToken']}"}
        response = await client.get('/api/auth/me', headers=headers)
        response.raise_for_status()
        admin_id = response.json()['id']
        airline_id = await _create_airline(client, headers, code='VUE', name='Vue Commander synthetic airline')
        await _assign_user(client, headers, user_public_id=admin_id, airline_id=airline_id, aircraft_codes=['A320'], first_name='Migration', last_name='Administrator')
        people = []
        for login, first, last in [('vue_instructor', 'Ivan', 'Instructor'), ('vue_alpha', 'Alice', 'Alpha'), ('vue_bravo', 'Bob', 'Bravo')]:
            uid = await _create_user(client, headers, login=login, email=f'{login}@example.com')
            await _assign_user(client, headers, user_public_id=uid, airline_id=airline_id, aircraft_codes=['A320'], first_name=first, last_name=last)
            people.append(uid)
        async with AsyncSessionLocal() as db:
            internal = [await _resolve_internal_user_id(db_session=db, user_public_id=uid) for uid in people]
            aircraft_id = await _resolve_aircraft_id(db_session=db, airline_id=airline_id, code='A320')
            scheme_id = await _load_active_grading_scheme_id(db_session=db, airline_id=airline_id)
            values = await _load_active_grading_values_by_code(db_session=db, airline_id=airline_id)
            fixture = await _seed_training_session_detail_fixture(db_session=db, airline_id=airline_id, aircraft_id=aircraft_id, instructor_id=internal[0], cm1_user_id=internal[1], cm2_user_id=internal[2], grading_scheme_id=scheme_id, grading_values_by_code=values, completed_at=datetime(2026, 3, 10, 14, 0, tzinfo=UTC), include_service_exercises=True)
        response = await client.get('/api/commander/competences', headers=headers)
        response.raise_for_status()
        competence_ids = [item['id'] for item in response.json()]
        response = await client.post('/api/commander/flight-types', headers=headers, json={'name': 'Migration recurrent', 'isMain': True})
        response.raise_for_status()
        type_id = response.json()['id']
        response = await client.put(f'/api/commander/flight-types/{type_id}/thresholds', headers=headers, json={'thresholds': [{'competenceId': id, 'value': '6'} for id in competence_ids]})
        response.raise_for_status()
        print(json.dumps({'airlineId': airline_id, 'adminId': admin_id, 'instructorId': people[0], 'firstPilotId': people[1], 'secondPilotId': people[2], 'flightTypeId': type_id, 'competenceIds': competence_ids, **fixture}))

asyncio.run(main())
