import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'data', 'vocab.db')
SECRET_KEY = 'sat-vocab-secret-key'
