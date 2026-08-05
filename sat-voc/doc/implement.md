# SAT Vocabulary Website — Implementation Reference

## Project Structure

```
sat-vocab/
├── app.py                    # Flask app entry point, blueprint registration
├── config.py                 # SECRET_KEY, DATABASE path
├── database.py               # SQLite connection, schema init (init_db)
├── scheduler.py              # SM-2 logic, learn group management, session counts
├── models/
│   └── word.py               # Word CRUD, import pipeline, API fetch, stem-strip
├── routes/
│   ├── home.py               # /, /dictionary/lookup, /dictionary/add
│   ├── session.py            # /session/*, /session/group/*, /session/history
│   ├── import_words.py       # /import
│   ├── words.py              # /words, /words/<id>, /words/<id>/rate, /words/reset-selected
│   ├── settings.py           # /settings
│   └── stats.py              # /stats
├── templates/
│   ├── base.html             # Nav, layout wrapper
│   ├── home.html             # Dashboard + dictionary lookup
│   ├── session.html          # Flashcard study UI
│   ├── session_done.html     # Session complete, group-complete banner
│   ├── queue_list.html       # Word list for learn group or review/test queue
│   ├── learn_history.html    # All learn groups listed by date
│   ├── word_card.html        # Standalone word card with prev/next nav
│   ├── import.html           # Import page with per-word chain results
│   ├── words.html            # Full word list with select/reset
│   ├── stats.html            # Stats and bar chart
│   └── settings.html         # Settings form
├── static/
│   ├── style.css             # All styles
│   └── card.js               # flip, speak, cycleExample, loadDetails, renderDetails
├── data/
│   └── vocab.db              # SQLite DB (auto-created on first run)
└── requirements.txt          # flask, requests
```

---

## Running

```bash
pip install flask requests
python3 app.py          # serves on http://0.0.0.0:5000
```

`init_db()` runs on startup — safe to call repeatedly (uses `CREATE TABLE IF NOT EXISTS`).

---

## Key Modules

### `database.py`
- `get_db()` — returns a `sqlite3.Row`-factory connection
- `init_db()` — creates all tables and the default settings row

### `scheduler.py`

**SM-2 core:**
- `ensure_progress(word_id)` — inserts a progress row if missing
- `update_progress(word_id, rating)` — applies SM-2, updates status

**Rating → status transitions:**

| Rating | From `new`/`learning` | From `review` | From `mastered` |
|--------|-----------------------|---------------|-----------------|
| easy   | → `review`, interval=7 | interval × ease; 3 consecutive → `mastered` | interval × ease |
| hard   | → `learning`, interval=3 | stays, interval × 1.2 | stays, interval × 1.2 |
| missed | → `learning`, interval=1 | → `learning`, interval=1 | → `learning`, interval=1 |

ease_factor: easy +0.1, hard −0.15, missed −0.2 (floor 1.3)

**Learn groups:**
- `get_or_create_learn_group(size)` — returns active group or creates one with `size` new words
- `create_next_learn_group(size)` — closes active group, creates next
- `get_due_words(mode, limit)` — learn: from active group (status=new); review/test: due by date
- `get_done_word_ids(mode)` — word_ids logged in `daily_word_log` today for the given mode
- `increment_session_count(mode, word_id)` — increments daily counter + logs to `daily_word_log`
- `get_all_learn_groups()` — all groups newest-first with word count
- `get_active_learn_group()` — the single incomplete group, or None

**Sessions:**
- `get_or_create_today_session()` — creates today's `daily_session` row from settings if missing
- `get_streak()` — consecutive days where all targets were met

### `models/word.py`

**Import pipeline** (`import_from_text(text)`):
1. Lowercase
2. `_api_fetch(word)` — GET Free Dictionary API
3. `_stem_candidates(word)` — strips suffixes (ness, ing, ous, tion, ly, ed, …), retries API
4. Fail if nothing found

Returns list of `{original, chain: [(step, value), …], final_word, outcome}` per word.

**Other:**
- `lookup_definition(word)` — fetch + stem fallback, returns `(matched_word, definition, pos, note, examples_json, audio_url)` or None
- `fetch_examples(word)` — returns `(examples_list, audio_url)` for refresh
- `get_all(search, page, per_page)` — paginated word list with progress join
- `add / update / delete` — standard CRUD

### `routes/session.py`

- `build_queue()` — creates active learn group if needed, returns list of `{id, mode}` dicts stored in Flask session
- `start` → `card` → `rate` / `skip` → `card` … → `done`
- `queue_list(mode)` — review/test list with done checkmarks; learn redirects to `group_detail`
- `group_detail(group_id)` — shows all words in a learn group with checkmarks; active group uses `daily_word_log`, completed groups use SM-2 status
- `manual_check(mode, word_id)` — POST, rates word as hard + logs to `daily_word_log`; used by circle→checkmark click in list
- `reset_group(group_id)` — POST, resets all words in group to new, deletes the group
- `learn_history()` — all groups as dated list
- `_group_label(group_id)` — returns `2026-08-04` or `2026-08-04a`/`b`/`c` if multiple groups same day

