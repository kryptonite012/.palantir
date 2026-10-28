"""Build the synthetic Northwind Harbor demonstration workspace inside a project.

Generates the deterministic SYNTHETIC files, then runs them through the normal, audited
pipelines (upload → import / document processing / GeoJSON layer), so the demo exercises
exactly the same code paths as real data.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from project_atlas.demo.generator import generate

if TYPE_CHECKING:
    from project_atlas.core.context import AtlasContext
    from project_atlas.core.jobs import JobReporter

ORGANIZATIONS = {
    "dataset_name": "organizations", "is_synthetic": True, "description": "SYNTHETIC organizations",
    "mapping": {"org_id": {"target": "org_id", "type": "identifier"}, "name": {"target": "name", "type": "string"},
                "registration_number": {"target": "registration_number", "type": "identifier"},
                "country": {"target": "country", "type": "string"}, "sector": {"target": "sector", "type": "string"},
                "record_origin": {"target": "record_origin", "type": "string"}},
    "entities": [{"entity_type": "organization", "name_field": "name", "id_field": "org_id",
                  "id_namespace": "org_id", "attributes": ["registration_number", "country"]}],
}

PEOPLE = {
    "dataset_name": "people", "is_synthetic": True, "description": "SYNTHETIC staff register",
    "mapping": {
        "person_id": {"target": "person_id", "type": "identifier"},
        "full_name": {"target": "full_name", "type": "string", "required": True},
        "email": {"target": "email", "type": "email", "sensitive": True},
        "phone": {"target": "phone", "type": "phone", "sensitive": True},
        "date_of_birth": {"target": "date_of_birth", "type": "date", "sensitive": True},
        "city": {"target": "city", "type": "string"},
        "employer_id": {"target": "employer_id", "type": "identifier"},
        "record_origin": {"target": "record_origin", "type": "string"},
    },
    "quality": {"unique": ["person_id"]},
    "entities": [
        {"entity_type": "person", "name_field": "full_name", "id_field": "person_id",
         "attributes": ["email", "phone", "date_of_birth", "city"]},
        {"entity_type": "organization", "id_field": "employer_id", "id_namespace": "org_id"},
    ],
    "relationships": [{"source": 0, "target": 1, "rel_type": "works_for"}],
}

CONTACTS = {
    "dataset_name": "contacts", "is_synthetic": True, "description": "SYNTHETIC second-source contact list (no ids)",
    "mapping": {"name": {"target": "name", "type": "string"}, "email": {"target": "email", "type": "email", "sensitive": True},
                "phone": {"target": "phone", "type": "phone", "sensitive": True}, "city": {"target": "city", "type": "string"},
                "source_note": {"target": "source_note", "type": "string"},
                "record_origin": {"target": "record_origin", "type": "string"}},
    "entities": [{"entity_type": "person", "name_field": "name", "attributes": ["email", "phone", "city"]}],
}

TRANSACTIONS = {
    "dataset_name": "transactions", "is_synthetic": True, "description": "SYNTHETIC payments with locations",
    "mapping": {"txn_id": {"target": "txn_id", "type": "identifier"}, "sender_id": {"target": "sender_id", "type": "identifier"},
                "receiver_org_id": {"target": "receiver_org_id", "type": "identifier"},
                "amount": {"target": "amount", "type": "float"}, "currency": {"target": "currency", "type": "string"},
                "timestamp": {"target": "event_time", "type": "datetime"},
                "latitude": {"target": "latitude", "type": "latitude"}, "longitude": {"target": "longitude", "type": "longitude"},
                "city": {"target": "city", "type": "string"}, "record_origin": {"target": "record_origin", "type": "string"}},
    "entities": [{"entity_type": "person", "id_field": "sender_id", "id_namespace": "person_id"},
                 {"entity_type": "organization", "id_field": "receiver_org_id", "id_namespace": "org_id"}],
    "relationships": [{"source": 0, "target": 1, "rel_type": "transacted_with", "valid_from_field": "event_time"}],
    "events": {"time_field": "event_time", "title_template": "Payment {txn_id}: {amount} {currency}", "category": "payment", "entity": 0},
    "geo": {"lat_field": "latitude", "lon_field": "longitude", "label_field": "txn_id", "entity": 0, "time_field": "event_time"},
}

DATASETS = [("synthetic_organizations.csv", ORGANIZATIONS), ("synthetic_people.csv", PEOPLE),
            ("synthetic_contacts.csv", CONTACTS), ("synthetic_transactions.csv", TRANSACTIONS)]
DOCUMENTS = ["synthetic_harbor_audit_report.pdf", "synthetic_meeting_minutes.docx", "synthetic_shipment_email.eml",
             "synthetic_memo_cold_storage.txt", "synthetic_suspicious_note.txt"]


def load_demo(ctx: "AtlasContext", *, project_id: str, user_id: str, reporter: "JobReporter | None" = None) -> dict[str, Any]:
    from project_atlas.documents.service import process_document
    from project_atlas.entities.service import resolve
    from project_atlas.geospatial.service import import_geojson
    from project_atlas.ingestion.service import run_import, store_upload

    def step(frac: float, msg: str) -> None:
        if reporter:
            reporter.progress(frac, msg)

    out: dict[str, Any] = {"datasets": {}, "documents": 0}
    with tempfile.TemporaryDirectory(dir=ctx.settings.storage_dir) as td:
        root = Path(td)
        expected = generate(root)
        total = len(DATASETS) + len(DOCUMENTS) + 2
        n = 0
        for name, cfg in DATASETS:
            n += 1
            step(n / total, f"Importing {name}")
            with ctx.sm() as db:
                with open(root / name, "rb") as fh:
                    f = store_upload(ctx, db, project_id=project_id, user_id=user_id, filename=name, stream=fh)
                rep = run_import(ctx, db, project_id=project_id, user_id=user_id, cfg={"file_id": f.id, **cfg}, dry_run=False)
            out["datasets"][cfg["dataset_name"]] = rep["counts"]["records"]
        for name in DOCUMENTS:
            n += 1
            path = root / name
            if not path.exists():  # optional generators (python-docx / reportlab) missing
                continue
            step(n / total, f"Processing {name}")
            with ctx.sm() as db:
                with open(path, "rb") as fh:
                    f = store_upload(ctx, db, project_id=project_id, user_id=user_id, filename=name, stream=fh)
                process_document(ctx, db, project_id=project_id, user_id=user_id, file_id=f.id, is_synthetic=True)
            out["documents"] += 1
        step((n + 1) / total, "Adding district polygons")
        with ctx.sm() as db:
            out["geo_features"] = import_geojson(db, project_id, "districts", (root / "synthetic_districts.geojson").read_bytes(), user_id)
            db.commit()
        step((n + 2) / total, "Generating match candidates")
        with ctx.sm() as db:
            out["resolution"] = resolve(db, project_id, "person")
    out["expected"] = expected["entity_resolution"]
    return out
