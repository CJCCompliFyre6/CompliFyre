# backend/run.py
from dotenv import load_dotenv
load_dotenv()  # MUST come first

import os
from app import create_app

config_name = os.getenv('FLASK_ENV', 'development')
app = create_app(config_name)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
