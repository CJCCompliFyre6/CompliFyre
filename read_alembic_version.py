
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

db_user = os.environ.get('DB_USER')
db_password = os.environ.get('DB_PASSWORD')
db_host = os.environ.get('DB_HOST')
db_port = os.environ.get('DB_PORT')
db_name = os.environ.get('DB_NAME')
db_uri = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'

engine = create_engine(db_uri)

try:
    with engine.connect() as connection:
        result = connection.execute(text('SELECT * FROM alembic_version'))
        for row in result:
            print(row)
except Exception as e:
    print(f"An error occurred: {e}")
