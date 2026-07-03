"""
Run this from C:\SniffHQDemo using its venv to generate schema.sql:

    cd C:\SniffHQDemo
    venv\Scripts\python.exe C:\SniffHQPlatform\gen_schema.py
"""
import sys
import os
import sqlite3
import tempfile

sys.path.insert(0, '.')
os.environ.setdefault('SECRET_KEY', 'schema-gen-tmp')

tmp_db = os.path.join(tempfile.gettempdir(), 'sniffhq_schema_gen.db')
os.environ['DATABASE_URL'] = f'sqlite:///{tmp_db}'

# Remove any previous temp DB
if os.path.exists(tmp_db):
    os.remove(tmp_db)

print(f'Generating schema into temp DB: {tmp_db}')

from app import create_app, db
app = create_app()
with app.app_context():
    db.create_all()

conn = sqlite3.connect(tmp_db)
stmts = [
    row[0] for row in conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type IN ('table','index') AND sql IS NOT NULL "
        "ORDER BY type DESC, name"
    )
]
conn.close()
os.remove(tmp_db)

out = r'C:\SniffHQPlatform\schema.sql'
with open(out, 'w', encoding='utf-8') as f:
    f.write(';\n'.join(stmts) + ';\n')

print(f'Exported {len(stmts)} statements to {out}')
tables = [s.split('(')[0].replace('CREATE TABLE ', '').strip() for s in stmts if 'CREATE TABLE' in s]
print(f'Tables ({len(tables)}): {tables}')
