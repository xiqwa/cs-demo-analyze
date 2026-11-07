"""All migrations must use Database's externally managed SQLite transaction."""
from alembic import context

connection = context.config.attributes.get('connection')
if connection is None:
    raise RuntimeError('use_python_m_roundmind_manage')
context.configure(connection=connection, transactional_ddl=True, target_metadata=None)
with context.begin_transaction():
    context.run_migrations()
