import json
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from models.word import get_all, get_by_id, add, update, delete, fetch_examples
from database import get_db

bp = Blueprint('words', __name__)


@bp.route('/words')
def word_list():
    search = request.args.get('search', '')
    page = int(request.args.get('page', 1))
    words, total = get_all(search=search, page=page)
    pages = (total + 29) // 30
    return render_template('words.html', words=words, search=search,
                           page=page, pages=pages, total=total)


@bp.route('/words/<int:word_id>')
def word_card(word_id):
    word = get_by_id(word_id)
    if not word:
        return redirect(url_for('words.word_list'))
    import json as _json
    raw = word['examples'] or ''
    try:
        examples_list = _json.loads(raw) if raw else []
    except Exception:
        examples_list = []
    if not examples_list and word['note']:
        examples_list = [word['note']]
    examples_json = _json.dumps(examples_list)

    # Optional list navigation: ?group=<id> or ?back=words, with ?ids=1,2,3&idx=0
    back = request.args.get('back', 'words')        # 'words' | 'group:<id>' | 'history'
    ids_param = request.args.get('ids', '')
    idx = int(request.args.get('idx', 0))
    nav_ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]

    prev_url = next_url = back_url = None
    if back == 'words':
        back_url = url_for('words.word_list')
    elif back == 'history':
        back_url = url_for('session.learn_history')
    elif back.startswith('group:'):
        gid = back.split(':', 1)[1]
        back_url = url_for('session.group_detail', group_id=gid)
    else:
        back_url = url_for('words.word_list')

    if nav_ids:
        def _card_url(i):
            return url_for('words.word_card', word_id=nav_ids[i],
                           back=back, ids=ids_param, idx=i)
        if idx > 0:
            prev_url = _card_url(idx - 1)
        if idx < len(nav_ids) - 1:
            next_url = _card_url(idx + 1)
        # if last card, next goes back to the list
        if idx == len(nav_ids) - 1:
            next_url = None  # template will show "Back to List" instead

    return render_template('word_card.html', word=word, examples_json=examples_json,
                           back_url=back_url, prev_url=prev_url, next_url=next_url,
                           is_last=(nav_ids and idx == len(nav_ids) - 1),
                           current=idx + 1 if nav_ids else None,
                           total=len(nav_ids) if nav_ids else None)


@bp.route('/words/<int:word_id>/rate', methods=['POST'])
def rate_word(word_id):
    """Rate a word from the word card (outside of a session queue)."""
    from scheduler import update_progress, ensure_progress, increment_session_count
    rating = request.form.get('rating', 'missed')
    ensure_progress(word_id)
    update_progress(word_id, rating)
    # Determine mode from back param so the right list gets checkmarked
    back = request.form.get('back', 'words')
    mode = 'learn' if back.startswith('group:') else 'review'
    increment_session_count(mode, word_id=word_id)
    ids_param = request.form.get('ids', '')
    idx = request.form.get('idx', '0')
    return redirect(url_for('words.word_card', word_id=word_id,
                            back=back, ids=ids_param, idx=idx))


@bp.route('/words/add', methods=['POST'])
def add_word():
    word = request.form.get('word', '').strip()
    definition = request.form.get('definition', '').strip()
    pos = request.form.get('pos', '').strip()
    note = request.form.get('note', '').strip()
    if word and definition:
        add(word, definition, pos, note)
    return redirect(url_for('words.word_list'))


@bp.route('/words/<int:word_id>/edit', methods=['POST'])
def edit_word(word_id):
    definition = request.form.get('definition', '').strip()
    note = request.form.get('note', '').strip()
    pos = request.form.get('pos', '').strip()
    update(word_id, definition, note, pos)
    return redirect(url_for('words.word_list'))


@bp.route('/words/<int:word_id>/delete', methods=['POST'])
def delete_word(word_id):
    delete(word_id)
    return redirect(url_for('words.word_list'))


@bp.route('/words/<int:word_id>/refresh-examples', methods=['POST'])
def refresh_examples(word_id):
    """Fetch fresh examples + audio from API. Used by card cycle button."""
    word_row = get_by_id(word_id)
    if not word_row:
        return jsonify({'error': 'not found'}), 404
    examples, audio_url = fetch_examples(word_row['word'])
    conn = get_db()
    conn.execute(
        "UPDATE words SET note = ?, examples = ?, audio_url = ? WHERE id = ?",
        (examples[0] if examples else '', json.dumps(examples), audio_url, word_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'examples': examples, 'example': examples[0] if examples else '', 'audio_url': audio_url})


@bp.route('/words/reset-selected', methods=['POST'])
def reset_selected():
    """Reset selected words back to 'new' status."""
    ids = request.form.getlist('word_ids')
    if ids:
        conn = get_db()
        for wid in ids:
            conn.execute("""
                UPDATE user_word_progress
                SET status = 'new', interval = 1, ease_factor = 2.5,
                    consecutive_correct = 0, next_due_at = CURRENT_TIMESTAMP
                WHERE word_id = ?
            """, (wid,))
        conn.commit()
        conn.close()
    return redirect(url_for('words.word_list',
                            search=request.form.get('search', ''),
                            page=request.form.get('page', 1)))


@bp.route('/words/fill-examples', methods=['POST'])
def fill_examples_route():
    """Batch-fetch examples + audio for all words that have none."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, word FROM words WHERE (note IS NULL OR note = '' OR note = '(definition pending)')"
        " AND (examples IS NULL OR examples = '')"
    ).fetchall()
    conn.close()
    updated = 0
    for row in rows:
        examples, audio_url = fetch_examples(row['word'])
        if examples or audio_url:
            conn = get_db()
            conn.execute(
                "UPDATE words SET note = ?, examples = ?, audio_url = ? WHERE id = ?",
                (examples[0] if examples else '', json.dumps(examples), audio_url, row['id'])
            )
            conn.commit()
            conn.close()
            updated += 1
    return jsonify({'updated': updated, 'total': len(rows)})
