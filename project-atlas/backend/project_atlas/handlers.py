"""Background job handlers (registered by kind)."""

from __future__ import annotations

from typing import Any

from project_atlas.core.jobs import JobReporter, register
from project_atlas.database.models import Job


@register("ingest")
def ingest_job(ctx, job: Job, reporter: JobReporter) -> dict[str, Any]:
    from project_atlas.ingestion.service import run_import

    reporter.progress(0.02, "Starting import")
    with ctx.sm() as db:
        report = run_import(ctx, db, project_id=job.project_id, user_id=job.created_by, cfg=job.params["config"],
                            dry_run=False, reporter=reporter)
    ctx.audit.record("ingest.completed", actor_id=job.created_by, actor_name="system:ingest", resource_type="dataset",
                     resource_id=report["dataset"]["id"], project_id=job.project_id,
                     details={"version": report["dataset"]["version"], "records": report["counts"]["records"],
                              "file_sha256": report["file"]["sha256"]})
    from project_atlas.notifications import watched_entities_updated

    with ctx.sm() as db:
        watched_entities_updated(db, project_id=job.project_id, dataset_version_id=report["dataset"]["version_id"],
                                 dataset_name=report["dataset"]["name"], actor_id=job.created_by)
        db.commit()
    reporter.progress(1.0, f"Imported {report['counts']['records']} records")
    return {"dataset": report["dataset"], "counts": report["counts"], "quality": report["quality"]}


@register("entity_resolution")
def resolution_job(ctx, job: Job, reporter: JobReporter) -> dict[str, Any]:
    from project_atlas.entities.service import resolve

    reporter.progress(0.05, "Generating match candidates")
    with ctx.sm() as db:
        res = resolve(db, job.project_id, job.params.get("entity_type"), float(job.params.get("threshold", 0.75)))
    reporter.progress(1.0, f"{res['candidates_created']} candidates")
    return res


@register("document_process")
def document_job(ctx, job: Job, reporter: JobReporter) -> dict[str, Any]:
    from project_atlas.documents.service import process_document

    reporter.progress(0.05, "Extracting text")
    with ctx.sm() as db:
        return process_document(ctx, db, project_id=job.project_id, user_id=job.created_by, **job.params)


@register("workflow_run")
def workflow_job(ctx, job: Job, reporter: JobReporter) -> dict[str, Any]:
    from project_atlas.workflows.engine import execute_run

    return execute_run(ctx, job, reporter)


@register("embed_documents")
def embed_job(ctx, job: Job, reporter: JobReporter) -> dict[str, Any]:
    from project_atlas.ai.service import embed_project_chunks

    return embed_project_chunks(ctx, job.project_id, job.params["model_id"], reporter)


@register("backup")
def backup_job(ctx, job: Job, reporter: JobReporter) -> dict[str, Any]:
    from project_atlas.backup.service import create_backup

    reporter.progress(0.1, "Snapshotting database")
    return create_backup(ctx, user_id=job.created_by, passphrase=None, kind=job.params.get("kind", "manual"))


@register("demo_load")
def demo_job(ctx, job: Job, reporter: JobReporter) -> dict[str, Any]:
    from project_atlas.demo.loader import load_demo

    res = load_demo(ctx, project_id=job.project_id, user_id=job.created_by, reporter=reporter)
    ctx.audit.record("demo.loaded", actor_id=job.created_by, actor_name="system:demo", resource_type="project",
                     resource_id=job.project_id, project_id=job.project_id, details={"datasets": res["datasets"]})
    return res


@register("retention_sweep")
def retention_job(ctx, job: Job, reporter: JobReporter) -> dict[str, Any]:
    from project_atlas.retention import apply_retention

    with ctx.sm() as db:
        return apply_retention(ctx, db, actor_id=job.created_by)
