from flask import Blueprint, render_template, request, redirect, url_for
from database import get_db

bp = Blueprint('settings', __name__)


@bp.route('/settings', methods=['GET', 'POST'])
def settings_page():
    conn = get_db()
    if request.method == 'POST':
        learn = max(1, int(request.form.get('daily_learn_count', 10)))
        review = max(1, int(request.form.get('daily_review_count', 20)))
        test = max(1, int(request.form.get('daily_test_count', 10)))
        show_word_first = 1 if request.form.get('show_word_first') else 0
        conn.execute("""
            UPDATE settings SET daily_learn_count = ?, daily_review_count = ?,
            daily_test_count = ?, show_word_first = ?
            WHERE id = 1
        """, (learn, review, test, show_word_first))
        conn.commit()
        conn.close()
        return redirect(url_for('settings.settings_page'))

    s = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    conn.close()
    return render_template('settings.html', settings=s)
