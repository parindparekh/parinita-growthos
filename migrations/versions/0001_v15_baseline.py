"""GrowthOS v1.5 schema baseline.

The compatibility bootstrap creates/adds the v1.5 schema. Existing installations may be
stamped here after backup + verification. All later non-additive changes use Alembic.
"""
revision = '0001_v15_baseline'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass
