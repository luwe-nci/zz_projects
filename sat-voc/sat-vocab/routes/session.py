import requests as http_requests
from flask import Blueprint, render_template, redirect, url_for, session as flask_session, request, jsonify
from scheduler import (get_due_words, get_or_create_today_session,
                       update_progress, increment_session_count, ensure_progress,
                       get_done_word_ids, get_or_create_learn_group,
                       create_next_learn_group, complete_learn_group,
                       get_active_learn_group, get_learn_group_word_ids,
                       get_all_learn_groups)
from models.word import get_by_id
from database import get_db

bp = Blueprint('session', __name__)


def build_queue():
    today = get_or_create_today_session()
    settings = get_db().execute("SELECT * FROM settings WHERE id = 1").fetchone()
    learn_size = settings['daily_learn_count'] if settings else 10

    # Ensure an active learn group exists
    get_or_create_learn_group(learn_size)

    learn_remaining = max(0, today['learn_target'] - today['learn_done'])
    review_remaining = max(0, today['review_target'] - today['review_done'])
    test_remaining = max(0, today['test_target'] - today['test_done'])

    learn_ids = [{'id': i, 'mode': 'learn'} for i in get_due_words('learn', learn_remaining)]
    review_ids = [{'id': i, 'mode': 'review'} for i in get_due_words('review', review_remaining)]
    test_ids = [{'id': i, 'mode': 'test'} for i in get_due_words('review', test_remaining)]

    return learn_ids + review_ids + test_ids


@bp.route('/session/start')
def start():
    queue = build_queue()
    flask_session['queue'] = queue
    flask_session['queue_index'] = 0
    if not queue:
        return redirect(url_for('session.done'))
    return redirect(url_for('session.card'))


@bp.route('/session/card')
def card():
    queue = flask_session.get('queue', [])
    idx = flask_session.get('queue_index', 0)

    if idx >= len(queue):
        return redirect(url_for('session.done'))

    item = queue[idx]
    word = get_by_id(item['id'])
    ensure_progress(item['id'])
    mode = item['mode']
    total = len(queue)

    settings = get_db().execute("SELECT * FROM settings WHERE id = 1").fetchone()
    show_word_first = settings['show_word_first'] if settings['show_word_first'] is not None else 1

    import json as _json
    raw = word['examples'] or ''
    try:
        examples_list = _json.loads(raw) if raw else []
    except Exception:
        examples_list = []
    if not examples_list and word['note']:
        examples_list = [word['note']]
    examples_json = _json.dumps(examples_list)

    return render_template('session.html',
                           word=word,
                           examples_json=examples_json,
                           mode=mode,
                           current=idx + 1,
                           total=total,
                           show_word_first=show_word_first)


@bp.route('/session/rate', methods=['POST'])
def rate():
    queue = flask_session.get('queue', [])
    idx = flask_session.get('queue_index', 0)

    if idx < len(queue):
        item = queue[idx]
        rating = request.form.get('rating', 'missed')
        update_progress(item['id'], rating)
        mode = item['mode'] if item['mode'] != 'test' else 'test'
        increment_session_count(mode, word_id=item['id'])

    flask_session['queue_index'] = idx + 1
    return redirect(url_for('session.card'))


@bp.route('/session/queue/<mode>')
def queue_list(mode):
    """Show all words for today's mode — learn redirects to active group."""
    if mode not in ('learn', 'review', 'test'):
        return redirect(url_for('home.index'))

    if mode == 'learn':
        settings = get_db().execute("SELECT * FROM settings WHERE id = 1").fetchone()
        learn_size = settings['daily_learn_count'] if settings else 10
        group = get_or_create_learn_group(learn_size)
        return redirect(url_for('session.group_detail', group_id=group['id'], ref='home'))

    today = get_or_create_today_session()
    target = today['review_target'] if mode == 'review' else today['test_target']
    done_ids = get_done_word_ids(mode)

    all_ids = list(done_ids) + [i for i in get_due_words('review', target) if i not in done_ids]
    all_ids = all_ids[:target]

    conn = get_db()
    words = []
    for wid in all_ids:
        row = conn.execute("""
            SELECT w.id, w.word, w.definition, w.note, w.pos,
                   p.status, p.next_due_at, p.interval
            FROM words w
            LEFT JOIN user_word_progress p ON p.word_id = w.id
            WHERE w.id = ?
        """, (wid,)).fetchone()
        if row:
            words.append({'word': row, 'done': wid in done_ids})
    conn.close()

    words.sort(key=lambda x: x['done'])
    return render_template('queue_list.html', words=words, mode=mode,
                           ref='home', session=today, target=target, done_count=len(done_ids))


@bp.route('/session/group/<int:group_id>')
def group_detail(group_id):
    """Show words in a specific learn group with done/remaining checkmarks."""
    ref = request.args.get('ref', 'history')  # 'history' or 'home'
    conn = get_db()
    group = conn.execute("SELECT * FROM learn_group WHERE id = ?", (group_id,)).fetchone()
    if not group:
        conn.close()
        return redirect(url_for('session.learn_history'))

    word_ids = get_learn_group_word_ids(group_id)
    is_active = group['completed_at'] is None
    done_ids = get_done_word_ids('learn') if is_active else set()

    words = []
    for wid in word_ids:
        row = conn.execute("""
            SELECT w.id, w.word, w.definition, w.note, w.pos, p.status
            FROM words w
            LEFT JOIN user_word_progress p ON p.word_id = w.id
            WHERE w.id = ?
        """, (wid,)).fetchone()
        if row:
            if is_active:
                done = wid in done_ids
            else:
                done = row['status'] not in (None, 'new')
            words.append({'word': row, 'done': done})
    conn.close()

    words.sort(key=lambda x: x['done'])

    label = _group_label(group_id)
    return render_template('queue_list.html', words=words, mode='learn',
                           group=group, group_label=label,
                           is_active=is_active, ref=ref,
                           target=len(word_ids),
                           done_count=sum(1 for w in words if w['done']),
                           session=get_or_create_today_session())


