"""Experimental adapters are confined to the internal lab network."""

from app.main import app
from datetime import date
from typing import Annotated
from uuid import UUID
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, require_privileges
from app.modules.users.models import User
from app.modules.users.access import require_user_airline_id
from app.modules.commander.service import get_airline_competency_grade_distribution
from app.modules.commander.schemas import CompetencyGradeDistributionResponse
import resource


@app.get("/_thesis/resources")
async def resources(
    user: Annotated[User, Depends(require_privileges(["pilots:read"]))],
):
    r = resource.getrusage(resource.RUSAGE_SELF)
    return {"cpu_seconds": r.ru_utime + r.ru_stime, "max_rss_kib": r.ru_maxrss}


@app.get(
    "/_thesis/analytics/{variant}", response_model=CompetencyGradeDistributionResponse
)
async def analytics(
    variant: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_privileges(["pilots:read"]))],
    asOfDate: date | None = None,
    pilotId: UUID | None = None,
    aircraftId: int | None = None,
    positionId: int | None = None,
    ageFromYears: int | None = None,
    ageToYears: int | None = None,
):
    assert variant in ("baseline", "projection")
    return await get_airline_competency_grade_distribution(
        session,
        airline_id=require_user_airline_id(user),
        pilot_public_id=pilotId,
        aircraft_id=aircraftId,
        position_id=positionId,
        age_from_years=ageFromYears,
        age_to_years=ageToYears,
        as_of_date=asOfDate,
        **({"use_projection": True} if variant == "projection" else {}),
    )
