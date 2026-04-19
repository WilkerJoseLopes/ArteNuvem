import os
from dotenv import load_dotenv

load_dotenv()


def _get_database_uri():
    """
    Usa a base de dados PostgreSQL do Supabase/Render.
    Se não houver DATABASE_URL, mantém fallback local para desenvolvimento.
    """
    db_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
    if db_url:
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        if db_url.startswith("postgresql://") and "sslmode=" not in db_url:
            sep = "&" if "?" in db_url else "?"
            db_url = f"{db_url}{sep}sslmode=require"

        return db_url

    return "sqlite:///local.db"


def _get_engine_options(database_uri: str):
    if database_uri.startswith("postgresql://"):
        return {
            "pool_pre_ping": True,
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "300")),
        }
    return {}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = _get_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _get_engine_options(SQLALCHEMY_DATABASE_URI)
