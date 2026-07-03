"""Run this once on the VPS to export the SniffHQDemo schema to schema.sql"""
import sqlite3

db_path = r'C:\SniffHQDemo\instance\sniffhq.db'
out_path = r'C:\SniffHQPlatform\schema.sql'

conn = sqlite3.connect(db_path)
stmts = [
    row[0] for row in conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type IN ('table','index') AND sql IS NOT NULL "
        "ORDER BY type DESC, name"
    )
]
conn.close()

with open(out_path, 'w', encoding='utf-8') as f:
    f.write(';\n'.join(stmts) + ';\n')

print(f'Exported {len(stmts)} statements to {out_path}')
