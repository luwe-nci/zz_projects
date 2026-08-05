from datetime import date, timedelta
from database import get_db


def get_settings():
    conn = get_db()
    s = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    conn.close()
    return s


def get_active_learn_group():
    """Return the current incomplete learn group, or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM learn_group WHERE completed_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row


def get_or_create_learn_group(size):
    """Return active group; create a new one filled with `size` new words if none open."""
    conn = get_db()
    group = conn.execute(
        "SELECT * FROM learn_group WHERE completed_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if group is None:
        today = date.today().isoformat()
        cur = conn.execute(
            "INSERT INTO learn_group (started_at) VALUES (?)", (today,)
        )
        group_id = cur.lastrowid
        # Pick next `size` new words not already in any group
        new_words = conn.execute("""
            SELECT w.id FROM words w
            LEFT JOIN user_word_progress p ON p.word_id = w.id
            WHERE (p.id IS NULL OR p.status = 'new')
              AND w.id NOT IN (SELECT word_id FROM learn_group_word)
            ORDER BY w.created_at
            LIMIT ?
        """, (size,)).fetchall()
        for row in new_words:
            conn.execute(
                "INSERT INTO learn_group_word (group_id, word_id) VALUES (?, ?)",
                (group_id, row['id'])
            )
        conn.commit()
        group = conn.execute(
            "SELECT * FROM learn_group WHERE id = ?", (group_id,)
        ).fetchone()

    conn.close()
    return group


def complete_learn_group(group_id):
    """Mark a learn group as completed."""
    conn = get_db()
    today = date.today().isoformat()
    conn.execute(
        "UPDATE learn_group SET completed_at = ? WHERE id = ?", (today, group_id)
    )
    conn.commit()
    conn.close()


def create_next_learn_group(size):
    """Complete current open group (if any) and create a new one."""
    conn = get_db()
    today = date.today().isoformat()
    # Close any open groups
    conn.execute(
        "UPDATE learn_group SET completed_at = ? WHERE completed_at IS NULL", (today,)
    )
    conn.commit()
    conn.close()
    return get_or_create_learn_group(size)


def get_learn_group_word_ids(group_id):
    """Return list of word_ids in this group."""
    conn = get_db()
    rows = conn.execute(
        "SELECT word_id FROM learn_group_word WHERE group_id = ?", (group_id,)
    ).fetchall()
    conn.close()
    return [r['word_id'] for r in rows]


def get_all_learn_groups():
    """Return all learn groups newest-first with word count."""
    conn = get_db()
    rows = conn.execute("""
        SELECT lg.id, lg.started_at, lg.completed_at,
               COUNT(lgw.word_id) as word_count
        FROM learn_group lg
        LEFT JOIN learn_group_word lgw ON lgw.group_id = lg.id
        GROUP BY lg.id
        ORDER BY lg.id DESC
    """).fetchall()
    conn.close()
    return rows


def get_due_words(mode, limit):
    """Return list of word_ids due for the given mode."""
    conn = get_db()
    today = date.today().isoformat()

    if mode == 'learn':
        # Pull from the active learn group only
        group = get_active_learn_group()
        if group is None:
            conn.close()
            return []
        rows = conn.execute("""
            SELECT lgw.word_id as id FROM learn_group_word lgw
            LEFT JOIN user_word_progress p ON p.word_id = lgw.word_id
            WHERE lgw.group_id = ?
              AND (p.id IS NULL OR p.status = 'new')
            ORDER BY lgw.word_id
            LIMIT ?
        """, (group['id'], limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT w.id FROM words w
            JOIN user_word_progress p ON p.word_id = w.id
            WHERE p.status IN ('learning', 'review')
              AND p.next_due_at <= ?
            ORDER BY p.next_due_at
            LIMIT ?
        """, (today, limit)).fetchall()

    conn.close()
    return [r['id'] for r in rows]


def ensure_progress(word_id):
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM user_word_progress WHERE word_id = ?", (word_id,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO user_word_progress (word_id) VALUES (?)", (word_id,)
        )
        conn.commit()
    conn.close()


def update_progress(word_id, rating):
    ensure_progress(word_id)
    conn = get_db()
    p = conn.execute(
        "SELECT * FROM user_word_progress WHERE word_id = ?", (word_id,)
    ).fetchone()

    interval = p['interval']
    ease = p['ease_factor']
    consecutive = p['consecutive_correct']
    status = p['status']

    if rating == 'easy':
        ease = max(1.3, ease + 0.1)
        consecutive += 1
        if status in ('new', 'learning'):
            # Known well enough — move to review, schedule a week out
            interval = 7
            status = 'review'
        elif status == 'review':
            interval = max(1, round(interval * ease))
            if consecutive >= 3:
                status = 'mastered'
        else:  # mastered — keep extending
            interval = max(1, round(interval * ease))
    elif rating == 'hard':
        ease = max(1.3, ease - 0.15)
        consecutive += 1
        if status == 'new':
            status = 'learning'
            interval = 3
        else:
            interval = max(1, round(interval * 1.2))
    else:  # missed
        ease = max(1.3, ease - 0.2)
        interval = 1
        consecutive = 0
        status = 'learning'

    next_due = (date.today() + timedelta(days=interval)).isoformat()
    today = date.today().isoformat()

    conn.execute("""
        UPDATE user_word_progress
        SET interval = ?, ease_factor = ?, consecutive_correct = ?,
            last_reviewed_at = ?, next_due_at = ?, status = ?
        WHERE word_id = ?
    """, (interval, ease, consecutive, today, next_due, status, word_id))
    conn.commit()
    conn.close()


def get_or_create_today_session():
    conn = get_db()
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT * FROM daily_session WHERE date = ?", (today,)
    ).fetchone()

    if not row:
        s = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        conn.execute("""
            INSERT INTO daily_session (date, learn_target, review_target, test_target)
            VALUES (?, ?, ?, ?)
        """, (today, s['daily_learn_count'], s['daily_review_count'], s['daily_test_count']))
        conn.commit()
        row = conn.execute(
            "SELECT * FROM daily_session WHERE date = ?", (today,)
        ).fetchone()

    conn.close()
    return row


def increment_session_count(mode, word_id=None):
    today = date.today().isoformat()
    col = f"{mode}_done"
    conn = get_db()
    conn.execute(
        f"UPDATE daily_session SET {col} = {col} + 1 WHERE date = ?", (today,)
    )
    if word_id is not None:
        conn.execute(
            "INSERT INTO daily_word_log (date, word_id, mode) VALUES (?, ?, ?)",
            (today, word_id, mode)
        )
    conn.commit()
    conn.close()


def get_done_word_ids(mode):
    """Return set of word_ids already done today for the given mode."""
    today = date.today().isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT word_id FROM daily_word_log WHERE date = ? AND mode = ?", (today, mode)
    ).fetchall()
    conn.close()
    return {r['word_id'] for r in rows}


def get_streak():
    conn = get_db()
    rows = conn.execute("""
        SELECT date FROM daily_session
        WHERE learn_done >= learn_target
          AND review_done >= review_target
          AND test_done >= test_target
        ORDER BY date DESC
    """).fetchall()
    conn.close()

    streak = 0
    check = date.today()
    dates = {r['date'] for r in rows}
    while check.isoformat() in dates:
        streak += 1
        check -= timedelta(days=1)
    return streak
