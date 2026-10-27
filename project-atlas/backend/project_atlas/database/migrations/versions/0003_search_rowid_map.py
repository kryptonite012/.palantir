"""Indexed rowid map for the FTS5 search index (fast deletes by ref_id / dataset_id).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("CREATE TABLE search_docs (rowid INTEGER PRIMARY KEY, ref_id TEXT NOT NULL, dataset_id TEXT)")
        op.execute("INSERT INTO search_docs (rowid, ref_id, dataset_id) SELECT rowid, ref_id, dataset_id FROM search_index")
        op.execute("CREATE INDEX ix_search_docs_ref ON search_docs (ref_id)")
        op.execute("CREATE INDEX ix_search_docs_dataset ON search_docs (dataset_id)")
    else:
        op.execute("CREATE INDEX IF NOT EXISTS ix_search_index_dataset ON search_index (dataset_id)")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TABLE IF EXISTS search_docs")
    else:
        op.execute("DROP INDEX IF EXISTS ix_search_index_dataset")
