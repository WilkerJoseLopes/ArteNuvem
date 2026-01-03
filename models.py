from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Utilizador(db.Model):
    __tablename__ = "utilizador"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Utilizador", db.Integer, primary_key=True)
    google_id = db.Column("Google_ID", db.String(200), unique=True, nullable=True)

    nome = db.Column("Nome", db.String(150), nullable=False)
    email = db.Column("Email", db.String(150), unique=True, nullable=False)
    foto_url = db.Column("Foto_URL", db.String(300), nullable=True)

    tipo_utilizador = db.Column("Tipo_Utilizador", db.String(50), default="Aluno")

    imagens = db.relationship("Imagem", backref="autor", lazy=True)



class Categoria(db.Model):
    __tablename__ = "categoria"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Categoria", db.Integer, primary_key=True)
    nome = db.Column("Nome", db.String(100), nullable=False, unique=True)

    imagens = db.relationship("Imagem", backref="categoria_obj", lazy=True)


class Imagem(db.Model):
    __tablename__ = "imagem"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Imagem", db.Integer, primary_key=True)
    titulo = db.Column("Titulo", db.String(150), nullable=False)
    categoria_texto = db.Column("Categoria", db.String(80))
    caminho_armazenamento = db.Column("Caminho_Armazenamento", db.String(500), nullable=False)
    data_upload = db.Column("Data_Upload", db.DateTime, default=datetime.utcnow)

    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=False)
    id_categoria = db.Column("ID_Categoria", db.Integer, db.ForeignKey("categoria.ID_Categoria"), nullable=True)
    tags = db.Column("Tags", db.String(300), nullable=True)


class Comentario(db.Model):
    __tablename__ = "comentario"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Comentario", db.Integer, primary_key=True)
    texto = db.Column("Texto", db.String(250), nullable=False)
    data = db.Column("Data", db.DateTime, default=datetime.utcnow)

    id_imagem = db.Column("ID_Imagem", db.Integer, db.ForeignKey("imagem.ID_Imagem"), nullable=False)
    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=True)

    # mapeamos explicitamente o nome da coluna na BD e referimos a PK correcta da tabela "comentario"
    id_comentario_pai = db.Column("ID_Comentario_Pai", db.Integer, db.ForeignKey("comentario.ID_Comentario"), nullable=True)




class Reacao(db.Model):
    __tablename__ = "reacao"
    __table_args__ = (
        db.UniqueConstraint("Tipo", "ID_Imagem", "ID_Utilizador", name="unique_reacao_por_utilizador"),
        {'extend_existing': True}
    )

    id = db.Column("ID_Reacao", db.Integer, primary_key=True)
    tipo = db.Column("Tipo", db.String(20), nullable=False)  # ex: 'like'
    id_imagem = db.Column("ID_Imagem", db.Integer, db.ForeignKey("imagem.ID_Imagem"), nullable=False)
    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=False)



class Exposicao(db.Model):
    __tablename__ = "exposicao"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Exposicao", db.Integer, primary_key=True)
    nome = db.Column("Nome", db.String(150), nullable=False)
    mes = db.Column("Mes", db.String(20), nullable=False)
    imagem_destaque = db.Column("Imagem_Destaque", db.String(500), nullable=True)
    ativo = db.Column("Ativo", db.Boolean, default=True)
    usar_tags = db.Column("Usar_Tags", db.Boolean, default=False)
    usar_categorias = db.Column("Usar_Categorias", db.Boolean, default=True)
    tags_filtro = db.Column("Tags_Filtro", db.String(300), nullable=True)
    categorias_ids = db.Column("Categorias_Ids", db.String(300), nullable=True)



class Voto(db.Model):
    __tablename__ = "voto"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Voto", db.Integer, primary_key=True)
    id_imagem = db.Column("ID_Imagem", db.Integer, db.ForeignKey("imagem.ID_Imagem"), nullable=False)
    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=False)
    id_exposicao = db.Column("ID_Exposicao", db.Integer, db.ForeignKey("exposicao.ID_Exposicao"), nullable=False)
    data = db.Column("Data", db.DateTime, default=datetime.utcnow)
