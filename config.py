import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://app_user:devpassword@localhost:5432/accel_db")
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-in-prod")