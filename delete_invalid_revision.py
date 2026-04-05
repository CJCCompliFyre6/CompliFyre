
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
        connection.execute(text("DELETE FROM alembic_version WHERE version_num = '06ff69aef760'"))
    print("Invalid revision ID deleted successfully.")
except Exception as e:
    print(f"An error occurred: {e}")
