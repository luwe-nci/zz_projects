import random
import json
import requests as _http
from flask import Blueprint, render_template, redirect, url_for, session as flask_session, request, jsonify
from scheduler import (get_due_words, get_or_create_today_session,
                       update_progress, increment_session_count, ensure_progress,
                       get_all_learn_groups, get_learn_group_word_ids)
from models.word import get_by_id
from database import get_db

bp = Blueprint('quiz', __name__)

QUIZ_TYPE_DEF  = 'word_to_def'
QUIZ_TYPE_WORD = 'def_to_word'
QUIZ_TYPE_SYN  = 'word_to_synonym'
ALL_TYPES = [QUIZ_TYPE_DEF, QUIZ_TYPE_WORD, QUIZ_TYPE_SYN]
TYPE_LABELS = {
    QUIZ_TYPE_DEF:  'Word → Definition',
    QUIZ_TYPE_WORD: 'Definition → Word',
    QUIZ_TYPE_SYN:  'Word → Synonym',
}

_PADDING_WORDS = [
    'ambiguous', 'benevolent', 'candid', 'diligent', 'eloquent',
    'furtive', 'gregarious', 'hapless', 'insipid', 'jovial',
    'languid', 'meticulous', 'nefarious', 'obscure', 'pragmatic',
    'quixotic', 'resilient', 'sagacious', 'tenacious', 'ubiquitous',
    'vacuous', 'wary', 'xenophobic', 'zealous', 'amiable',
    'brevity', 'cogent', 'deference', 'ephemeral', 'frivolous',
]


def _fetch_api_word(word):
    try:
        resp = _http.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
            timeout=5
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        meanings = data[0].get('meanings', [])
        if not meanings:
            return None
        defs = meanings[0].get('definitions', [])
        if not defs:
            return None
        return {'id': f'api:{word}', 'word': word, 'definition': defs[0].get('definition', '')}
    except Exception:
        return None


def _db_words_by_ids(ids):
    """Fetch word rows for a list of IDs in a single query."""
    if not ids:
        return []
    conn = get_db()
    placeholders = ','.join('?' * len(ids))
    rows = conn.execute(
        f"SELECT id, word, definition FROM words WHERE id IN ({placeholders})",
        ids
    ).fetchall()
    conn.close()
    return rows


def _get_distractors(exclude_ids, count, pool_ids):
    """
    Return `count` distractor word-dicts, sourced in priority order:
      1. pool_ids (the quiz's selected word pool)
      2. rest of the DB
      3. API padding words
    `exclude_ids` is a set of IDs (including the correct answer) to skip.
    """
    result = []
    seen_ids  = set(exclude_ids)
    seen_words = set()

    def _add(rows):
        for r in rows:
            if len(result) >= count:
                break
            rid = r['id'] if not isinstance(r['id'], str) else r['id']
            if rid in seen_ids:
                continue
            w = r['word']
            if w in seen_words:
                continue
            seen_ids.add(rid)
            seen_words.add(w)
            result.append(r)

    # Tier 1: pool words (shuffled)
    pool_candidates = [pid for pid in pool_ids if pid not in seen_ids]
    random.shuffle(pool_candidates)
    if pool_candidates:
        _add(_db_words_by_ids(pool_candidates))

    # Tier 2: rest of DB (excluding already collected)
    if len(result) < count:
        conn = get_db()
        exclude_list = list(seen_ids)
        placeholders = ','.join('?' * len(exclude_list)) if exclude_list else '0'
        rows = conn.execute(
            f"SELECT id, word, definition FROM words WHERE id NOT IN ({placeholders}) ORDER BY RANDOM() LIMIT ?",
            exclude_list + [count - len(result)]
        ).fetchall()
        conn.close()
        _add(rows)

    # Tier 3: API padding
    if len(result) < count:
        candidates = [w for w in _PADDING_WORDS if w not in seen_words]
        random.shuffle(candidates)
        for word in candidates:
            if len(result) >= count:
                break
            fetched = _fetch_api_word(word)
            if fetched:
                _add([fetched])

    return result


