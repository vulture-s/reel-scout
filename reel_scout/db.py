from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import config

SCHEMA_VERSION = 6

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS videos (
    id              TEXT PRIMARY KEY,
    platform        TEXT NOT NULL,
    platform_id     TEXT NOT NULL,
    url             TEXT NOT NULL,
    title           TEXT,
    uploader        TEXT,
    duration_sec    REAL,
    upload_date     TEXT,
    file_path       TEXT,
    file_size_bytes INTEGER,
    status          TEXT DEFAULT 'downloaded',
    error_message   TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transcripts (
    video_id        TEXT PRIMARY KEY REFERENCES videos(id),
    language        TEXT,
    text_full       TEXT,
    segments_json   TEXT,
    whisper_model   TEXT,
    duration_sec    REAL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS keyframes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        TEXT REFERENCES videos(id),
    frame_index     INTEGER,
    timestamp_sec   REAL,
    file_path       TEXT,
    strategy        TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vision_descriptions (
    keyframe_id     INTEGER PRIMARY KEY REFERENCES keyframes(id),
    description     TEXT,
    objects_json    TEXT,
    text_in_frame   TEXT,
    vlm_backend     TEXT,
    vlm_model       TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS analyses (
    video_id        TEXT PRIMARY KEY REFERENCES videos(id),
    summary         TEXT,
    topics_json     TEXT,
    hooks_json      TEXT,
    style_json      TEXT,
    engagement_signals_json TEXT,
    full_json       TEXT,
    -- Normalized low-cardinality tags (derived from full_json) for filtering/stats.
    content_type    TEXT,
    opening_type    TEXT,
    cta_type        TEXT,
    style_format    TEXT,
    style_pacing    TEXT,
    emotion         TEXT,
    content_structure TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS batches (
    id              TEXT PRIMARY KEY,
    source          TEXT,
    total_urls      INTEGER,
    completed       INTEGER DEFAULT 0,
    failed          INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'running',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS batch_items (
    batch_id        TEXT REFERENCES batches(id),
    url             TEXT,
    video_id        TEXT REFERENCES videos(id),
    status          TEXT DEFAULT 'pending',
    error_message   TEXT,
    PRIMARY KEY (batch_id, url)
);

CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_platform ON videos(platform);
CREATE INDEX IF NOT EXISTS idx_batch_items_status ON batch_items(status);
"""
# analyses tag indexes are created after migrations (see init_db) so they don't
# run against a pre-v5 DB whose analyses table lacks these columns yet.


# Low-cardinality analysis tags that are mirrored from full_json into indexed
# columns on `analyses` so they can be filtered/aggregated without JSON scans.
# (column name -> extractor) — full_json stays the source of truth.
def _extract_tag_columns(data: Dict[str, Any]) -> Dict[str, Any]:
    hook = data.get("hook") or {}
    style = data.get("style") or {}
    eng = data.get("engagement_signals") or {}
    return {
        "content_type": data.get("content_type"),
        "opening_type": hook.get("opening_type"),
        "cta_type": hook.get("cta_type"),
        "style_format": style.get("format"),
        "style_pacing": style.get("pacing"),
        "emotion": eng.get("emotion"),
        "content_structure": data.get("content_structure"),
    }


def _video_id(platform: str, platform_id: str) -> str:
    raw = f"{platform}:{platform_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_connection() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Add audio_events table (schema v1 -> v2)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS audio_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id        TEXT REFERENCES videos(id),
            event_type      TEXT NOT NULL,
            label           TEXT,
            start_sec       REAL,
            end_sec         REAL,
            confidence      REAL,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_audio_events_video ON audio_events(video_id);
    """)
    conn.execute(
        "UPDATE schema_version SET version = 2 WHERE version = 1"
    )
    conn.commit()


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Add scores table (schema v2 -> v3)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scores (
            video_id        TEXT PRIMARY KEY REFERENCES videos(id),
            hook_strength   REAL,
            visual_storytelling REAL,
            pacing          REAL,
            structure       REAL,
            overall         REAL,
            reasoning       TEXT,
            model_used      TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.execute(
        "UPDATE schema_version SET version = 3 WHERE version = 2"
    )
    conn.commit()


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Rebuild scores table with Direction-A dimensions (schema v3 -> v4).
    Safe DROP: scores is regenerated by `reel-scout score`, not source data."""
    conn.executescript("""
        DROP TABLE IF EXISTS scores;
        CREATE TABLE scores (
            video_id        TEXT PRIMARY KEY REFERENCES videos(id),
            hook_strength   REAL,
            visual_storytelling REAL,
            pacing          REAL,
            structure       REAL,
            overall         REAL,
            reasoning       TEXT,
            model_used      TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.execute(
        "UPDATE schema_version SET version = 4 WHERE version = 3"
    )
    conn.commit()


def _migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    """Normalize low-cardinality analysis tags into indexed columns for
    filtering/stats (schema v4 -> v5), and backfill them from the existing
    full_json blobs. First migration in this repo to ALTER an existing
    data-bearing table (prior ones only added/rebuilt whole tables)."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(analyses)")}
    for name in ("content_type", "opening_type", "cta_type",
                 "style_format", "style_pacing", "emotion"):
        if name not in existing:
            conn.execute("ALTER TABLE analyses ADD COLUMN %s TEXT" % name)
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_analyses_content_type ON analyses(content_type);
        CREATE INDEX IF NOT EXISTS idx_analyses_style_format ON analyses(style_format);
        CREATE INDEX IF NOT EXISTS idx_analyses_opening_type ON analyses(opening_type);
        CREATE INDEX IF NOT EXISTS idx_analyses_cta_type ON analyses(cta_type);
    """)
    # Backfill from full_json (the source of truth) for rows analyzed pre-v5.
    for video_id, full_json in conn.execute(
        "SELECT video_id, full_json FROM analyses"
    ).fetchall():
        if not full_json:
            continue
        try:
            data = json.loads(full_json)
        except (ValueError, TypeError):
            continue
        tags = _extract_tag_columns(data)
        conn.execute(
            """UPDATE analyses SET content_type=?, opening_type=?, cta_type=?,
               style_format=?, style_pacing=?, emotion=? WHERE video_id=?""",
            (tags["content_type"], tags["opening_type"], tags["cta_type"],
             tags["style_format"], tags["style_pacing"], tags["emotion"], video_id),
        )
    conn.execute("UPDATE schema_version SET version = 5 WHERE version = 4")
    conn.commit()


def _migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    """Add the content_structure classification column + backfill from full_json
    (schema v5 -> v6). Rows analyzed before the merger emitted content_structure
    simply stay NULL — nothing to backfill for them."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(analyses)")}
    if "content_structure" not in existing:
        conn.execute("ALTER TABLE analyses ADD COLUMN content_structure TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_analyses_content_structure "
        "ON analyses(content_structure)"
    )
    for video_id, full_json in conn.execute(
        "SELECT video_id, full_json FROM analyses"
    ).fetchall():
        if not full_json:
            continue
        try:
            data = json.loads(full_json)
        except (ValueError, TypeError):
            continue
        cs = data.get("content_structure")
        if cs is not None:
            conn.execute(
                "UPDATE analyses SET content_structure=? WHERE video_id=?",
                (cs, video_id),
            )
    conn.execute("UPDATE schema_version SET version = 6 WHERE version = 5")
    conn.commit()


def init_db(conn: Optional[sqlite3.Connection] = None) -> sqlite3.Connection:
    if conn is None:
        conn = get_connection()
    conn.executescript(_SCHEMA_SQL)
    # Set schema version if not exists
    cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
    row = cur.fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
    else:
        current_ver = row[0] if row else 0
        if current_ver < 2:
            _migrate_v1_to_v2(conn)
            current_ver = 2
        if current_ver < 3:
            _migrate_v2_to_v3(conn)
            current_ver = 3
        if current_ver < 4:
            _migrate_v3_to_v4(conn)
            current_ver = 4
        if current_ver < 5:
            _migrate_v4_to_v5(conn)
            current_ver = 5
        if current_ver < 6:
            _migrate_v5_to_v6(conn)
    # Always ensure audio_events table exists for fresh installs
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS audio_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id        TEXT REFERENCES videos(id),
            event_type      TEXT NOT NULL,
            label           TEXT,
            start_sec       REAL,
            end_sec         REAL,
            confidence      REAL,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_audio_events_video ON audio_events(video_id);

        CREATE TABLE IF NOT EXISTS scores (
            video_id        TEXT PRIMARY KEY REFERENCES videos(id),
            hook_strength   REAL,
            visual_storytelling REAL,
            pacing          REAL,
            structure       REAL,
            overall         REAL,
            reasoning       TEXT,
            model_used      TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_analyses_content_type ON analyses(content_type);
        CREATE INDEX IF NOT EXISTS idx_analyses_style_format ON analyses(style_format);
        CREATE INDEX IF NOT EXISTS idx_analyses_opening_type ON analyses(opening_type);
        CREATE INDEX IF NOT EXISTS idx_analyses_cta_type ON analyses(cta_type);
        CREATE INDEX IF NOT EXISTS idx_analyses_content_structure ON analyses(content_structure);
    """)
    conn.commit()
    return conn


# --- Video CRUD ---

def get_video(conn: sqlite3.Connection, video_id: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
    return cur.fetchone()


def get_video_by_url(conn: sqlite3.Connection, url: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM videos WHERE url = ?", (url,))
    return cur.fetchone()


def upsert_video(
    conn: sqlite3.Connection,
    platform: str,
    platform_id: str,
    url: str,
    title: Optional[str] = None,
    uploader: Optional[str] = None,
    duration_sec: Optional[float] = None,
    upload_date: Optional[str] = None,
    file_path: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
) -> str:
    vid = _video_id(platform, platform_id)
    existing = get_video(conn, vid)
    if existing:
        conn.execute(
            """UPDATE videos SET title=COALESCE(?,title), uploader=COALESCE(?,uploader),
               duration_sec=COALESCE(?,duration_sec), upload_date=COALESCE(?,upload_date),
               file_path=COALESCE(?,file_path), file_size_bytes=COALESCE(?,file_size_bytes),
               updated_at=datetime('now')
               WHERE id=?""",
            (title, uploader, duration_sec, upload_date, file_path, file_size_bytes, vid),
        )
    else:
        conn.execute(
            """INSERT INTO videos (id, platform, platform_id, url, title, uploader,
               duration_sec, upload_date, file_path, file_size_bytes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (vid, platform, platform_id, url, title, uploader,
             duration_sec, upload_date, file_path, file_size_bytes),
        )
    conn.commit()
    return vid


def update_video_status(
    conn: sqlite3.Connection, video_id: str, status: str,
    error: Optional[str] = None,
) -> None:
    conn.execute(
        "UPDATE videos SET status=?, error_message=?, updated_at=datetime('now') WHERE id=?",
        (status, error, video_id),
    )
    conn.commit()


def list_videos(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    platform: Optional[str] = None,
    limit: int = 50,
) -> List[sqlite3.Row]:
    query = "SELECT * FROM videos WHERE 1=1"
    params = []  # type: List[Any]
    if status:
        query += " AND status = ?"
        params.append(status)
    if platform:
        query += " AND platform = ?"
        params.append(platform)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return conn.execute(query, params).fetchall()


# --- Transcript CRUD ---

def save_transcript(
    conn: sqlite3.Connection,
    video_id: str,
    language: str,
    text_full: str,
    segments_json: str,
    whisper_model: str,
    duration_sec: float,
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO transcripts
           (video_id, language, text_full, segments_json, whisper_model, duration_sec)
           VALUES (?,?,?,?,?,?)""",
        (video_id, language, text_full, segments_json, whisper_model, duration_sec),
    )
    update_video_status(conn, video_id, "transcribed")
    conn.commit()


def get_transcript(conn: sqlite3.Connection, video_id: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM transcripts WHERE video_id = ?", (video_id,))
    return cur.fetchone()


# --- Keyframe CRUD ---

def save_keyframes(
    conn: sqlite3.Connection,
    video_id: str,
    keyframes: List[Dict[str, Any]],
) -> List[int]:
    ids = []
    for kf in keyframes:
        cur = conn.execute(
            """INSERT INTO keyframes (video_id, frame_index, timestamp_sec, file_path, strategy)
               VALUES (?,?,?,?,?)""",
            (video_id, kf["frame_index"], kf["timestamp_sec"],
             kf["file_path"], kf["strategy"]),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def get_keyframes(conn: sqlite3.Connection, video_id: str) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM keyframes WHERE video_id = ? ORDER BY timestamp_sec",
        (video_id,),
    ).fetchall()


def get_described_keyframe_ids(conn: sqlite3.Connection, video_id: str) -> set:
    """Keyframe ids for this video that already have a vision description.
    Used to backfill only the missing frames on re-run."""
    rows = conn.execute(
        """SELECT vd.keyframe_id FROM vision_descriptions vd
           JOIN keyframes k ON k.id = vd.keyframe_id
           WHERE k.video_id = ?""",
        (video_id,),
    ).fetchall()
    return {r[0] for r in rows}


# --- Vision CRUD ---

def save_vision_description(
    conn: sqlite3.Connection,
    keyframe_id: int,
    description: str,
    objects_json: str,
    text_in_frame: str,
    vlm_backend: str,
    vlm_model: str,
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO vision_descriptions
           (keyframe_id, description, objects_json, text_in_frame, vlm_backend, vlm_model)
           VALUES (?,?,?,?,?,?)""",
        (keyframe_id, description, objects_json, text_in_frame, vlm_backend, vlm_model),
    )
    conn.commit()


# --- Audio Events CRUD ---

def save_audio_events(
    conn: sqlite3.Connection,
    video_id: str,
    events: List[Dict[str, Any]],
) -> None:
    """Bulk insert audio events for a video."""
    for ev in events:
        conn.execute(
            """INSERT INTO audio_events
               (video_id, event_type, label, start_sec, end_sec, confidence)
               VALUES (?,?,?,?,?,?)""",
            (
                video_id,
                ev["event_type"],
                ev.get("label", ""),
                ev.get("start_sec"),
                ev.get("end_sec"),
                ev.get("confidence"),
            ),
        )
    conn.commit()


def get_audio_events(
    conn: sqlite3.Connection, video_id: str
) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM audio_events WHERE video_id = ? ORDER BY start_sec",
        (video_id,),
    ).fetchall()


# --- Score CRUD ---

def save_score(
    conn: sqlite3.Connection,
    video_id: str,
    score: Any,
) -> None:
    """Insert or replace a video score. Accepts a VideoScore dataclass."""
    conn.execute(
        """INSERT OR REPLACE INTO scores
           (video_id, hook_strength, visual_storytelling, pacing,
            structure, overall, reasoning, model_used)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            video_id,
            score.hook_strength,
            score.visual_storytelling,
            score.pacing,
            score.structure,
            score.overall,
            score.reasoning,
            score.model_used,
        ),
    )
    conn.commit()


def get_score(conn: sqlite3.Connection, video_id: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM scores WHERE video_id = ?", (video_id,))
    return cur.fetchone()


# --- Analysis CRUD ---

def save_analysis(
    conn: sqlite3.Connection,
    video_id: str,
    summary: str,
    topics_json: str,
    hooks_json: str,
    style_json: str,
    engagement_signals_json: str,
    full_json: str,
) -> None:
    # Derive the normalized tag columns from full_json (the source of truth) so
    # callers stay unchanged and the columns can never drift from the blob.
    try:
        data = json.loads(full_json) if full_json else {}
    except (ValueError, TypeError):
        data = {}
    tags = _extract_tag_columns(data)
    conn.execute(
        """INSERT OR REPLACE INTO analyses
           (video_id, summary, topics_json, hooks_json, style_json,
            engagement_signals_json, full_json,
            content_type, opening_type, cta_type, style_format, style_pacing,
            emotion, content_structure)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (video_id, summary, topics_json, hooks_json, style_json,
         engagement_signals_json, full_json,
         tags["content_type"], tags["opening_type"], tags["cta_type"],
         tags["style_format"], tags["style_pacing"], tags["emotion"],
         tags["content_structure"]),
    )
    update_video_status(conn, video_id, "analyzed")
    conn.commit()


def get_analysis(conn: sqlite3.Connection, video_id: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM analyses WHERE video_id = ?", (video_id,))
    return cur.fetchone()


# --- Batch CRUD ---

def create_batch(
    conn: sqlite3.Connection, urls: List[str], source: str = "cli",
) -> str:
    batch_id = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO batches (id, source, total_urls) VALUES (?,?,?)",
        (batch_id, source, len(urls)),
    )
    for url in urls:
        conn.execute(
            "INSERT INTO batch_items (batch_id, url) VALUES (?,?)",
            (batch_id, url),
        )
    conn.commit()
    return batch_id


def get_pending_batch_items(
    conn: sqlite3.Connection, batch_id: str,
) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM batch_items WHERE batch_id = ? AND status = 'pending'",
        (batch_id,),
    ).fetchall()


def get_latest_interrupted_batch(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM batches WHERE status = 'interrupted' ORDER BY updated_at DESC LIMIT 1"
    )
    return cur.fetchone()


def update_batch_item(
    conn: sqlite3.Connection,
    batch_id: str,
    url: str,
    status: str,
    video_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    conn.execute(
        """UPDATE batch_items SET status=?, video_id=?, error_message=?
           WHERE batch_id=? AND url=?""",
        (status, video_id, error, batch_id, url),
    )
    # Update batch counters
    if status == "done":
        conn.execute(
            "UPDATE batches SET completed=completed+1, updated_at=datetime('now') WHERE id=?",
            (batch_id,),
        )
    elif status == "error":
        conn.execute(
            "UPDATE batches SET failed=failed+1, updated_at=datetime('now') WHERE id=?",
            (batch_id,),
        )
    conn.commit()


def mark_batch_interrupted(conn: sqlite3.Connection, batch_id: str) -> None:
    conn.execute(
        "UPDATE batches SET status='interrupted', updated_at=datetime('now') WHERE id=?",
        (batch_id,),
    )
    conn.commit()


def mark_batch_completed(conn: sqlite3.Connection, batch_id: str) -> None:
    conn.execute(
        "UPDATE batches SET status='completed', updated_at=datetime('now') WHERE id=?",
        (batch_id,),
    )
    conn.commit()


# --- Stats ---

def db_stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    stats = {}
    for table in ["videos", "transcripts", "keyframes", "vision_descriptions", "analyses", "audio_events", "scores", "batches"]:
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - table names are hardcoded
        stats[table] = cur.fetchone()[0]

    # Status breakdown
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM videos GROUP BY status"
    ).fetchall()
    stats["videos_by_status"] = {r["status"]: r["cnt"] for r in rows}

    # Platform breakdown
    rows = conn.execute(
        "SELECT platform, COUNT(*) as cnt FROM videos GROUP BY platform"
    ).fetchall()
    stats["videos_by_platform"] = {r["platform"]: r["cnt"] for r in rows}

    return stats
