from flask import Blueprint, render_template
from database import get_db

bp = Blueprint('stats', __name__)


@bp.route('/stats')
def stats_page():
    conn = get_db()

    status_counts = dict(conn.execute("""
        SELECT status, COUNT(*) FROM user_word_progress GROUP BY status
    """).fetchall())

    total_words = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    unstarted = total_words - sum(status_counts.values())

    daily_counts = conn.execute("""
        SELECT date, learn_done + review_done + test_done AS total
        FROM daily_session
        ORDER BY date DESC
        LIMIT 30
    """).fetchall()

    mastery_pct = 0
    if total_words > 0:
        mastered = status_counts.get('mastered', 0)
        mastery_pct = round(mastered / total_words * 100)

    conn.close()
    return render_template('stats.html',
                           status_counts=status_counts,
                           total_words=total_words,
                           unstarted=unstarted,
                           daily_counts=daily_counts,
                           mastery_pct=mastery_pct)
