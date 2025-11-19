# config.py
import os
from dotenv import load_dotenv

# Carrega variáveis de ambiente do .env (em local)
load_dotenv()

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///local.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    CLOUDCONVERT_API_KEY = os.getenv("CLOUDCONVERT_API_KEY", "CHAVE_AQUI")
