"""Row-level domain repository and durable worker lease.

An existing 0001 checkpoint is imported on first application startup. It remains
intact until an operator verifies the upgrade and backup.
"""
from alembic import op
from backend.db import metadata
revision = '0002_relational_repository'
down_revision = '0001_state_store'
branch_labels = None
depends_on = None

def upgrade():
    metadata.create_all(op.get_bind())

def downgrade():
    metadata.drop_all(op.get_bind())
