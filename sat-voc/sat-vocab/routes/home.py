import requests as http_requests
from flask import Blueprint, render_template, jsonify, request
from scheduler import get_or_create_today_session, get_streak
from database import get_db
from models.word import import_from_text

bp = Blueprint('home', __name__)


@bp.route('/')
def index():
    session = get_or_create_today_session()
    streak = get_streak()

    conn = get_db()
    status_counts = {
        row['status']: row['cnt']
        for row in conn.execute("""
            SELECT status, COUNT(*) as cnt
            FROM user_word_progress
            GROUP BY status
        """).fetchall()
    }
    total_words = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    conn.close()

    return render_template('home.html',
                           session=session,
                           streak=streak,
                           status_counts=status_counts,
                           total_words=total_words)


@bp.route('/dictionary/lookup', methods=['POST'])
def dictionary_lookup():
    word = request.json.get('word', '').strip().lower()
    if not word:
        return jsonify({'error': 'No word provided'}), 400
    try:
        resp = http_requests.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
            timeout=6
        )
        if resp.status_code != 200:
            return jsonify({'error': f'"{word}" not found in dictionary'}), 404
        data = resp.json()[0]
        phonetic = data.get('phonetic', '')
        meanings = []
        for m in data.get('meanings', []):
            defs = [{'definition': d.get('definition', ''),
                     'example': d.get('example', '')}
                    for d in m.get('definitions', [])]
            meanings.append({'pos': m.get('partOfSpeech', ''),
                             'definitions': defs,
                             'synonyms': m.get('synonyms', []),
                             'antonyms': m.get('antonyms', [])})
        # Check if already in DB
        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM words WHERE word = ?", (word,)
        ).fetchone()
        conn.close()
        return jsonify({'word': word, 'phonetic': phonetic,
                        'meanings': meanings, 'audio_url': '',
                        'already_added': existing is not None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/dictionary/add', methods=['POST'])
def dictionary_add():
    word = request.json.get('word', '').strip()
    if not word:
        return jsonify({'error': 'No word provided'}), 400
    results = import_from_text(word)
    r = results[0] if results else {}
    return jsonify({
        'outcome': r.get('outcome'),
        'final_word': r.get('final_word'),
        'chain': r.get('chain', []),
    })
