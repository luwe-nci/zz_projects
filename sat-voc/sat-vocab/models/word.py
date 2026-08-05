import json
import requests
from database import get_db

try:
    from spellchecker import SpellChecker as _SpellChecker
    _spell = _SpellChecker()
except ImportError:
    _spell = None


def _parse_api_response(data):
    """Parse API response dict into (definition, pos, note, examples_json, audio_url)."""
    meanings = data[0].get('meanings', [])
    if not meanings:
        return None
    m = meanings[0]
    pos = m.get('partOfSpeech', '')
    defs = m.get('definitions', [])
    if not defs:
        return None
    definition = defs[0].get('definition', '')
    examples = []
    for meaning in meanings:
        for d in meaning.get('definitions', []):
            ex = d.get('example', '').strip()
            if ex and ex not in examples:
                examples.append(ex)
    note = examples[0] if examples else ''
    audio_url = next(
        (p['audio'] for p in data[0].get('phonetics', []) if p.get('audio')),
        ''
    )
    return definition, pos, note, json.dumps(examples), audio_url


def _spell_correct(word):
    """Return spell-corrected form if the word is unknown and a correction exists."""
    if _spell is None:
        return word
    w = word.lower()
    # If the word is already known, don't touch it
    if w in _spell:
        return w
    correction = _spell.correction(w)
    return correction if correction else w


def _api_fetch(word):
    """Raw API fetch. Returns parsed JSON list or None."""
    try:
        resp = requests.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{word.strip().lower()}",
            timeout=5
        )
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def _stem_candidates(word):
    """Return suffix-stripped fallback forms to try when the exact word 404s."""
    w = word.lower()
    candidates = []
    # Order matters — most specific first
    rules = [
        ('nesses', 'ness'), ('nesses', ''),        # impetuousness -> impetuous
        ('ness',   ''),                             # boldness -> bold
        ('ingly',  'ing'), ('ingly',  ''),
        ('ation',  'ate'), ('ation',  'e'), ('ation', ''),
        ('ations', 'ate'), ('ations', ''),
        ('tion',   'te'),  ('tion',   ''),
        ('ities',  'ity'), ('ities',  'e'), ('ities', 'y'),
        ('ity',    'e'),   ('ity',    ''),
        ('ments',  'ment'),('ment',   ''),
        ('ences',  'ence'),('ence',   ''),
        ('ances',  'ance'),('ance',   ''),
        ('nesses', ''),
        ('ious',   'e'),   ('ious',   ''),
        ('ous',    'e'),   ('ous',    ''),
        ('ful',    ''),
        ('less',   ''),
        ('ness',   ''),
        ('ings',   'ing'), ('ing',    'e'), ('ing', ''),
        ('edly',   'ed'),  ('edly',   ''),
        ('ed',     'e'),   ('ed',     ''),
        ('er',     'e'),   ('er',     ''),
        ('est',    'e'),   ('est',    ''),
        ('ly',     'le'),  ('ly',     ''),
        ('ies',    'y'),   ('ies',    'ie'),
        ('es',     'e'),   ('es',     ''),
        ('s',      ''),
    ]
    seen = {w}
    for suffix, replacement in rules:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            candidate = w[:-len(suffix)] + replacement
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
    return candidates


def lookup_definition(word):
    """Fetch from Free Dictionary API with suffix-stripping fallback.
    Returns (matched_word, definition, pos, note, examples_json, audio_url) or None."""
    data = _api_fetch(word)
    matched_word = word.strip().lower()
    if data is None:
        for candidate in _stem_candidates(word):
            data = _api_fetch(candidate)
            if data is not None:
                matched_word = candidate
                break
    if data is None:
        return None
    result = _parse_api_response(data)
    if result is None:
        return None
    definition, pos, note, examples_json, audio_url = result
    return matched_word, definition, pos, note, examples_json, audio_url


