// ── Quiz Logic ──────────────────────────────────────────────────────────────
let _answered = false;

function selectAnswer(btn) {
  if (_answered) return;
  _answered = true;

  const isCorrect = btn.dataset.correct === '1';
  const choiceId = btn.dataset.choiceId;

  // Set form values
  document.getElementById('choice-id-input').value = choiceId;
  document.getElementById('is-correct-input').value = isCorrect ? '1' : '0';

  // Highlight all buttons
  const buttons = document.querySelectorAll('.quiz-choice-btn');
  buttons.forEach(b => {
    b.disabled = true;
    if (b.dataset.correct === '1') {
      b.classList.add('choice-correct');
    }
    if (b === btn && !isCorrect) {
      b.classList.add('choice-incorrect');
    }
  });

  // Show feedback
  const feedback = document.getElementById('quiz-feedback');
  const icon = document.getElementById('feedback-icon');
  const text = document.getElementById('feedback-text');

  feedback.style.display = 'block';
  if (isCorrect) {
    icon.textContent = '✓';
    icon.className = 'feedback-icon feedback-correct';
    text.textContent = 'Correct!';
    text.className = 'feedback-text feedback-correct';
  } else {
    icon.textContent = '✗';
    icon.className = 'feedback-icon feedback-incorrect';
    text.textContent = 'Incorrect';
    text.className = 'feedback-text feedback-incorrect';
  }

  // Show next button
  document.getElementById('quiz-next-row').style.display = 'flex';

  // Scroll to next button on mobile
  setTimeout(() => {
    document.getElementById('quiz-next-row').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, 300);
}

// Keyboard shortcuts: 1-6 or A-F to select choices
document.addEventListener('keydown', function(e) {
  if (_answered) {
    // Enter to submit next
    if (e.key === 'Enter') {
      e.preventDefault();
      document.getElementById('quiz-form').submit();
    }
    return;
  }

  let idx = -1;
  if (e.key >= '1' && e.key <= '6') {
    idx = parseInt(e.key) - 1;
  } else if (e.key.toLowerCase() >= 'a' && e.key.toLowerCase() <= 'f') {
    idx = e.key.toLowerCase().charCodeAt(0) - 'a'.charCodeAt(0);
  }

  if (idx >= 0) {
    const buttons = document.querySelectorAll('.quiz-choice-btn');
    if (idx < buttons.length) {
      selectAnswer(buttons[idx]);
    }
  }
});