def _find_synonym(word_id, pool_ids):
    """
    Find a synonym row for word_id, searching in priority order:
      1. pool words whose definition shares keywords
      2. full DB words whose definition shares keywords
      3. random pool word
      4. random DB word
    """
    word = get_by_id(word_id)
    if not word:
        return None

    definition = word['definition'] or ''
    stopwords = {'which', 'being', 'having', 'about', 'their', 'there',
                 'these', 'those', 'would', 'could', 'should'}
    keywords = [w.strip().lower() for w in definition.split()
                if len(w.strip()) > 4 and w.strip().lower() not in stopwords]
    random.shuffle(keywords)

    conn = get_db()

    # Tier 1: pool words with matching definition keywords
    if keywords and pool_ids:
        pool_excl = [pid for pid in pool_ids if pid != word_id]
        if pool_excl:
            placeholders = ','.join('?' * len(pool_excl))
            for kw in keywords[:5]:
                row = conn.execute(
                    f"SELECT id, word, definition FROM words "
                    f"WHERE id IN ({placeholders}) AND definition LIKE ? "
                    f"ORDER BY RANDOM() LIMIT 1",
                    pool_excl + [f'%{kw}%']
                ).fetchone()
                if row:
                    conn.close()
                    return row

    # Tier 2: any DB word with matching definition keywords
    if keywords:
        for kw in keywords[:5]:
            row = conn.execute(
                "SELECT id, word, definition FROM words "
                "WHERE id != ? AND definition LIKE ? ORDER BY RANDOM() LIMIT 1",
                (word_id, f'%{kw}%')
            ).fetchone()
            if row:
                conn.close()
                return row

    # Tier 3: random pool word
    if pool_ids:
        pool_excl = [pid for pid in pool_ids if pid != word_id]
        if pool_excl:
            placeholders = ','.join('?' * len(pool_excl))
            row = conn.execute(
                f"SELECT id, word, definition FROM words WHERE id IN ({placeholders}) ORDER BY RANDOM() LIMIT 1",
                pool_excl
            ).fetchone()
            if row:
                conn.close()
                return row

    # Tier 4: random DB word
    row = conn.execute(
        "SELECT id, word, definition FROM words WHERE id != ? ORDER BY RANDOM() LIMIT 1",
        (word_id,)
    ).fetchone()
    conn.close()
    return row


def _build_quiz_question(word_id, quiz_type, pool_ids):
    word = get_by_id(word_id)
    if not word:
        return None

    if quiz_type == QUIZ_TYPE_DEF:
        distractors = _get_distractors({word_id}, 5, pool_ids)
        choices = [{'id': word['id'], 'text': word['definition'], 'correct': True}]
        for d in distractors:
            choices.append({'id': d['id'], 'text': d['definition'], 'correct': False})
        random.shuffle(choices)
        return {
            'word_id': word['id'],
            'type': quiz_type,
            'prompt': word['word'],
            'prompt_sub': word['pos'] or '',
            'instruction': 'Choose the correct definition',
            'choices': choices,
        }

    elif quiz_type == QUIZ_TYPE_WORD:
        distractors = _get_distractors({word_id}, 5, pool_ids)
        choices = [{'id': word['id'], 'text': word['word'], 'correct': True}]
        for d in distractors:
            choices.append({'id': d['id'], 'text': d['word'], 'correct': False})
        random.shuffle(choices)
        return {
            'word_id': word['id'],
            'type': quiz_type,
            'prompt': word['definition'],
            'prompt_sub': word['pos'] or '',
            'instruction': 'Choose the matching word',
            'choices': choices,
        }

    elif quiz_type == QUIZ_TYPE_SYN:
        synonym_row = _find_synonym(word_id, pool_ids)
        if not synonym_row:
            return None

        distractors = _get_distractors({word_id, synonym_row['id']}, 4, pool_ids)
        choices = [{'id': synonym_row['id'], 'text': synonym_row['word'], 'correct': True}]
        for d in distractors:
            choices.append({'id': d['id'], 'text': d['word'], 'correct': False})
        random.shuffle(choices)
        return {
            'word_id': word['id'],
            'type': quiz_type,
            'prompt': word['word'],
            'prompt_sub': f"({word['definition'][:80]}{'…' if len(word['definition'] or '') > 80 else ''})",
            'instruction': 'Choose the word with a similar meaning',
            'choices': choices,
        }

    return None


def _get_word_pool(source, group_ids):
    conn = get_db()
    if source == 'all':
        rows = conn.execute("SELECT id FROM words ORDER BY RANDOM()").fetchall()
        pool = [r['id'] for r in rows]
        conn.close()
        return pool

    if group_ids:
        gids = [int(g) for g in group_ids]
    else:
        gids = [r['id'] for r in conn.execute(
            "SELECT id FROM learn_group ORDER BY id"
        ).fetchall()]
    conn.close()

    seen = set()
    pool = []
    for gid in gids:
        for wid in get_learn_group_word_ids(gid):
            if wid not in seen:
                seen.add(wid)
                pool.append(wid)
    random.shuffle(pool)
    return pool


# ── Config page ───────────────────────────────────────────────────────────────

@bp.route('/quiz/config', methods=['GET', 'POST'])
def config():
    conn = get_db()
    settings = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    groups_raw = get_all_learn_groups()
    groups = []
    for g in groups_raw:
        from routes.session import _group_label
        groups.append({'group': g, 'label': _group_label(g['id'])})
    conn.close()

    default_size = settings['test_size'] if settings and settings['test_size'] else 10

    if request.method == 'POST':
        source     = request.form.get('source', 'groups')
        group_ids  = request.form.getlist('group_ids')
        test_types = request.form.getlist('test_types') or ALL_TYPES
        size       = max(1, min(200, int(request.form.get('size', default_size))))

        conn = get_db()
        conn.execute("UPDATE settings SET test_size = ? WHERE id = 1", (size,))
        conn.commit()
        conn.close()

        flask_session['quiz_config'] = {
            'source': source,
            'group_ids': group_ids,
            'test_types': test_types,
            'size': size,
        }
        return redirect(url_for('quiz.start'))

    return render_template('quiz_config.html',
                           groups=groups,
                           default_size=default_size,
                           all_types=ALL_TYPES,
                           type_labels=TYPE_LABELS)