def fetch_examples(word):
    """Fetch fresh examples + audio for a word, with fallback. Returns (examples_list, audio_url)."""
    try:
        data = _api_fetch(word)
        if data is None:
            for candidate in _stem_candidates(word):
                data = _api_fetch(candidate)
                if data is not None:
                    break
        if data is None:
            return [], ''
        examples = []
        for meaning in data[0].get('meanings', []):
            for d in meaning.get('definitions', []):
                ex = d.get('example', '').strip()
                if ex and ex not in examples:
                    examples.append(ex)
        audio_url = next(
            (p['audio'] for p in data[0].get('phonetics', []) if p.get('audio')),
            ''
        )
        return examples, audio_url
    except Exception:
        return [], ''


def get_all(search='', page=1, per_page=30):
    conn = get_db()
    offset = (page - 1) * per_page
    if search:
        rows = conn.execute("""
            SELECT w.*, p.status, p.next_due_at, p.interval
            FROM words w
            LEFT JOIN user_word_progress p ON p.word_id = w.id
            WHERE w.word LIKE ?
            ORDER BY w.word
            LIMIT ? OFFSET ?
        """, (f'%{search}%', per_page, offset)).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM words WHERE word LIKE ?", (f'%{search}%',)
        ).fetchone()[0]
    else:
        rows = conn.execute("""
            SELECT w.*, p.status, p.next_due_at, p.interval
            FROM words w
            LEFT JOIN user_word_progress p ON p.word_id = w.id
            ORDER BY w.word
            LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    conn.close()
    return rows, total


def get_by_id(word_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
    conn.close()
    return row


def add(word, definition, pos='', note='', examples='', audio_url=''):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO words (word, definition, pos, note, examples, audio_url) VALUES (?, ?, ?, ?, ?, ?)",
            (word.strip(), definition.strip(), pos, note, examples, audio_url)
        )
        conn.commit()
        return True, 'added'
    except Exception:
        return False, 'duplicate'
    finally:
        conn.close()


def get_examples_list(word_row):
    """Return parsed examples list from a word row."""
    if word_row['examples']:
        try:
            return json.loads(word_row['examples'])
        except Exception:
            pass
    if word_row['note']:
        return [word_row['note']]
    return []


def update(word_id, definition, note, pos):
    conn = get_db()
    conn.execute(
        "UPDATE words SET definition = ?, note = ?, pos = ? WHERE id = ?",
        (definition, note, pos, word_id)
    )
    conn.commit()
    conn.close()


def delete(word_id):
    conn = get_db()
    conn.execute("DELETE FROM words WHERE id = ?", (word_id,))
    conn.commit()
    conn.close()


def import_from_text(text):
    """
    Returns a list of per-word result dicts:
      {original, chain: [(step, value)], final_word, outcome: added|skipped|failed}
    """
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    results = []

    for line in lines:
        entry = {'original': line, 'chain': [], 'final_word': None, 'outcome': None}

        if ':' in line:
            # Manual word: definition format
            parts = line.split(':', 1)
            word = parts[0].strip()
            definition = parts[1].strip()
            pos, note, examples, audio_url = '', '', '', ''

            lowered = word.lower()
            if lowered != word:
                entry['chain'].append(('lowercased', lowered))
                word = lowered

            entry['chain'].append(('manual definition', definition[:60] + ('…' if len(definition) > 60 else '')))
            entry['final_word'] = word

            ok, _ = add(word, definition, pos, note, examples, audio_url)
            entry['outcome'] = 'added' if ok else 'skipped'

        else:
            original = line.strip()
            current = original

            # Step 1: lowercase
            lowered = current.lower()
            if lowered != current:
                entry['chain'].append(('lowercased', lowered))
                current = lowered

            # Step 2: API lookup (includes stem-strip fallback inside lookup_definition)
            result = lookup_definition(current)
            if result:
                word, definition, pos, note, examples, audio_url = result
                if word != current:
                    entry['chain'].append(('stem-matched', word))
                else:
                    entry['chain'].append(('found', word))
                entry['final_word'] = word

                ok, _ = add(word, definition, pos, note, examples, audio_url)
                entry['outcome'] = 'added' if ok else 'skipped'
            else:
                entry['chain'].append(('not found in dictionary', current))
                entry['final_word'] = current
                entry['outcome'] = 'failed'

        results.append(entry)

    return results
