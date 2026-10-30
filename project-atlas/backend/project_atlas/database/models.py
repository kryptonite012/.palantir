"""Relational schema for Project Atlas.

All primary keys are stable string identifiers (UUID4 hex with a type
prefix) except the audit log, which uses a monotonically increasing integer
sequence so that the hash chain has a well-defined order.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


def _pk(prefix: str):
    return mapped_column(String(40), primary_key=True, default=lambda: new_id(prefix))


def _ts():
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# --------------------------------------------------------------------------- identity


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = _pk("usr")
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    global_role: Mapped[str | None] = mapped_column(String(32))  # system_admin | security_admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = _ts()
    created_at: Mapped[datetime] = _ts()


class UserSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = _pk("ses")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = _ts()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client: Mapped[str | None] = mapped_column(String(255))


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[str] = _pk("prt")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    issued_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()


# --------------------------------------------------------------------------- projects


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = _pk("prj")
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    classification: Mapped[str] = mapped_column(String(32), default="internal", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)
    id: Mapped[str] = _pk("pmb")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    added_at: Mapped[datetime] = _ts()


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = _ts()


# --------------------------------------------------------------------------- data


class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[str] = _pk("src")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # upload | directory
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    permitted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()


class StoredFile(Base):
    __tablename__ = "files"
    id: Mapped[str] = _pk("fil")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("data_sources.id"))
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False)  # relative to storage dir
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_format: Mapped[str] = mapped_column(String(32), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = _ts()


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    id: Mapped[str] = _pk("dst")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("data_sources.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    access_policy: Mapped[str] = mapped_column(String(32), default="project", nullable=False)  # project|restricted
    retention_policy: Mapped[str] = mapped_column(String(64), default="indefinite", nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = _ts()


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version"),)
    id: Mapped[str] = _pk("dsv")
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id"))
    parent_version_id: Mapped[str | None] = mapped_column(String(40))
    origin: Mapped[str] = mapped_column(String(32), default="import", nullable=False)  # import | workflow
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    import_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quality_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ingestion_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    imported_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    imported_at: Mapped[datetime] = _ts()


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (Index("ix_records_version_row", "dataset_version_id", "row_index"),)
    id: Mapped[str] = _pk("rec")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)  # original source values, untouched
    normalized: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)  # mapped + normalized values
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class QualityIssue(Base):
    __tablename__ = "quality_issues"
    id: Mapped[str] = _pk("qis")
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_index: Mapped[int | None] = mapped_column(Integer)
    field: Mapped[str | None] = mapped_column(String(128))
    check: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # info | warning | error
    message: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = _pk("job")
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------- ontology & entities


class EntityType(Base):
    __tablename__ = "entity_types"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    id: Mapped[str] = _pk("ety")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    fields: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    # each field: {name, type, required, sensitive, identifier, pattern}
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = _ts()


class RelationshipType(Base):
    __tablename__ = "relationship_types"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    id: Mapped[str] = _pk("rty")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    directed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_types: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    target_types: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = _ts()


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (Index("ix_entities_project_type", "project_id", "entity_type"),)
    id: Mapped[str] = _pk("ent")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_key: Mapped[str | None] = mapped_column(String(255), index=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # attributes: {field: [{value, normalized, source_record_id, dataset_version_id}]}
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active | merged
    merged_into_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class EntitySource(Base):
    __tablename__ = "entity_sources"
    id: Mapped[str] = _pk("esr")
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), nullable=False, index=True)
    original_entity_id: Mapped[str] = mapped_column(String(40), nullable=False)


class Relationship(Base):
    __tablename__ = "relationships"
    id: Mapped[str] = _pk("rel")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    target_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    rel_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # observed | inferred | model_suggested | manual
    assertion: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)  # active|unverified|rejected
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    record_id: Mapped[str | None] = mapped_column(ForeignKey("records.id", ondelete="SET NULL"))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)  # user id or "system:<component>"
    created_at: Mapped[datetime] = _ts()


class MatchCandidate(Base):
    __tablename__ = "match_candidates"
    __table_args__ = (UniqueConstraint("entity_a_id", "entity_b_id", "algorithm_version"),)
    id: Mapped[str] = _pk("mtc")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_a_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    entity_b_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[str] = mapped_column(String(16), nullable=False)  # strong | ambiguous | weak
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)  # pending|accepted|rejected
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class MergeHistory(Base):
    __tablename__ = "merge_history"
    id: Mapped[str] = _pk("mrg")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    survivor_id: Mapped[str] = mapped_column(String(40), nullable=False)
    merged_id: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_id: Mapped[str | None] = mapped_column(String(40))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    performed_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    performed_at: Mapped[datetime] = _ts()
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class GraphSnapshot(Base):
    __tablename__ = "graph_snapshots"
    id: Mapped[str] = _pk("gsn")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    node_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    edge_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    layout: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()


# --------------------------------------------------------------------------- documents


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = _pk("doc")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    language_confidence: Mapped[float | None] = mapped_column(Float)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[str] = mapped_column(String(64), default="unclassified", nullable=False)
    keywords: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    entity_candidates: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    duplicate_of_id: Mapped[str | None] = mapped_column(String(40))
    near_duplicates: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    ocr_status: Mapped[str] = mapped_column(String(32), default="not_required", nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[str] = _pk("chk")
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based page (or section for non-paged formats)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (UniqueConstraint("chunk_id", "model_id"),)
    id: Mapped[str] = _pk("emb")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False)
    model_id: Mapped[str] = mapped_column(String(40), nullable=False)
    dims: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # float32 little-endian
    created_at: Mapped[datetime] = _ts()


# --------------------------------------------------------------------------- temporal & geo


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_project_time", "project_id", "event_time"),)
    id: Mapped[str] = _pk("evt")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    record_id: Mapped[str | None] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="event", nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # UTC
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_timezone: Mapped[str | None] = mapped_column(String(64))
    source_time_text: Mapped[str | None] = mapped_column(String(64))  # original value as found
    record_created_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = _ts()
    modified_at: Mapped[datetime] = _ts()
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)


class GeoFeature(Base):
    __tablename__ = "geo_features"
    id: Mapped[str] = _pk("geo")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    layer: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="data", nullable=False)  # data | annotation | layer
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    geometry: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)  # GeoJSON geometry
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    feature_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_id: Mapped[str | None] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _ts()


# --------------------------------------------------------------------------- search & analysis


class SavedQuery(Base):
    __tablename__ = "saved_queries"
    id: Mapped[str] = _pk("sqy")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="search", nullable=False)  # search | sql
    query: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = _ts()


class QueryHistory(Base):
    __tablename__ = "query_history"
    id: Mapped[str] = _pk("qhs")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = _ts()


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[str] = _pk("anr")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)  # dataset version ids, graph state hash
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    software_version: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    reproduced_from_id: Mapped[str | None] = mapped_column(String(40))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()


# --------------------------------------------------------------------------- investigations


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[str] = _pk("inv")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    scope: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False)
    classification: Mapped[str] = mapped_column(String(32), default="internal", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()


class InvestigationCollaborator(Base):
    __tablename__ = "investigation_collaborators"
    __table_args__ = (UniqueConstraint("investigation_id", "user_id"),)
    id: Mapped[str] = _pk("icl")
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    added_at: Mapped[datetime] = _ts()


class InvestigationItem(Base):
    __tablename__ = "investigation_items"
    id: Mapped[str] = _pk("iit")
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    added_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    added_at: Mapped[datetime] = _ts()


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[str] = _pk("not")
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = _pk("evd")
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # record|document_chunk|entity|relationship|analysis
    source_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    classification: Mapped[str] = mapped_column(String(32), default="internal", nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    captured_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    captured_at: Mapped[datetime] = _ts()


class EvidenceRevision(Base):
    __tablename__ = "evidence_revisions"
    id: Mapped[str] = _pk("evr")
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    changed_at: Mapped[datetime] = _ts()


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = _pk("fnd")
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    # draft | under_review | confirmed_by_reviewer | disputed | rejected | superseded
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    basis: Mapped[str] = mapped_column(String(32), default="analyst_assessment", nullable=False)
    superseded_by_id: Mapped[str | None] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    history: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _ts()


class FindingEvidence(Base):
    __tablename__ = "finding_evidence"
    __table_args__ = (UniqueConstraint("finding_id", "evidence_id"),)
    id: Mapped[str] = _pk("fev")
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False)
    stance: Mapped[str] = mapped_column(String(16), nullable=False)  # supporting | contradicting


# --------------------------------------------------------------------------- workflows & reports


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[str] = _pk("wfl")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version"),)
    id: Mapped[str] = _pk("wfv")
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[str] = _pk("wfr")
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    node_results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    logs: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = _pk("rpt")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    investigation_id: Mapped[str | None] = mapped_column(ForeignKey("investigations.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class ReportExport(Base):
    __tablename__ = "report_exports"
    id: Mapped[str] = _pk("rex")
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()


# --------------------------------------------------------------------------- audit, AI, backup


class AuditEvent(Base):
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, default=lambda: new_id("aud"))
    ts: Mapped[datetime] = _ts()
    actor_id: Mapped[str | None] = mapped_column(String(40))
    actor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    project_id: Mapped[str | None] = mapped_column(String(40), index=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)  # success | denied | failure
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ModelRegistryEntry(Base):
    __tablename__ = "model_registry"
    id: Mapped[str] = _pk("mdl")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # chat | embedding | reranker | ocr
    runtime: Mapped[str] = mapped_column(String(32), default="ollama", nullable=False)
    runtime_model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(512))
    sha256: Mapped[str | None] = mapped_column(String(64))
    quantization: Mapped[str | None] = mapped_column(String(32))
    license: Mapped[str] = mapped_column(String(128), default="unspecified", nullable=False)
    ram_mb: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    health: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    health_detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()


class BackupManifest(Base):
    __tablename__ = "backup_manifests"
    id: Mapped[str] = _pk("bkp")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = _ts()


# --------------------------------------------------------------------------- personal workspace features


class SavedView(Base):
    """A named UI location (path + query string) a user wants to return to."""

    __tablename__ = "saved_views"
    id: Mapped[str] = _pk("svw")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = _ts()


class Watch(Base):
    """A user's watch on an entity: new evidence about it raises a notification."""

    __tablename__ = "watches"
    __table_args__ = (UniqueConstraint("user_id", "entity_id"),)
    id: Mapped[str] = _pk("wch")
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = _ts()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)
    id: Mapped[str] = _pk("ntf")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # job | watch | retention | system
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    link: Mapped[str | None] = mapped_column(String(1024))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
