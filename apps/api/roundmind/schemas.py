from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from .config import HEAD_REVISION, VERSION


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class DatabaseHealth(StrictModel):
    status: Literal['ready', 'unavailable', 'schema_mismatch']
    schema_revision: Literal['0001_initial'] | None
    expected_revision: Literal['0001_initial'] = HEAD_REVISION


class HealthData(StrictModel):
    status: Literal['ok', 'degraded']
    service: Literal['roundmind-api'] = 'roundmind-api'
    database: DatabaseHealth


class Meta(StrictModel):
    request_id: UUID
    version: Literal['0.1.0'] = VERSION


class HealthResponse(StrictModel):
    data: HealthData
    meta: Meta
