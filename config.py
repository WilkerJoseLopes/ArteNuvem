import os
from dotenv import load_dotenv

load_dotenv()


def _get_database_uri():
    """Usa DATABASE_URL (Render/Internal DB). Se não houver, usa SQLite local."""
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        return db_url

    # fallback para desenvolvimento local
    return "sqlite:///local.db"


class Config:
    SQLALCHEMY_DATABASE_URI = _get_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
