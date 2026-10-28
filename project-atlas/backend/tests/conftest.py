from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "sample-data"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_atlas.core.config import load_settings  # noqa: E402
from project_atlas.main import create_app  # noqa: E402

ADMIN_PW = "Atlas-Test-Passw0rd!"


def make_settings(tmp: Path, **extra: str):
    env = {"ATLAS_ENV": "test", "ATLAS_STORAGE_DIR": str(tmp / "ws"), "ATLAS_BACKUP_DIR": str(tmp / "bk"),
           "ATLAS_MODEL_DIR": str(tmp / "models"), "ATLAS_JOBS_INLINE": "true", "ATLAS_LOG_LEVEL": "WARNING",
           "ATLAS_FRONTEND_DIST": str(tmp / "no-frontend"), **extra}
    return load_settings(env)


class Api:
    """Thin authenticated wrapper around TestClient."""

    def __init__(self, client: TestClient, token: str | None = None):
        self.c = client
        self.token = token

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def get(self, url, **kw):
        return self.c.get(url, headers=self._h(), **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers=self._h(), **kw)

    def put(self, url, **kw):
        return self.c.put(url, headers=self._h(), **kw)

    def patch(self, url, **kw):
        return self.c.patch(url, headers=self._h(), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(), **kw)

    def ok(self, resp, status=200):
        assert resp.status_code == status, resp.text
        return resp.json()

    def as_user(self, token):
        return Api(self.c, token)

    # convenience flows -----------------------------------------------------------------------
    def upload(self, pid, path: Path):
        with open(path, "rb") as f:
            return self.ok(self.post(f"/api/projects/{pid}/files", files={"file": (path.name, f)}))

    def import_file(self, pid, path: Path, config: dict):
        fid = self.upload(pid, path)["id"]
        job = self.ok(self.post(f"/api/projects/{pid}/ingest/commit", json={"config": {"file_id": fid, **config}}))
        assert job["status"] == "succeeded", job
        return job["result"]

    def login(self, username, password):
        return self.ok(self.c.post("/api/auth/login", json={"username": username, "password": password}))["token"]

    def create_user(self, username, password=ADMIN_PW, role=None):
        return self.ok(self.post("/api/admin/users", json={"username": username, "display_name": username.title(),
                                                           "password": password, "global_role": role}))


@pytest.fixture
def app(tmp_path):
    application = create_app(make_settings(tmp_path))
    yield application
    application.state.ctx.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client, app):
    token = app.state.ctx.ensure_setup_token()
    data = client.post("/api/auth/setup", json={"setup_token": token, "username": "admin", "display_name": "Admin",
                                                 "password": ADMIN_PW}).json()
    return Api(client, data["token"])


@pytest.fixture
def project(admin):
    return admin.ok(admin.post("/api/projects", json={"name": "Northwind Review", "description": "synthetic"}))


from project_atlas.demo.loader import CONTACTS as CONTACTS_CONFIG  # noqa: E402
from project_atlas.demo.loader import ORGANIZATIONS as ORG_CONFIG  # noqa: E402
from project_atlas.demo.loader import PEOPLE as PEOPLE_CONFIG  # noqa: E402
from project_atlas.demo.loader import TRANSACTIONS as TXN_CONFIG  # noqa: E402


def load_demo(api: Api, pid: str) -> dict:
    out = {}
    out["orgs"] = api.import_file(pid, SAMPLE / "synthetic_organizations.csv", ORG_CONFIG)
    out["people"] = api.import_file(pid, SAMPLE / "synthetic_people.csv", PEOPLE_CONFIG)
    out["contacts"] = api.import_file(pid, SAMPLE / "synthetic_contacts.csv", CONTACTS_CONFIG)
    out["txns"] = api.import_file(pid, SAMPLE / "synthetic_transactions.csv", TXN_CONFIG)
    return out
