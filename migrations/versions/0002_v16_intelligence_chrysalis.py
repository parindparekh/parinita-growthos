"""GrowthOS v1.6 media intelligence, opportunity, claim graph and Chrysalis receipt tables."""
from alembic import op
import sqlalchemy as sa

revision = '0002_v16_intelligence_chrysalis'
down_revision = '0001_v15_baseline'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('media_contacts',
        sa.Column('id', sa.String(64), primary_key=True), sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('external_id', sa.String(300), nullable=False), sa.Column('name', sa.String(300), nullable=False),
        sa.Column('outlet', sa.String(300), nullable=False, server_default=''), sa.Column('beat', sa.String(500), nullable=False, server_default=''),
        sa.Column('email', sa.String(500), nullable=False, server_default=''), sa.Column('profile_url', sa.String(2000), nullable=False, server_default=''),
        sa.Column('location', sa.String(300), nullable=False, server_default=''), sa.Column('influence_score', sa.String(64), nullable=False, server_default='0'),
        sa.Column('metadata_json', sa.Text(), nullable=False, server_default='{}'), sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)), sa.UniqueConstraint('provider','external_id',name='uq_media_contact_provider_external'))
    op.create_index('ix_media_contacts_provider','media_contacts',['provider']); op.create_index('ix_media_contacts_name','media_contacts',['name']); op.create_index('ix_media_contacts_outlet','media_contacts',['outlet'])

    op.create_table('media_coverage',
        sa.Column('id', sa.String(64), primary_key=True), sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('external_id', sa.String(300), nullable=False), sa.Column('title', sa.String(500), nullable=False),
        sa.Column('url', sa.String(2000), nullable=False, server_default=''), sa.Column('outlet', sa.String(300), nullable=False, server_default=''),
        sa.Column('author', sa.String(300), nullable=False, server_default=''), sa.Column('body', sa.Text(), nullable=False, server_default=''),
        sa.Column('topics_json', sa.Text(), nullable=False, server_default='[]'), sa.Column('sentiment', sa.String(30), nullable=False, server_default='unknown'),
        sa.Column('content_id', sa.String(64), nullable=True), sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=False, server_default='{}'), sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('provider','external_id',name='uq_media_coverage_provider_external'))
    for name, cols in [('ix_media_coverage_provider',['provider']),('ix_media_coverage_url',['url']),('ix_media_coverage_outlet',['outlet']),('ix_media_coverage_author',['author']),('ix_media_coverage_content_id',['content_id']),('ix_media_coverage_published_at',['published_at']),('ix_media_coverage_created_at',['created_at'])]: op.create_index(name,'media_coverage',cols)

    op.create_table('opportunities',
        sa.Column('id', sa.String(64), primary_key=True), sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(50), nullable=False), sa.Column('title', sa.String(500), nullable=False), sa.Column('summary', sa.Text(), nullable=False, server_default=''),
        sa.Column('score', sa.String(64), nullable=False, server_default='0'), sa.Column('status', sa.String(30), nullable=False, server_default='new'),
        sa.Column('source_refs_json', sa.Text(), nullable=False, server_default='[]'), sa.Column('recommendation_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_by_agent', sa.String(100), nullable=False, server_default='Parinita Signal Agent'), sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)), sa.UniqueConstraint('fingerprint',name='uq_opportunity_fingerprint'))
    for name, cols in [('ix_opportunities_fingerprint',['fingerprint']),('ix_opportunities_kind',['kind']),('ix_opportunities_score',['score']),('ix_opportunities_status',['status']),('ix_opportunities_created_at',['created_at'])]: op.create_index(name,'opportunities',cols)

    op.create_table('claim_observations',
        sa.Column('id', sa.String(64), primary_key=True), sa.Column('content_id', sa.String(64), nullable=False),
        sa.Column('sentence_hash', sa.String(32), nullable=False, server_default=''), sa.Column('claim_text', sa.Text(), nullable=False),
        sa.Column('observation_type', sa.String(50), nullable=False), sa.Column('provider', sa.String(100), nullable=False, server_default=''),
        sa.Column('uri', sa.String(2000), nullable=False, server_default=''), sa.Column('observed_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('matched_score', sa.String(64), nullable=False, server_default='0'), sa.Column('metadata_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True)))
    for name, cols in [('ix_claim_observations_content_id',['content_id']),('ix_claim_observations_sentence_hash',['sentence_hash']),('ix_claim_observations_observation_type',['observation_type']),('ix_claim_observations_uri',['uri']),('ix_claim_observations_created_at',['created_at'])]: op.create_index(name,'claim_observations',cols)

    op.create_table('chrysalis_anchors',
        sa.Column('id', sa.String(64), primary_key=True), sa.Column('anchor_type', sa.String(30), nullable=False),
        sa.Column('content_id', sa.String(64), nullable=True), sa.Column('content_hash', sa.String(64), nullable=False, server_default=''),
        sa.Column('audit_head_hash', sa.String(64), nullable=False, server_default=''), sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('chrysalis_ref', sa.String(300), nullable=False, server_default=''), sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('receipt_json', sa.Text(), nullable=False, server_default='{}'), sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True)), sa.Column('anchored_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('anchor_type','content_id','content_hash','audit_head_hash',name='uq_chrysalis_anchor_subject'))
    for name, cols in [('ix_chrysalis_anchors_anchor_type',['anchor_type']),('ix_chrysalis_anchors_content_id',['content_id']),('ix_chrysalis_anchors_payload_hash',['payload_hash']),('ix_chrysalis_anchors_chrysalis_ref',['chrysalis_ref']),('ix_chrysalis_anchors_status',['status']),('ix_chrysalis_anchors_created_at',['created_at'])]: op.create_index(name,'chrysalis_anchors',cols)


def downgrade():
    for table in ['chrysalis_anchors','claim_observations','opportunities','media_coverage','media_contacts']:
        op.drop_table(table)
