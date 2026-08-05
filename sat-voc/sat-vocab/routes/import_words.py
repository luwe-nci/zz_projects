from flask import Blueprint, render_template, request
from models.word import import_from_text

bp = Blueprint('import_words', __name__)


@bp.route('/import', methods=['GET', 'POST'])
def import_page():
    result = None
    if request.method == 'POST':
        text = request.form.get('words_text', '')
        entries = import_from_text(text)
        added   = sum(1 for e in entries if e['outcome'] == 'added')
        skipped = sum(1 for e in entries if e['outcome'] == 'skipped')
        failed  = [e for e in entries if e['outcome'] == 'failed']
        result  = {'added': added, 'skipped': skipped, 'failed': failed, 'entries': entries}
    return render_template('import.html', result=result)
