import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(tempfile.mkdtemp()) / "cars.db").replace("\\", "/")
os.environ["ADMIN_API_KEY"] = "test-admin-key-1234567890"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import Base, app, engine  # noqa: E402

ADMIN = {"X-API-Key": "test-admin-key-1234567890"}


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as test_client:
        yield test_client


def test_add_get_search_delete(client):
    r = client.post("/add-car", json={"name": "Chevrolet", "model": "Cobalt", "year": 2020}, headers=ADMIN)
    assert r.status_code == 201, r.text
    car_id = r.json()["id"]
    assert client.get(f"/car/{car_id}").json()["year"] == 2020
    assert [c["model"] for c in client.get("/cars", params={"q": "cob"}).json()] == ["Cobalt"]
    assert client.delete(f"/car/{car_id}", headers=ADMIN).status_code == 204
    assert client.get(f"/car/{car_id}").status_code == 404


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_changes_require_admin_key(client, headers):
    assert client.post("/add-car", json={"name": "A", "model": "B"}, headers=headers).status_code == 401
    assert client.delete("/car/1", headers=headers).status_code == 401


def test_validation(client):
    assert client.post("/add-car", json={"name": "", "model": "B"}, headers=ADMIN).status_code == 422
    assert client.post("/add-car", json={"name": "A", "model": "B", "year": 1500}, headers=ADMIN).status_code == 422
    assert client.post("/add-car", json={"name": "A", "model": "B", "id": 1}, headers=ADMIN).status_code == 422
    assert client.get("/car/abc").status_code == 422
