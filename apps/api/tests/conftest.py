import pytest
from fastapi.testclient import TestClient
from app import create_app
from roundmind.config import Settings

@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / 'data')

@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client
