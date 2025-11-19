# models.py
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Utilizador(db.Model):
    __tablename__ = "utilizador"

    id = db.Column("ID_Utilizador", db.Integer, primary_key=True)
    nome = db.Column("Nome", db.String(150), nullable=False)
    email = db.Column("Email", db.String(150), unique=True, nullable=False)
    palavra_passe = db.Column("Palavra_Passe", db.String(255))  # se usassem password normal
    tipo_utilizador = db.Column("Tipo_Utilizador", db.String(50), default="Aluno")

    imagens = db.relationship("Imagem", backref="autor", lazy=True)

class Categoria(db.Model):
    __tablename__ = "categoria"

    id = db.Column("ID_Categoria", db.Integer, primary_key=True)
    nome = db.Column("Nome", db.String(100), nullable=False, unique=True)

    imagens = db.relationship("Imagem", backref="categoria_obj", lazy=True)

class Imagem(db.Model):
    __tablename__ = "imagem"

    id = db.Column("ID_Imagem", db.Integer, primary_key=True)
    titulo = db.Column("Titulo", db.String(150), nullable=False)
    caminho_armazenamento = db.Column("Caminho_Armazenamento", db.String(500), nullable=False)
    data_upload = db.Column("Data_Upload", db.DateTime, default=datetime.utcnow)

    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=False)
    id_categoria = db.Column("ID_Categoria", db.Integer, db.ForeignKey("categoria.ID_Categoria"), nullable=True)

class Comentario(db.Model):
    __tablename__ = "comentario"

    id = db.Column("ID_Comentario", db.Integer, primary_key=True)
    texto = db.Column("Texto", db.String(250), nullable=False)
    data = db.Column("Data", db.DateTime, default=datetime.utcnow)

    id_imagem = db.Column("ID_Imagem", db.Integer, db.ForeignKey("imagem.ID_Imagem"), nullable=False)
    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=True)

class Reacao(db.Model):
    __tablename__ = "reacao"

    id = db.Column("ID_Reacao", db.Integer, primary_key=True)
    tipo = db.Column("Tipo", db.String(50), nullable=False)

    id_imagem = db.Column("ID_Imagem", db.Integer, db.ForeignKey("imagem.ID_Imagem"), nullable=False)
    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=True)

class Exposicao(db.Model):
    __tablename__ = "exposicao"

    id = db.Column("ID_Exposicao", db.Integer, primary_key=True)
    nome = db.Column("Nome", db.String(150), nullable=False)
    mes = db.Column("Mes", db.String(20), nullable=False)
    imagem_destaque = db.Column("Imagem_Destaque", db.String(500), nullable=True)

class Voto(db.Model):
    __tablename__ = "voto"

    id = db.Column("ID_Voto", db.Integer, primary_key=True)
    id_imagem = db.Column("ID_Imagem", db.Integer, db.ForeignKey("imagem.ID_Imagem"), nullable=False)
    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=False)
    id_exposicao = db.Column("ID_Exposicao", db.Integer, db.ForeignKey("exposicao.ID_Exposicao"), nullable=False)
    data = db.Column("Data", db.DateTime, default=datetime.utcnow)