@bp.route('/session/check/<mode>/<int:word_id>', methods=['POST'])
def manual_check(mode, word_id):
    """Manually mark a word done from the list (rates as hard, logs it)."""
    from scheduler import update_progress, ensure_progress
    ensure_progress(word_id)
    update_progress(word_id, 'hard')
    increment_session_count(mode, word_id=word_id)
    # Return to same page — use Referer or fall back
    return redirect(request.referrer or url_for('home.index'))


@bp.route('/session/skip')
def skip():
    """Advance to the next card without recording a rating."""
    idx = flask_session.get('queue_index', 0)
    flask_session['queue_index'] = idx + 1
    return redirect(url_for('session.card'))


@bp.route('/session/done')
def done():
    today = get_or_create_today_session()
    settings = get_db().execute("SELECT * FROM settings WHERE id = 1").fetchone()
    learn_size = settings['daily_learn_count'] if settings else 10

    # Check if the current learn group is fully learned (all words progressed past 'new')
    group = get_active_learn_group()
    group_finished = False
    if group:
        remaining = get_due_words('learn', 1)
        group_finished = len(remaining) == 0

    return render_template('session_done.html', session=today,
                           group=group, group_finished=group_finished)


@bp.route('/session/next-group', methods=['POST'])
def next_group():
    """Complete the current learn group and create the next one."""
    settings = get_db().execute("SELECT * FROM settings WHERE id = 1").fetchone()
    learn_size = settings['daily_learn_count'] if settings else 10
    create_next_learn_group(learn_size)
    return redirect(url_for('session.learn_history'))


def _group_label(group_id):
    """Return a label like '2026-08-04' or '2026-08-04a'/'2026-08-04b' when multiple on same day."""
    conn = get_db()
    g = conn.execute("SELECT started_at FROM learn_group WHERE id = ?", (group_id,)).fetchone()
    if not g:
        conn.close()
        return str(group_id)
    date_str = g['started_at']
    total = conn.execute(
        "SELECT COUNT(*) FROM learn_group WHERE started_at = ?", (date_str,)
    ).fetchone()[0]
    if total == 1:
        conn.close()
        return date_str
    position = conn.execute(
        "SELECT COUNT(*) FROM learn_group WHERE started_at = ? AND id <= ?",
        (date_str, group_id)
    ).fetchone()[0] - 1  # 0-based position
    conn.close()
    return date_str + chr(ord('a') + position)


@bp.route('/session/group/<int:group_id>/reset', methods=['POST'])
def reset_group(group_id):
    """Delete a learn group and reset all its words back to 'new'."""
    conn = get_db()
    word_ids = [r['word_id'] for r in conn.execute(
        "SELECT word_id FROM learn_group_word WHERE group_id = ?", (group_id,)
    ).fetchall()]
    for wid in word_ids:
        conn.execute("""
            UPDATE user_word_progress
            SET status = 'new', interval = 1, ease_factor = 2.5,
                consecutive_correct = 0, next_due_at = CURRENT_TIMESTAMP
            WHERE word_id = ?
        """, (wid,))
    conn.execute("DELETE FROM learn_group WHERE id = ?", (group_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('session.learn_history'))


@bp.route('/session/history')
def learn_history():
    """Show all learn groups as a simple dated list."""
    groups_raw = get_all_learn_groups()
    groups = []
    for g in groups_raw:
        label = _group_label(g['id'])
        groups.append({'group': g, 'label': label})
    return render_template('learn_history.html', groups=groups)


@bp.route('/session/word-details/<int:word_id>')
def word_details(word_id):
    """Fetch full word details from dictionary API at runtime."""
    word_row = get_by_id(word_id)
    if not word_row:
        return jsonify({'error': 'not found'}), 404
    try:
        resp = http_requests.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{word_row['word'].strip().lower()}",
            timeout=6
        )
        if resp.status_code != 200:
            return jsonify({'error': 'not found in dictionary'}), 404
        data = resp.json()[0]
        phonetic = data.get('phonetic', '')
        audio_url = next(
            (p['audio'] for p in data.get('phonetics', []) if p.get('audio')), ''
        )
        meanings = []
        for m in data.get('meanings', []):
            pos = m.get('partOfSpeech', '')
            defs = []
            for d in m.get('definitions', []):
                defs.append({
                    'definition': d.get('definition', ''),
                    'example': d.get('example', ''),
                })
            synonyms = m.get('synonyms', [])
            antonyms = m.get('antonyms', [])
            meanings.append({'pos': pos, 'definitions': defs,
                              'synonyms': synonyms, 'antonyms': antonyms})
        return jsonify({
            'word': word_row['word'],
            'phonetic': phonetic,
            'audio_url': audio_url,
            'meanings': meanings,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
