"""Local Demo index foundation. No generated or sample match records."""
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('demo_files',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('sha256', sa.String(64), nullable=False, unique=True),
        sa.Column('path', sa.Text, nullable=False),
        sa.Column('size', sa.BigInteger, nullable=False),
        sa.Column('source', sa.Text, nullable=False, server_default='user_import'),
        sa.Column('license_status', sa.Text, nullable=False, server_default='unknown'),
        sa.Column('parser_version', sa.Text, nullable=True),
        sa.Column('status', sa.Text, nullable=False, server_default='queued'),
        sa.Column('created_at', sa.Text, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.CheckConstraint('size >= 0', name='ck_demo_size'),
        sa.CheckConstraint("length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'", name='ck_demo_sha256'),
        sa.CheckConstraint("status IN ('queued','validating','parsing','indexing','complete','partial','failed','canceled')", name='ck_demo_status'))
    op.create_index('ix_demo_files_status', 'demo_files', ['status'])
    op.create_table('matches',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('demo_id', sa.Text, sa.ForeignKey('demo_files.id', ondelete='RESTRICT'), nullable=False, unique=True),
        sa.Column('map', sa.Text, nullable=False),
        sa.Column('played_at', sa.Text, nullable=True),
        sa.Column('build', sa.Text, nullable=True),
        sa.Column('score', sa.Text, nullable=True))
    op.create_table('rounds',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('match_id', sa.Text, sa.ForeignKey('matches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('round_no', sa.Integer, nullable=False),
        sa.Column('start_tick', sa.BigInteger, nullable=False),
        sa.Column('end_tick', sa.BigInteger, nullable=True),
        sa.Column('winner', sa.Text, nullable=True),
        sa.UniqueConstraint('match_id', 'round_no', name='uq_round_match_no'),
        sa.CheckConstraint('round_no > 0', name='ck_round_number'),
        sa.CheckConstraint('start_tick >= 0 AND (end_tick IS NULL OR end_tick >= start_tick)', name='ck_round_ticks'))
    op.create_table('events',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('round_id', sa.Text, sa.ForeignKey('rounds.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tick', sa.BigInteger, nullable=False),
        sa.Column('type', sa.Text, nullable=False),
        sa.Column('actor', sa.Text, nullable=True),
        sa.Column('target', sa.Text, nullable=True),
        sa.Column('payload', sa.JSON, nullable=True),
        sa.CheckConstraint('tick >= 0', name='ck_event_tick'))
    op.create_index('ix_events_round_tick', 'events', ['round_id','tick'])


def downgrade():
    op.drop_index('ix_events_round_tick', table_name='events')
    op.drop_table('events')
    op.drop_table('rounds')
    op.drop_table('matches')
    op.drop_index('ix_demo_files_status', table_name='demo_files')
    op.drop_table('demo_files')
