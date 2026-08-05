from flask import Flask
from config import SECRET_KEY
from database import init_db
from routes.home import bp as home_bp
from routes.session import bp as session_bp
from routes.import_words import bp as import_bp
from routes.words import bp as words_bp
from routes.settings import bp as settings_bp
from routes.stats import bp as stats_bp

app = Flask(__name__)
app.secret_key = SECRET_KEY

app.register_blueprint(home_bp)
app.register_blueprint(session_bp)
app.register_blueprint(import_bp)
app.register_blueprint(words_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(stats_bp)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
