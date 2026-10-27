"""Full-text search index and append-only audit guards.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            "CREATE VIRTUAL TABLE search_index USING fts5("
            "doc_type UNINDEXED, ref_id UNINDEXED, project_id UNINDEXED, dataset_id UNINDEXED, "
            "access UNINDEXED, created_at UNINDEXED, title, body, tokenize='unicode61 remove_diacritics 2')"
        )
        op.execute(
            "CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"
        )
    else:
        op.execute(
            "CREATE TABLE search_index (rowid BIGSERIAL PRIMARY KEY, doc_type TEXT, ref_id TEXT, project_id TEXT, "
            "dataset_id TEXT, access TEXT, created_at TEXT, title TEXT, body TEXT, "
            "tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(body,''))) STORED)"
        )
        op.execute("CREATE INDEX ix_search_index_tsv ON search_index USING GIN (tsv)")
        op.execute("CREATE INDEX ix_search_index_ref ON search_index (ref_id)")
        op.execute(
            "CREATE FUNCTION atlas_audit_guard() RETURNS trigger AS $$ BEGIN "
            "RAISE EXCEPTION 'audit_events is append-only'; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER audit_no_modify BEFORE UPDATE OR DELETE ON audit_events "
            "FOR EACH ROW EXECUTE FUNCTION atlas_audit_guard()"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS audit_no_update")
        op.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    else:
        op.execute("DROP TRIGGER IF EXISTS audit_no_modify ON audit_events")
        op.execute("DROP FUNCTION IF EXISTS atlas_audit_guard")
    op.execute("DROP TABLE IF EXISTS search_index")
