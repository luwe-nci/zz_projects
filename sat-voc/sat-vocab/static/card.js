// ── Speak ──────────────────────────────────────────────────────────────────
function speakText(text) {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'en-US';
  u.rate = 0.85;
  window.speechSynthesis.speak(u);
}

// ── Flip ───────────────────────────────────────────────────────────────────
let _flipped = false;

function flipCard() {
  _flipped = !_flipped;
  document.getElementById('card-flipper').classList.toggle('flipped', _flipped);
}

// Click anywhere on the card to flip, except buttons
document.addEventListener('DOMContentLoaded', function () {
  const scene = document.querySelector('.card-scene');
  if (scene) {
    scene.addEventListener('click', function (e) {
      if (e.target.closest('button')) return;
      flipCard();
    });
  }
});

// ── Example cycle (hidden → ex1 → ex2 → … → hidden → …) ──────────────────
let _examples = [];   // loaded from inline JSON on page load
let _exampleIdx = -1; // -1 = hidden

function initExamples(list) {
  _examples = list || [];
}

function cycleExample(wordId) {
  const wrap   = document.getElementById('card-example-wrap');
  const textEl = document.getElementById('card-example-text');
  const btn    = document.getElementById('example-toggle-btn');

  if (_examples.length === 0) {
    // No examples stored — fetch first
    fetch('/words/' + wordId + '/refresh-examples', { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        _examples = (data.examples && data.examples.length) ? data.examples : [];
        _exampleIdx = -1;
        cycleExample(wordId); // re-enter now that we have examples
      })
      .catch(() => {
        textEl.textContent = 'No example available.';
        wrap.classList.remove('card-example-hidden');
        _exampleIdx = 0;
      });
    return;
  }

  // Advance index: after last example, wrap back to -1 (hidden)
  _exampleIdx = (_exampleIdx + 1) % (_examples.length + 1);
  const hidden = _exampleIdx === _examples.length;

  wrap.classList.toggle('card-example-hidden', hidden);
  btn.classList.toggle('active', !hidden);

  if (!hidden) {
    textEl.textContent = '”' + _examples[_exampleIdx] + '”';
  }
}

// ── Full Details ───────────────────────────────────────────────────────────
let _detailsLoaded = false;

function loadDetails(wordId) {
  const panel = document.getElementById('details-panel');
  const btn   = document.getElementById('details-btn');
  const open  = panel.style.display !== 'none';
  panel.style.display = open ? 'none' : 'block';
  btn.textContent = open ? 'Show Full Details' : 'Hide Details';
  if (!open && !_detailsLoaded) {
    _detailsLoaded = true;
    fetch('/session/word-details/' + wordId)
      .then(r => r.json())
      .then(renderDetails)
      .catch(() => {
        document.getElementById('details-content').innerHTML =
          '<p class="details-error">Could not load details — check network.</p>';
      });
  }
}

// Escape text for use inside an HTML attribute value (single-quoted onclick)
function escAttr(text) {
  return text.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function speakerBtn(text) {
  return `<button class="btn-speak-sm" type="button"
    onclick="speakText('${escAttr(text)}')" title="Speak">&#128266;</button>`;
}

function renderDetails(data) {
  if (data.error) {
    document.getElementById('details-content').innerHTML =
      `<p class="details-error">${data.error}</p>`;
    return;
  }

  let html = '';
  html += `<div class="details-word-row">
    <span class="details-word">${data.word}</span>`;
  if (data.phonetic) html += `<span class="details-phonetic">${data.phonetic}</span>`;
  html += speakerBtn(data.word);
  html += `</div>`;

  data.meanings.forEach(m => {
    html += `<div class="details-meaning">`;
    html += `<div class="details-pos">${m.pos}</div>`;

    m.definitions.forEach((d, i) => {
      html += `<div class="details-def-block">
        <div class="details-def-row">
          <span class="details-def-num">${i + 1}.</span>
          <span class="details-def-text">${d.definition}</span>
          ${speakerBtn(d.definition)}
        </div>`;
      if (d.example) {
        html += `<div class="details-example-row">
          <span class="details-example-text">“${d.example}”</span>
          ${speakerBtn(d.example)}
        </div>`;
      }
      html += `</div>`;
    });

    if (m.synonyms && m.synonyms.length) {
      html += `<div class="details-syn-ant">
        <span class="details-syn-label">Synonyms:</span>
        <span class="details-chips">`;
      m.synonyms.forEach(s => {
        html += `<span class="chip chip-syn">${s} ${speakerBtn(s)}</span>`;
      });
      html += `</span></div>`;
    }

    if (m.antonyms && m.antonyms.length) {
      html += `<div class="details-syn-ant">
        <span class="details-ant-label">Antonyms:</span>
        <span class="details-chips">`;
      m.antonyms.forEach(a => {
        html += `<span class="chip chip-ant">${a} ${speakerBtn(a)}</span>`;
      });
      html += `</span></div>`;
    }

    html += `</div>`;
  });

  document.getElementById('details-content').innerHTML = html;
}
