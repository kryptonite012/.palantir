"""Ontology: entity types, relationship types, field definitions and validation."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from project_atlas.core.errors import ValidationFailed
from project_atlas.database.models import EntityType, RelationshipType

FIELD_TYPES = {"string", "integer", "float", "boolean", "date", "datetime", "email", "phone", "identifier", "geo"}


def _f(name: str, type_: str = "string", *, identifier: bool = False, sensitive: bool = False,
       required: bool = False, pattern: str | None = None) -> dict[str, Any]:
    return {"name": name, "type": type_, "identifier": identifier, "sensitive": sensitive,
            "required": required, "pattern": pattern}


DEFAULT_ENTITY_TYPES: list[dict[str, Any]] = [
    {"name": "person", "label": "Person", "fields": [
        _f("name", required=True), _f("email", "email", identifier=True, sensitive=True),
        _f("phone", "phone", identifier=True, sensitive=True), _f("date_of_birth", "date", sensitive=True),
        _f("national_id", "identifier", identifier=True, sensitive=True), _f("city")]},
    {"name": "organization", "label": "Organization", "fields": [
        _f("name", required=True), _f("registration_number", "identifier", identifier=True), _f("country"),
        _f("sector")]},
    {"name": "location", "label": "Location", "fields": [
        _f("name", required=True), _f("latitude", "float"), _f("longitude", "float"), _f("country")]},
    {"name": "event", "label": "Event", "fields": [_f("name", required=True), _f("event_time", "datetime")]},
    {"name": "document", "label": "Document", "fields": [_f("name", required=True), _f("document_id", "identifier", identifier=True)]},
    {"name": "account", "label": "Account", "fields": [
        _f("name", required=True), _f("account_number", "identifier", identifier=True, sensitive=True), _f("institution")]},
    {"name": "asset", "label": "Asset", "fields": [_f("name", required=True), _f("serial_number", "identifier", identifier=True)]},
    {"name": "transaction", "label": "Transaction", "fields": [
        _f("name", required=True), _f("transaction_id", "identifier", identifier=True), _f("amount", "float"),
        _f("currency"), _f("event_time", "datetime")]},
    {"name": "device", "label": "Device", "fields": [_f("name", required=True), _f("device_id", "identifier", identifier=True)]},
    {"name": "project", "label": "Project", "fields": [_f("name", required=True), _f("code", "identifier", identifier=True)]},
]

DEFAULT_RELATIONSHIP_TYPES = [
    ("works_for", "Works for", True, ["person"], ["organization"]),
    ("located_in", "Located in", True, [], ["location"]),
    ("owns", "Owns", True, ["person", "organization"], ["account", "asset", "device"]),
    ("transacted_with", "Transacted with", True, [], []),
    ("associated_with", "Associated with", False, [], []),
    ("participated_in", "Participated in", True, [], ["event", "transaction", "project"]),
    ("mentioned_in", "Mentioned in", True, [], ["document"]),
    ("sent_payment", "Sent payment", True, ["account", "person", "organization"], ["transaction"]),
    ("received_payment", "Received payment", True, ["transaction"], ["account", "person", "organization"]),
]

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def seed_project_ontology(db: Session, project_id: str) -> None:
    for et in DEFAULT_ENTITY_TYPES:
        db.add(EntityType(project_id=project_id, name=et["name"], label=et["label"], fields=et["fields"]))
    for name, label, directed, src, tgt in DEFAULT_RELATIONSHIP_TYPES:
        db.add(RelationshipType(project_id=project_id, name=name, label=label, directed=directed,
                                source_types=src, target_types=tgt))


def validate_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for f in fields:
        name = str(f.get("name", ""))
        if not _NAME_RE.match(name):
            raise ValidationFailed(f"Invalid field name {name!r}: use lowercase letters, digits, underscore")
        if name in seen:
            raise ValidationFailed(f"Duplicate field {name}")
        seen.add(name)
        t = f.get("type", "string")
        if t not in FIELD_TYPES:
            raise ValidationFailed(f"Unknown field type {t!r}")
        pattern = f.get("pattern")
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValidationFailed(f"Invalid pattern for {name}: {exc}") from exc
        out.append(_f(name, t, identifier=bool(f.get("identifier")), sensitive=bool(f.get("sensitive")),
                      required=bool(f.get("required")), pattern=pattern))
    if "name" not in seen:
        raise ValidationFailed("Every entity type needs a 'name' field")
    return out


def validate_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise ValidationFailed("Type names must be lowercase identifiers (a-z, 0-9, _)")
    return name


def entity_types(db: Session, project_id: str) -> dict[str, EntityType]:
    return {e.name: e for e in db.execute(select(EntityType).where(EntityType.project_id == project_id)).scalars()}


def sensitive_fields(db: Session, project_id: str) -> dict[str, set[str]]:
    return {name: {f["name"] for f in et.fields if f.get("sensitive")} for name, et in entity_types(db, project_id).items()}


def relationship_type_names(db: Session, project_id: str) -> set[str]:
    return set(db.execute(select(RelationshipType.name).where(RelationshipType.project_id == project_id)).scalars())
