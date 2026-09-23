"""initial durable state store"""
from alembic import op
import sqlalchemy as sa

revision = "0001_state_store"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("pharmascope_state_checkpoint", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("schema_version", sa.Integer(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))

def downgrade() -> None:
    op.drop_table("pharmascope_state_checkpoint")
