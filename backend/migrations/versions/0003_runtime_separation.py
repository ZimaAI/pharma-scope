"""Persist runtime identity to prevent replay/live database mixing."""
from alembic import op
from backend.db import runtime_meta
revision='0003_runtime_separation'
down_revision='0002_relational_repository'
branch_labels=None
depends_on=None

def upgrade(): runtime_meta.create(op.get_bind(),checkfirst=True)
def downgrade(): runtime_meta.drop(op.get_bind())
