"""Agent conversation registry for persistent multi-conversation management."""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'agent_conversations',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('thread_id', sa.String(128), nullable=False),
        sa.Column('user_id', sa.String(255), nullable=False),
        sa.Column('title', sa.String(255), nullable=False, server_default='Cuộc trò chuyện mới'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.UniqueConstraint('thread_id', name='uq_agent_conversations_thread_id'),
    )
    op.create_index('ix_agent_conversations_thread_id', 'agent_conversations', ['thread_id'])
    op.create_index('ix_agent_conversations_user_id', 'agent_conversations', ['user_id'])
    op.create_index('ix_agent_conversations_user_updated', 'agent_conversations', ['user_id', 'updated_at'])
    op.create_index('ix_agent_conversations_user_last_msg', 'agent_conversations', ['user_id', 'last_message_at'])
    op.create_index('ix_agent_conversations_status', 'agent_conversations', ['status'])


def downgrade():
    op.drop_index('ix_agent_conversations_status', table_name='agent_conversations')
    op.drop_index('ix_agent_conversations_user_last_msg', table_name='agent_conversations')
    op.drop_index('ix_agent_conversations_user_updated', table_name='agent_conversations')
    op.drop_index('ix_agent_conversations_user_id', table_name='agent_conversations')
    op.drop_index('ix_agent_conversations_thread_id', table_name='agent_conversations')
    op.drop_table('agent_conversations')
