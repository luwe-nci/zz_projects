# SAT Vocabulary Learning Website — Design Document

## Overview

A local Flask web app for learning SAT vocabulary using spaced repetition. Words are studied in batches (learn groups), rated on each card, and scheduled for future review based on performance.

---

## Tech Stack

| Layer      | Choice                | Rationale                                    |
|------------|-----------------------|----------------------------------------------|
| Frontend   | Jinja2 + HTML/CSS/JS  | Server-rendered templates, vanilla JS        |
| Backend    | Python / Flask        | Lightweight Python web framework             |
| Database   | SQLite (local file)   | File-based, zero config, ships with Python   |
| Dictionary | Free Dictionary API   | Auto-lookup definitions on import and lookup |
| Audio      | Web Speech API        | Browser-native TTS, no CDN dependency        |

---

## Features

### 1. Flashcards

Each card has a front (word) and back (definition). Click anywhere on the card to flip it.

- **Part of speech** shown as a subtitle
- **Note/example toggle** — cycles through stored examples; fetches from API on first tap if empty
- **Speaker button** on each face to pronounce the text
- **Rating buttons** — always visible (no need to flip first): Easy / Hard / Didn't Know
- **Next button** — skip to the next card without rating
- **Details panel** — expandable, fetches full API data on demand: all definitions, examples, synonyms, antonyms, each with speaker buttons

Card orientation (word-first or definition-first) is configurable in Settings.

### 2. Word Import

Words are pasted into a text area (one per line, or `word: definition` for manual entry).

**Normalization pipeline** (applied in order):
1. **Lowercase** — `Impetuousness` → `impetuousness`
2. **API lookup** — exact match attempted first
3. **Stem-strip fallback** — if not found, common suffixes are stripped and the API is retried
   - Examples: `litigiousness` → `litigious`, `burgeoned` → `burgeon`, `impetuousness` → `impetuous`
4. **Fail** — if nothing resolves, shows failure with a manual-add link

Each word's import result shows every normalization step and the final outcome (added / skipped duplicate / failed).

### 3. Dictionary Lookup (Home Page)

Type any word on the home page to look it up instantly (press Enter or click Look Up). Shows the full details panel with all definitions, examples, synonyms, and antonyms — each with speaker buttons. An **"+ Add to Learn"** button runs the same import pipeline and adds the word to the word bank.

### 4. Learn Groups

New words are studied in fixed-size batches called **learn groups**. The group size matches the daily learn target (default: 10 words).

**Group lifecycle:**

1. **Created** — automatically when a session starts or the Learn card is clicked on the home page, if no active group exists. Words are picked from the word bank in import order, excluding words already assigned to any previous group.
2. **In Progress** — the active group. Only words in this group with status `new` appear in learn sessions.
3. **Completed** — when all words in the active group have been rated at least once (no words remain as `new`), the session-done screen shows a **"🎉 Learn group complete!"** banner with a **"Start Next Group →"** button. Clicking it marks the current group done and creates the next one.

**Learn History** lists all groups by date (e.g. `2026-08-04`). If multiple groups were created on the same day they get letter suffixes: `2026-08-04a`, `2026-08-04b`, etc. Each group name links to its word list. The back button on a group list returns to where you came from (home page or history page).

### 5. Spaced Repetition (SM-2)

Every word has a progress record: `status`, `interval` (days), `ease_factor`, `consecutive_correct`.

**Statuses:** `new` → `learning` → `review` → `mastered`

**Rating behaviour:**

| Button | From `new` or `learning` | From `review` | From `mastered` |
|--------|--------------------------|---------------|-----------------|
| **Easy** | → `review`, interval = 7 days | interval × ease_factor; 3 consecutive easy → `mastered` | interval × ease_factor |
| **Hard** | → `learning`, interval = 3 days | stays `review`, interval × 1.2 | stays `mastered`, interval × 1.2 |
| **Missed** | → `learning`, interval = 1 day | → `learning`, interval = 1 day | → `learning`, interval = 1 day |

**Key rule:** one **Easy** immediately removes a word from the active learn list. It is scheduled for review in 7 days and will not reappear in learn sessions until that date.

**ease_factor** adjustments per rating:
- Easy: +0.1 (floor 1.3)
- Hard: −0.15 (floor 1.3)
- Missed: −0.2 (floor 1.3)

### 6. Daily Sessions

Each day a session record is created with configurable targets (defaults: 10 learn / 20 review / 10 test). The home page shows done/target progress bars for each mode.

**What appears in each mode:**
- **Learn** — words in the active learn group with status `new`
- **Review** — words with status `learning` or `review` whose `next_due_at` ≤ today
- **Test** — same pool as review

Clicking a mode on the home page goes to that mode's word list. Learn goes directly to the active group list. Each word in the list shows a checkmark (done today) or circle (remaining).

### 7. Word List

Full paginated word list with search. Columns: Word, Definition, Note — all resizable by drag. Definition and Note columns are toggleable (click header label to hide/show). Hover-reveal speaker buttons on each row. Click a word to open its standalone card.

### 8. Standalone Word Card

Accessible from any word list. Same flip card UI with always-visible rating buttons. Rating here updates SM-2 progress directly (outside the daily session counter). Prev/Next buttons navigate through the source list. Back button returns to wherever the card was opened from.

---

## Data Model

```
words
  id, word, definition, note, examples (JSON array), pos, created_at

user_word_progress
  word_id, interval, ease_factor, consecutive_correct,
  last_reviewed_at, next_due_at, status (new/learning/review/mastered)

daily_session
  date, learn_target, review_target, test_target,
  learn_done, review_done, test_done, completed_at

daily_word_log
  date, word_id, mode       — tracks which words were done today per mode

learn_group
  id, started_at, completed_at

learn_group_word
  group_id, word_id

settings
  daily_learn_count (10), daily_review_count (20), daily_test_count (10),
  show_word_first (1)
```

---

## Page Map

| Route | Description |
|-------|-------------|
| `/` | Home — streak, daily progress, dictionary lookup |
| `/session/start` | Build queue and redirect to first card |
| `/session/card` | Current flashcard in the session queue |
| `/session/rate` | POST — record rating, advance queue |
| `/session/skip` | Advance queue without rating |
| `/session/done` | Session complete; shows "Next Group" if group finished |
| `/session/next-group` | POST — complete active group, create next |
| `/session/queue/<mode>` | Word list for review/test mode |
| `/session/group/<id>` | Word list for a specific learn group |
| `/session/history` | All learn groups listed by date |
| `/words` | Full word list with search and pagination |
| `/words/<id>` | Standalone word card with prev/next nav |
| `/words/<id>/rate` | POST — rate a word from standalone card |
| `/import` | Import words by pasting text |
| `/stats` | Study statistics and charts |
| `/settings` | Configure daily targets and card orientation |
| `/dictionary/lookup` | POST (JSON) — look up a word via API |
| `/dictionary/add` | POST (JSON) — add a looked-up word to the bank |
