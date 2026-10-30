"""Projects/workspaces, membership, data sources and ontology management."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from project_atlas.api.common import audit
from project_atlas.api.deps import Principal, ProjectAccess, current_principal, get_ctx, get_db, project_access
from project_atlas.core.context import AtlasContext
from project_atlas.core.errors import Conflict, NotFound, ValidationFailed
from project_atlas.database.models import (
    DataSource, Dataset, Document, Entity, EntityType, Investigation, Job, Project, ProjectMember, QualityIssue,
    Relationship, RelationshipType, Record, StoredFile, User, DatasetVersion, ModelRegistryEntry,
)
from project_atlas.ontology import service as ontology
from project_atlas.security.rbac import PROJECT_ROLES, ROLE_LABELS

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    classification: str = Field(default="internal", pattern=r"^(public|internal|confidential|restricted)$")


class MemberUpsert(BaseModel):
    user_id: str
    role: str


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: str = Field(default="upload", pattern=r"^(upload|removable_media|network_share|manual)$")
    description: str = ""


class EntityTypeBody(BaseModel):
    name: str
    label: str
    fields: list[dict]


class RelTypeBody(BaseModel):
    name: str
    label: str
    directed: bool = True
    source_types: list[str] = []
    target_types: list[str] = []


def project_view(p: Project, role: str | None = None) -> dict:
    return {"id": p.id, "name": p.name, "description": p.description, "classification": p.classification,
            "created_at": p.created_at, "archived": p.archived, "role": role, "role_label": ROLE_LABELS.get(role or "")}


@router.get("")
def list_projects(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    rows = db.execute(select(Project, ProjectMember.role).join(ProjectMember, ProjectMember.project_id == Project.id)
                      .where(ProjectMember.user_id == p.id).order_by(Project.name)).all()
    return [project_view(pr, role) for pr, role in rows]


@router.post("")
def create_project(body: ProjectCreate, p: Principal = Depends(current_principal), db: Session = Depends(get_db),
                   ctx: AtlasContext = Depends(get_ctx)):
    p.require_global("project.create")
    if db.execute(select(Project).where(Project.name == body.name)).scalar_one_or_none():
        raise Conflict("A project with this name already exists")
    pr = Project(name=body.name, description=body.description, classification=body.classification, created_by=p.id)
    db.add(pr)
    db.flush()
    db.add(ProjectMember(project_id=pr.id, user_id=p.id, role="project_admin"))
    db.add(DataSource(project_id=pr.id, name="Local uploads", kind="upload", created_by=p.id,
                      description="Files uploaded through the Project Atlas interface"))
    ontology.seed_project_ontology(db, pr.id)
    db.commit()
    audit(ctx, p, "project.create", "project", pr.id, details={"name": pr.name})
    return project_view(pr, "project_admin")


@router.get("/{project_id}")
def get_project(acc: ProjectAccess = Depends(project_access)):
    return {**project_view(acc.project, acc.role), "permissions": sorted(acc.perms)}


@router.get("/{project_id}/overview")
def overview(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    """Locally computed statistics for the home dashboard (all zeros when empty)."""
    pid = acc.project_id

    def count(model, *where):
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    readable_restricted = acc.can("dataset.read_restricted")
    ds_where = [Dataset.project_id == pid] + ([] if readable_restricted else [Dataset.access_policy != "restricted"])
    jobs = db.execute(select(Job.status, func.count()).where(Job.project_id == pid).group_by(Job.status)).all()
    quality_warnings = db.execute(
        select(func.count()).select_from(QualityIssue).join(DatasetVersion, DatasetVersion.id == QualityIssue.dataset_version_id)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id).where(*ds_where, DatasetVersion.version == Dataset.current_version)
    ).scalar_one()
    storage = db.execute(select(func.coalesce(func.sum(StoredFile.size_bytes), 0)).where(StoredFile.project_id == pid)).scalar_one()
    rel_by_assertion = dict(db.execute(select(Relationship.assertion, func.count()).where(Relationship.project_id == pid)
                                       .group_by(Relationship.assertion)).all())
    ai_models = count(ModelRegistryEntry, ModelRegistryEntry.enabled.is_(True), ModelRegistryEntry.health == "healthy")
    return {
        "datasets": count(Dataset, *ds_where),
        "records": db.execute(select(func.count()).select_from(Record).join(Dataset, Dataset.id == Record.dataset_id)
                              .join(DatasetVersion, DatasetVersion.id == Record.dataset_version_id)
                              .where(*ds_where, DatasetVersion.version == Dataset.current_version)).scalar_one(),
        "entities": count(Entity, Entity.project_id == pid, Entity.status == "active"),
        "relationships": sum(rel_by_assertion.values()),
        "relationships_by_assertion": rel_by_assertion,
        "documents": count(Document, Document.project_id == pid),
        "investigations": count(Investigation, Investigation.project_id == pid),
        "jobs": dict(jobs),
        "quality_issues_current": quality_warnings,
        "storage_bytes": int(storage),
        "ai": {"enabled": ctx.settings.ai_enabled, "healthy_models": ai_models},
    }


# --------------------------------------------------------------------------- membership


@router.get("/{project_id}/members")
def list_members(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    rows = db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id)
                      .where(ProjectMember.project_id == acc.project_id)).all()
    return [{"user_id": u.id, "username": u.username, "display_name": u.display_name, "role": m.role,
             "role_label": ROLE_LABELS[m.role]} for m, u in rows]


@router.put("/{project_id}/members")
def upsert_member(body: MemberUpsert, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                  ctx: AtlasContext = Depends(get_ctx)):
    acc.require("members.manage")
    if body.role not in PROJECT_ROLES:
        raise ValidationFailed(f"Role must be one of {PROJECT_ROLES}")
    if db.get(User, body.user_id) is None:
        raise NotFound("User not found")
    m = db.execute(select(ProjectMember).where(ProjectMember.project_id == acc.project_id,
                                               ProjectMember.user_id == body.user_id)).scalar_one_or_none()
    old = m.role if m else None
    if m and m.role == "project_admin" and body.role != "project_admin":
        admins = db.execute(select(func.count()).select_from(ProjectMember).where(
            ProjectMember.project_id == acc.project_id, ProjectMember.role == "project_admin")).scalar_one()
        if admins <= 1:
            raise Conflict("A project must keep at least one project administrator")
    if m:
        m.role = body.role
    else:
        db.add(ProjectMember(project_id=acc.project_id, user_id=body.user_id, role=body.role))
    db.commit()
    audit(ctx, acc, "permission.member_set", "project_member", body.user_id, details={"role": body.role, "previous": old})
    return {"ok": True}


@router.delete("/{project_id}/members/{user_id}")
def remove_member(user_id: str, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                  ctx: AtlasContext = Depends(get_ctx)):
    acc.require("members.manage")
    m = db.execute(select(ProjectMember).where(ProjectMember.project_id == acc.project_id,
                                               ProjectMember.user_id == user_id)).scalar_one_or_none()
    if m is None:
        raise NotFound("Member not found")
    if m.role == "project_admin":
        admins = db.execute(select(func.count()).select_from(ProjectMember).where(
            ProjectMember.project_id == acc.project_id, ProjectMember.role == "project_admin")).scalar_one()
        if admins <= 1:
            raise Conflict("Cannot remove the last project administrator")
    db.delete(m)
    db.commit()
    audit(ctx, acc, "permission.member_removed", "project_member", user_id)
    return {"ok": True}


# --------------------------------------------------------------------------- data sources


@router.get("/{project_id}/sources")
def list_sources(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    rows = db.execute(select(DataSource).where(DataSource.project_id == acc.project_id)).scalars().all()
    return [{"id": s.id, "name": s.name, "kind": s.kind, "description": s.description, "permitted": s.permitted,
             "created_at": s.created_at} for s in rows]


@router.post("/{project_id}/sources")
def create_source(body: SourceCreate, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                  ctx: AtlasContext = Depends(get_ctx)):
    acc.require("dataset.write")
    s = DataSource(project_id=acc.project_id, name=body.name, kind=body.kind, description=body.description,
                   created_by=acc.principal.id)
    db.add(s)
    db.commit()
    audit(ctx, acc, "source.create", "data_source", s.id, details={"name": s.name})
    return {"id": s.id}


@router.patch("/{project_id}/sources/{source_id}")
def set_source_permitted(source_id: str, permitted: bool, acc: ProjectAccess = Depends(project_access),
                         db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    acc.require("project.manage")
    s = db.get(DataSource, source_id)
    if s is None or s.project_id != acc.project_id:
        raise NotFound("Source not found")
    s.permitted = permitted
    db.commit()
    audit(ctx, acc, "source.permitted_changed", "data_source", s.id, details={"permitted": permitted})
    return {"ok": True}


# --------------------------------------------------------------------------- ontology


@router.get("/{project_id}/ontology")
def get_ontology(acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db)):
    ets = db.execute(select(EntityType).where(EntityType.project_id == acc.project_id).order_by(EntityType.name)).scalars().all()
    rts = db.execute(select(RelationshipType).where(RelationshipType.project_id == acc.project_id)
                     .order_by(RelationshipType.name)).scalars().all()
    return {"entity_types": [{"id": e.id, "name": e.name, "label": e.label, "fields": e.fields,
                              "schema_version": e.schema_version} for e in ets],
            "relationship_types": [{"id": r.id, "name": r.name, "label": r.label, "directed": r.directed,
                                    "source_types": r.source_types, "target_types": r.target_types} for r in rts],
            "field_types": sorted(ontology.FIELD_TYPES)}


@router.put("/{project_id}/ontology/entity-types")
def upsert_entity_type(body: EntityTypeBody, acc: ProjectAccess = Depends(project_access), db: Session = Depends(get_db),
                       ctx: AtlasContext = Depends(get_ctx)):
    acc.require("ontology.write")
    name = ontology.validate_name(body.name)
    fields = ontology.validate_fields(body.fields)
    et = db.execute(select(EntityType).where(EntityType.project_id == acc.project_id, EntityType.name == name)).scalar_one_or_none()
    if et:
        if et.fields != fields or et.label != body.label:
            et.fields, et.label = fields, body.label
            et.schema_version += 1
    else:
        et = EntityType(project_id=acc.project_id, name=name, label=body.label, fields=fields)
        db.add(et)
    db.commit()
    audit(ctx, acc, "ontology.entity_type_saved", "entity_type", et.id, details={"name": name, "version": et.schema_version})
    return {"id": et.id, "schema_version": et.schema_version}


@router.put("/{project_id}/ontology/relationship-types")
def upsert_relationship_type(body: RelTypeBody, acc: ProjectAccess = Depends(project_access),
                             db: Session = Depends(get_db), ctx: AtlasContext = Depends(get_ctx)):
    acc.require("ontology.write")
    name = ontology.validate_name(body.name)
    known = set(ontology.entity_types(db, acc.project_id))
    for t in body.source_types + body.target_types:
        if t not in known:
            raise ValidationFailed(f"Unknown entity type {t}")
    rt = db.execute(select(RelationshipType).where(RelationshipType.project_id == acc.project_id,
                                                   RelationshipType.name == name)).scalar_one_or_none()
    if rt is None:
        rt = RelationshipType(project_id=acc.project_id, name=name, label=body.label)
        db.add(rt)
    rt.label, rt.directed, rt.source_types, rt.target_types = body.label, body.directed, body.source_types, body.target_types
    db.commit()
    audit(ctx, acc, "ontology.relationship_type_saved", "relationship_type", rt.id, details={"name": name})
    return {"id": rt.id}