### `routes/words.py`

- `word_card(word_id)` — standalone card; accepts `?back=`, `?ids=`, `?idx=` for list navigation
- `rate_word(word_id)` — POST, updates SM-2 + logs to `daily_word_log` with mode inferred from `back` param
- `reset_selected()` — POST, resets chosen word_ids to new status

### `routes/home.py`

- `dictionary_lookup()` — POST JSON `{word}`, returns full API data + `already_added` flag
- `dictionary_add()` — POST JSON `{word}`, runs `import_from_text` pipeline

### `static/card.js`

- `flipCard()` — toggles `.flipped` on `#card-flipper`
- Click on `.card-scene` (excluding buttons) calls `flipCard()`
- `cycleExample(wordId)` — hidden → ex0 → ex1 → … → hidden; fetches from API on first call if empty
- `loadDetails(wordId)` — lazy-fetches `/session/word-details/<id>`, calls `renderDetails`
- `renderDetails(data)` — builds full details HTML with `speakerBtn()` on every item
- `escAttr(text)` — escapes `\` and `'` for safe single-quoted onclick attributes

---

## Database Schema

```sql
CREATE TABLE words (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    word       TEXT NOT NULL UNIQUE,
    definition TEXT NOT NULL,
    note       TEXT,
    examples   TEXT,          -- JSON array of example sentences
    pos        TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_word_progress (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id             INTEGER REFERENCES words(id) ON DELETE CASCADE,
    interval            INTEGER DEFAULT 1,
    ease_factor         REAL DEFAULT 2.5,
    consecutive_correct INTEGER DEFAULT 0,
    last_reviewed_at    DATETIME,
    next_due_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    status              TEXT DEFAULT 'new'  -- new/learning/review/mastered
);

CREATE TABLE daily_session (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          DATE NOT NULL UNIQUE,
    learn_target  INTEGER DEFAULT 0,
    review_target INTEGER DEFAULT 0,
    test_target   INTEGER DEFAULT 0,
    learn_done    INTEGER DEFAULT 0,
    review_done   INTEGER DEFAULT 0,
    test_done     INTEGER DEFAULT 0,
    completed_at  DATETIME
);

CREATE TABLE daily_word_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    date    DATE NOT NULL,
    word_id INTEGER REFERENCES words(id) ON DELETE CASCADE,
    mode    TEXT NOT NULL    -- learn/review/test
);
CREATE INDEX idx_dwl_date ON daily_word_log(date, mode);

CREATE TABLE learn_group (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   DATE NOT NULL,
    completed_at DATE          -- NULL = active
);

CREATE TABLE learn_group_word (
    group_id INTEGER NOT NULL REFERENCES learn_group(id) ON DELETE CASCADE,
    word_id  INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, word_id)
);

CREATE TABLE settings (
    id                  INTEGER PRIMARY KEY DEFAULT 1,
    daily_learn_count   INTEGER DEFAULT 10,
    daily_review_count  INTEGER DEFAULT 20,
    daily_test_count    INTEGER DEFAULT 10,
    show_word_first     INTEGER DEFAULT 1   -- 1=word front, 0=definition front
);
```

---

## Known Design Decisions & Gotchas

- **No nested `<form>` tags** — the word list uses a dynamically-built form (via JS) for reset-selected so it doesn't interfere with inline delete forms.
- **`daily_word_log` is date-scoped** — checkmarks reset each day. Completed groups use SM-2 status instead.
- **`back` param** in word card URLs encodes the return context: `'words'`, `'group:<id>'`, or `'history'`. The `rate_word` route uses this to infer which mode to log.
- **Learn group auto-created** on session start or Learn card click — `get_or_create_learn_group` is idempotent.
- **Group completion is manual** — the session-done page shows a "Start Next Group" button only when no words in the active group remain as `new`. Clicking it calls `create_next_learn_group`.
- **Stem-strip order matters** — longer suffixes must be checked before shorter ones (e.g. `nesses` before `ness`) to avoid partial matches.
- **Free Dictionary API** returns 404 for inflected forms — the stem-strip fallback handles this at import time and the matched (root) word is what gets stored.

---

## Potential Improvements

- Spell-correction fallback on import (`pyspellchecker` is installed but disabled — hook in `_spell_correct` in `import_from_text`)
- Export word list to CSV/Anki
- Multiple word banks / user profiles
- Mobile PWA / offline support
- Audio pronunciation (API CDN URLs are unreliable; Web Speech API is the current fallback)
- Smarter test mode (multiple choice, fill-in-the-blank)
