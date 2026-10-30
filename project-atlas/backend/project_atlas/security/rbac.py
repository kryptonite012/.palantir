"""Role-based access control.

Two layers:
* global roles (system_admin, security_admin) govern platform administration;
* project roles govern access to everything inside a project.

System administrators do NOT implicitly read project data: data access is
always through project membership, which keeps administration and analysis
duties separable.
"""

from __future__ import annotations

GLOBAL_ROLES = {"system_admin", "security_admin"}

PROJECT_ROLES = ["project_admin", "data_engineer", "analyst", "reviewer", "read_only"]

ROLE_LABELS = {
    "system_admin": "System Administrator",
    "security_admin": "Security Administrator",
    "project_admin": "Project Administrator",
    "data_engineer": "Data Engineer",
    "analyst": "Analyst",
    "reviewer": "Reviewer",
    "read_only": "Read-Only User",
}

_READ = {
    "project.read", "dataset.read", "entity.read", "graph.read", "search.run", "document.read",
    "timeline.read", "geo.read", "analysis.read", "investigation.read", "workflow.read", "report.read",
}

PROJECT_PERMISSIONS: dict[str, set[str]] = {
    "read_only": set(_READ),
    "reviewer": _READ | {
        "entity.review", "finding.review", "analysis.run", "query.sql", "investigation.write", "evidence.write",
    },
    "analyst": _READ | {
        "analysis.run", "query.sql", "investigation.write", "investigation.create", "evidence.write",
        "finding.write", "report.write", "report.export", "graph.write", "geo.write", "workflow.run",
        "workflow.write", "ai.use", "document.write",
    },
    "data_engineer": _READ | {
        "dataset.write", "dataset.read_restricted", "ingest.run", "ontology.write", "entity.write",
        "entity.resolve", "entity.review", "analysis.run", "query.sql", "document.write", "workflow.run",
        "workflow.write", "workflow.write_data", "graph.write", "geo.write", "report.write", "report.export",
        "ai.use", "investigation.write", "evidence.write", "finding.write", "investigation.create",
    },
}
PROJECT_PERMISSIONS["project_admin"] = set().union(*PROJECT_PERMISSIONS.values()) | {
    "project.manage", "members.manage", "sensitive.read", "sensitive.export", "dataset.delete",
}

GLOBAL_PERMISSIONS: dict[str, set[str]] = {
    "system_admin": {
        "admin.users", "admin.projects", "admin.backup", "admin.restore", "admin.settings", "admin.models",
        "audit.read", "system.status", "project.create",
    },
    "security_admin": {"admin.users.security", "audit.read", "audit.verify", "system.status", "sessions.revoke"},
}


def project_permissions(role: str | None) -> set[str]:
    return set(PROJECT_PERMISSIONS.get(role or "", set()))


def global_permissions(role: str | None) -> set[str]:
    return set(GLOBAL_PERMISSIONS.get(role or "", set()))
