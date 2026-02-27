"""
database.py
-----------
Dual-mode database layer:
  • Supabase PostgreSQL  — when DATABASE_URL env var is set (cloud/production)
  • SQLite               — automatic local fallback (zero setup for development)

Set DATABASE_URL in your .env or Render dashboard:
  DATABASE_URL=postgresql://user:password@host:5432/dbname
"""

import os
import json
import sqlite3
from datetime import datetime
from utils import logger

# ── Connection mode detection ─────────────────────────────────────────────────
DATABASE_URL  = os.getenv("DATABASE_URL", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "conversions.db")
USE_POSTGRES  = bool(DATABASE_URL)

if USE_POSTGRES:
    try:
        import psycopg2
        import psycopg2.extras
        logger.info("Database: Supabase PostgreSQL")
    except ImportError:
        logger.warning("psycopg2 not installed — falling back to SQLite")
        USE_POSTGRES = False
else:
    logger.info(f"Database: SQLite at {DATABASE_PATH}")


# ── Connection helpers ─────────────────────────────────────────────────────────

def _pg_conn():
    """Return a new PostgreSQL connection."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def _sqlite_conn():
    """Return a new SQLite connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Schema ─────────────────────────────────────────────────────────────────────

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS conversions (
    id           SERIAL PRIMARY KEY,
    file_name    TEXT,
    doc_type     TEXT,
    patient_name TEXT,
    hospital     TEXT,
    valid        INTEGER DEFAULT 0,
    score        INTEGER DEFAULT 0,
    error_count  INTEGER DEFAULT 0,
    use_case     TEXT    DEFAULT 'claim',
    fhir_bundle  TEXT,
    created_at   TEXT
)
"""

_CREATE_SQL_SQLITE = _CREATE_SQL.replace("SERIAL", "INTEGER AUTOINCREMENT")


def init_db():
    """Create the database tables if they don't exist."""
    try:
        if USE_POSTGRES:
            conn = _pg_conn()
            cur  = conn.cursor()
            # PostgreSQL uses SERIAL; strip AUTOINCREMENT keyword
            cur.execute(_CREATE_SQL)
            conn.commit()
            cur.close()
            conn.close()
        else:
            conn = _sqlite_conn()
            # SQLite uses INTEGER PRIMARY KEY AUTOINCREMENT
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_name    TEXT,
                    doc_type     TEXT,
                    patient_name TEXT,
                    hospital     TEXT,
                    valid        INTEGER DEFAULT 0,
                    score        INTEGER DEFAULT 0,
                    error_count  INTEGER DEFAULT 0,
                    use_case     TEXT    DEFAULT 'claim',
                    fhir_bundle  TEXT,
                    created_at   TEXT
                )
            """)
            conn.commit()
            conn.close()
        logger.info("Database ready")
    except Exception as e:
        logger.error(f"DB init failed: {e}")


# ── Write ─────────────────────────────────────────────────────────────────────

def save_conversion(
    file_name: str,
    doc_type: str,
    clinical_data: dict,
    validation: dict,
    fhir_bundle: dict,
    use_case: str = "claim",
):
    """Persist one conversion result."""
    try:
        values = (
            file_name,
            doc_type,
            clinical_data.get("patient_name", "Unknown"),
            clinical_data.get("hospital_name", "Unknown"),
            1 if validation.get("valid") else 0,
            validation.get("readiness", {}).get("score", 0),
            validation.get("error_count", 0),
            use_case,
            json.dumps(fhir_bundle),
            datetime.utcnow().isoformat(),
        )

        if USE_POSTGRES:
            conn = _pg_conn()
            cur  = conn.cursor()
            cur.execute("""
                INSERT INTO conversions
                    (file_name, doc_type, patient_name, hospital,
                     valid, score, error_count, use_case, fhir_bundle, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, values)
            conn.commit()
            cur.close()
            conn.close()
        else:
            conn = _sqlite_conn()
            conn.execute("""
                INSERT INTO conversions
                    (file_name, doc_type, patient_name, hospital,
                     valid, score, error_count, use_case, fhir_bundle, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, values)
            conn.commit()
            conn.close()

        logger.info(f"Saved conversion: {file_name}")
    except Exception as e:
        logger.error(f"DB save failed: {e}")


# ── Read ──────────────────────────────────────────────────────────────────────

def get_all_conversions() -> list:
    """Return all conversions, newest first."""
    try:
        if USE_POSTGRES:
            conn = _pg_conn()
            cur  = conn.cursor()
            cur.execute(
                "SELECT id,file_name,doc_type,patient_name,hospital,"
                "valid,score,error_count,use_case,created_at "
                "FROM conversions ORDER BY id DESC LIMIT 100"
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [dict(r) for r in rows]
        else:
            conn = _sqlite_conn()
            rows = conn.execute(
                "SELECT id,file_name,doc_type,patient_name,hospital,"
                "valid,score,error_count,use_case,created_at "
                "FROM conversions ORDER BY id DESC LIMIT 100"
            ).fetchall()
            conn.close()
            return [
                {
                    "id":r[0],"file_name":r[1],"doc_type":r[2],
                    "patient_name":r[3],"hospital":r[4],
                    "valid":bool(r[5]),"score":r[6],"error_count":r[7],
                    "use_case":r[8],"created_at":r[9],
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"DB read failed: {e}")
        return []


def clear_all():
    """Delete all conversion records."""
    try:
        if USE_POSTGRES:
            conn = _pg_conn()
            cur  = conn.cursor()
            cur.execute("DELETE FROM conversions")
            conn.commit()
            cur.close()
            conn.close()
        else:
            conn = _sqlite_conn()
            conn.execute("DELETE FROM conversions")
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"DB clear failed: {e}")


def get_stats() -> dict:
    """Return aggregated conversion statistics."""
    try:
        if USE_POSTGRES:
            conn = _pg_conn()
            cur  = conn.cursor()
            cur.execute("SELECT COUNT(*) AS total FROM conversions")
            total = cur.fetchone()["total"]
            cur.execute("SELECT COUNT(*) AS c FROM conversions WHERE valid=1")
            valid = cur.fetchone()["c"]
            cur.execute("SELECT AVG(score) AS avg FROM conversions")
            avg   = cur.fetchone()["avg"] or 0
            cur.execute("SELECT doc_type,COUNT(*) AS c FROM conversions GROUP BY doc_type")
            doc_types = {r["doc_type"]: r["c"] for r in cur.fetchall()}
            cur.execute("SELECT use_case,COUNT(*) AS c FROM conversions GROUP BY use_case")
            use_cases = {r["use_case"]: r["c"] for r in cur.fetchall()}
            cur.close()
            conn.close()
        else:
            conn = _sqlite_conn()
            total = conn.execute("SELECT COUNT(*) FROM conversions").fetchone()[0]
            valid = conn.execute("SELECT COUNT(*) FROM conversions WHERE valid=1").fetchone()[0]
            avg   = conn.execute("SELECT AVG(score) FROM conversions").fetchone()[0] or 0
            doc_types = {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT doc_type,COUNT(*) FROM conversions GROUP BY doc_type"
                ).fetchall()
            }
            use_cases = {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT use_case,COUNT(*) FROM conversions GROUP BY use_case"
                ).fetchall()
            }
            conn.close()

        return {
            "total_conversions":       total,
            "valid_bundles":           valid,
            "invalid_bundles":         total - valid,
            "average_readiness_score": round(float(avg), 1),
            "by_doc_type":             doc_types,
            "by_use_case":             use_cases,
            "database_backend":        "PostgreSQL (Supabase)" if USE_POSTGRES else "SQLite",
        }
    except Exception as e:
        logger.error(f"DB stats failed: {e}")
        return {"total_conversions": 0, "error": str(e)}
