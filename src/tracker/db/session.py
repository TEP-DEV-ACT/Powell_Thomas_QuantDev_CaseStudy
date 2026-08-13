"""Thin psycopg connection helper. No ORM — every table has a natural key
and every access pattern is a handful of SQL statements, so an ORM would add
indirection without buying anything (see PLAN.md "Deliberate cuts").
"""
import psycopg
from psycopg.rows import dict_row

from tracker.config import DATABASE_URL


def get_connection():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def apply_schema(conn=None):
    schema_path = __file__.replace("session.py", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        ddl = f.read()
    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
    finally:
        if owns_conn:
            conn.close()