# ── Quiz flow ─────────────────────────────────────────────────────────────────

def _build_quiz_queue_from_config(cfg):
    source    = cfg.get('source', 'groups')
    group_ids = cfg.get('group_ids', [])
    types     = cfg.get('test_types', ALL_TYPES)
    size      = cfg.get('size', 10)

    full_pool = _get_word_pool(source, group_ids)
    quiz_pool = full_pool[:size]
    if not quiz_pool:
        return [], []

    queue = [{'word_id': wid, 'type': types[i % len(types)]}
             for i, wid in enumerate(quiz_pool)]
    return queue, full_pool


@bp.route('/quiz/start')
def start():
    cfg = flask_session.get('quiz_config')
    if cfg:
        queue, pool_ids = _build_quiz_queue_from_config(cfg)
    else:
        today = get_or_create_today_session()
        test_remaining = max(0, today['test_target'] - today['test_done'])
        word_ids = get_due_words('review', test_remaining) if test_remaining else []
        queue    = [{'word_id': wid, 'type': ALL_TYPES[i % 3]}
                    for i, wid in enumerate(word_ids)]
        pool_ids = word_ids

    flask_session['quiz_queue']    = queue
    flask_session['quiz_pool_ids'] = pool_ids
    flask_session['quiz_index']    = 0
    flask_session['quiz_score']    = {
        'correct': 0,
        'incorrect': 0,
        'by_type': {t: {'correct': 0, 'incorrect': 0} for t in ALL_TYPES},
    }

    if not queue:
        return redirect(url_for('quiz.done'))
    return redirect(url_for('quiz.question'))


@bp.route('/quiz/question')
def question():
    queue    = flask_session.get('quiz_queue', [])
    pool_ids = flask_session.get('quiz_pool_ids', [])
    idx      = flask_session.get('quiz_index', 0)

    if idx >= len(queue):
        return redirect(url_for('quiz.done'))

    item = queue[idx]
    q = _build_quiz_question(item['word_id'], item['type'], pool_ids)

    if not q:
        flask_session['quiz_index'] = idx + 1
        return redirect(url_for('quiz.question'))

    ensure_progress(item['word_id'])
    return render_template('quiz.html',
                           question=q,
                           current=idx + 1,
                           total=len(queue),
                           quiz_type=item['type'])


@bp.route('/quiz/answer', methods=['POST'])
def answer():
    queue = flask_session.get('quiz_queue', [])
    idx   = flask_session.get('quiz_index', 0)
    score = flask_session.get('quiz_score', {
        'correct': 0, 'incorrect': 0,
        'by_type': {t: {'correct': 0, 'incorrect': 0} for t in ALL_TYPES},
    })

    if idx >= len(queue):
        return redirect(url_for('quiz.done'))

    item       = queue[idx]
    is_correct = request.form.get('is_correct') == '1'
    qtype      = item['type']

    if is_correct:
        score['correct'] += 1
        score.setdefault('by_type', {}).setdefault(qtype, {'correct': 0, 'incorrect': 0})['correct'] += 1
        rating = 'easy'
    else:
        score['incorrect'] += 1
        score.setdefault('by_type', {}).setdefault(qtype, {'correct': 0, 'incorrect': 0})['incorrect'] += 1
        rating = 'missed'

    update_progress(item['word_id'], rating)
    increment_session_count('test', word_id=item['word_id'])

    flask_session['quiz_score'] = score
    flask_session['quiz_index'] = idx + 1

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'correct': is_correct, 'next': url_for('quiz.question')})
    return redirect(url_for('quiz.question'))


@bp.route('/quiz/done')
def done():
    score   = flask_session.get('quiz_score', {'correct': 0, 'incorrect': 0, 'by_type': {}})
    total_q = score['correct'] + score['incorrect']
    pct     = round(score['correct'] / total_q * 100) if total_q > 0 else 0
    by_type = score.get('by_type', {})

    type_rows = []
    for t in ALL_TYPES:
        ts  = by_type.get(t, {'correct': 0, 'incorrect': 0})
        tot = ts['correct'] + ts['incorrect']
        if tot > 0:
            type_rows.append({
                'label':     TYPE_LABELS[t],
                'correct':   ts['correct'],
                'incorrect': ts['incorrect'],
                'total':     tot,
                'pct':       round(ts['correct'] / tot * 100),
            })

    return render_template('quiz_done.html',
                           score=score,
                           total=total_q,
                           pct=pct,
                           type_rows=type_rows)
