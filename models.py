from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

imagem_exposicao = db.Table(
    "imagem_exposicao",
    db.Column("ID_Imagem", db.Integer, db.ForeignKey("imagem.ID_Imagem"), primary_key=True),
    db.Column("ID_Exposicao", db.Integer, db.ForeignKey("exposicao.ID_Exposicao"), primary_key=True)
)

class Utilizador(db.Model):
    __tablename__ = "utilizador"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Utilizador", db.Integer, primary_key=True)
    google_id = db.Column("Google_ID", db.String(200), unique=True, nullable=True)
    nome = db.Column("Nome", db.String(150), nullable=False)
    email = db.Column("Email", db.String(150), unique=True, nullable=False)
    foto_url = db.Column("Foto_URL", db.String(300), nullable=True)
    notifications_paused_until = db.Column("notificationspauseduntil", db.DateTime, nullable=True)

    imagens = db.relationship("Imagem", backref="autor", lazy=True)

class Categoria(db.Model):
    __tablename__ = "categoria"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Categoria", db.Integer, primary_key=True)
    nome = db.Column("Nome", db.String(100), nullable=False, unique=True)
    imagens = db.relationship("Imagem", backref="categoria_obj", lazy=True)

class Localizacao(db.Model):
    __tablename__ = "localizacao"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Location", db.Integer, primary_key=True)
    address = db.Column("Address", db.String(500), nullable=False)
    city = db.Column("City", db.String(150), nullable=True)
    country = db.Column("Country", db.String(150), nullable=True)
    latitude = db.Column("Latitude", db.Float, nullable=True)
    longitude = db.Column("Longitude", db.Float, nullable=True)
    google_place_id = db.Column("Google_Place_ID", db.String(300), unique=True, nullable=True)
    created_at = db.Column("CreatedAt", db.DateTime, default=datetime.utcnow, nullable=False)

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
    descricao = db.Column("Descricao", db.String(500), nullable=True)
    publica = db.Column("Publica", db.Boolean, default=True, nullable=False)
    id_location = db.Column("ID_Location", db.Integer, db.ForeignKey("localizacao.ID_Location"), nullable=True)
    localizacao = db.relationship("Localizacao", backref="imagens", lazy=True)
    
    exposicoes = db.relationship(
        "Exposicao",
        secondary=imagem_exposicao,
        backref=db.backref("imagens_associadas", lazy="dynamic"),
        lazy="dynamic"
    )

class Comentario(db.Model):
    __tablename__ = "comentario"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Comentario", db.Integer, primary_key=True)
    texto = db.Column("Texto", db.String(250), nullable=False)
    data = db.Column("Data", db.DateTime, default=datetime.utcnow)
    id_imagem = db.Column("ID_Imagem", db.Integer, db.ForeignKey("imagem.ID_Imagem"), nullable=False)
    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=True)
    estado_moderacao = db.Column("EstadoModeracao", db.String(20), default="aprovado", nullable=False)

class Reacao(db.Model):
    __tablename__ = "reacao"
    __table_args__ = (
        db.UniqueConstraint("Tipo", "ID_Imagem", "ID_Utilizador", name="unique_reacao_por_utilizador"),
        {'extend_existing': True}
    )

    id = db.Column("ID_Reacao", db.Integer, primary_key=True)
    tipo = db.Column("Tipo", db.String(20), nullable=False)
    id_imagem = db.Column("ID_Imagem", db.Integer, db.ForeignKey("imagem.ID_Imagem"), nullable=False)
    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=False)

class Exposicao(db.Model):
    __tablename__ = "exposicao"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Exposicao", db.Integer, primary_key=True)
    nome = db.Column("Nome", db.String(150), nullable=False)
    mes = db.Column("Mes", db.String(20), nullable=True)
    imagem_destaque = db.Column("Imagem_Destaque", db.String(500), nullable=True)
    ativo = db.Column("Ativo", db.Boolean, default=True)
    usar_tags = db.Column("Usar_Tags", db.Boolean, default=False)
    usar_categorias = db.Column("Usar_Categorias", db.Boolean, default=True)
    tags_filtro = db.Column("Tags_Filtro", db.String(300), nullable=True)
    categorias_ids = db.Column("Categorias_Ids", db.String(300), nullable=True)
    descricao = db.Column("Descricao", db.String(500), nullable=True)
    start_date = db.Column("Start_Date", db.Date, nullable=True)
    end_date = db.Column("End_Date", db.Date, nullable=True)
    mes_inteiro = db.Column("Mes_Inteiro", db.Boolean, default=False)
    categoria_id = db.Column("Categoria_ID", db.Integer, db.ForeignKey("categoria.ID_Categoria"), nullable=True)

class Notificacao(db.Model):
    __tablename__ = "notificacao"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Notification", db.Integer, primary_key=True)
    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=False)
    type = db.Column("Type", db.String(50), nullable=False)
    title = db.Column("Title", db.String(200), nullable=True)
    message = db.Column("Message", db.String(500), nullable=False)
    link_url = db.Column("Link_URL", db.String(500), nullable=True)
    is_read = db.Column("IsRead", db.Boolean, default=False, nullable=False)
    created_at = db.Column("CreatedAt", db.DateTime, default=datetime.utcnow, nullable=False)
    utilizador = db.relationship("Utilizador", backref="notificacoes_gerais", lazy=True)


class Notification(db.Model):
    __tablename__ = "notification"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Notification", db.Integer, primary_key=True)
    id_utilizador = db.Column("UserID", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=False)
    type = db.Column("Type", db.String(50), nullable=False)  # 'like' ou 'comentario'
    id_imagem = db.Column("ID_Imagem", db.Integer, db.ForeignKey("imagem.ID_Imagem"), nullable=True)
    message = db.Column("Message", db.String(500), nullable=False)
    count = db.Column("Count", db.Integer, default=1, nullable=False)
    is_read = db.Column("IsRead", db.Boolean, default=False, nullable=False)
    created_at = db.Column("CreatedAt", db.DateTime, default=datetime.utcnow, nullable=False)

    # Relacionamentos
    imagem = db.relationship("Imagem", backref="notificacoes", lazy=True)
    utilizador = db.relationship("Utilizador", backref="notificacoes", lazy=True)

class PreferenciaNotificacao(db.Model):
    __tablename__ = "preferencia_notificacao"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Preferencia", db.Integer, primary_key=True)
    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), unique=True, nullable=False)
    email_boas_vindas = db.Column("Email_Boas_Vindas", db.Boolean, default=True, nullable=False)
    email_likes = db.Column("Email_Likes", db.Boolean, default=True, nullable=False)
    email_comentarios = db.Column("Email_Comentarios", db.Boolean, default=True, nullable=False)
    email_recomendacoes = db.Column("Email_Recomendacoes", db.Boolean, default=False, nullable=False)
    email_ativo = db.Column("Email_Ativo", db.Boolean, default=True, nullable=False)
    updated_at = db.Column("UpdatedAt", db.DateTime, default=datetime.utcnow, nullable=False)
    utilizador = db.relationship("Utilizador", backref=db.backref("preferencia_notificacao", uselist=False), lazy=True)

class ResultadoModeracao(db.Model):
    __tablename__ = "resultado_moderacao"
    __table_args__ = {'extend_existing': True}

    id = db.Column("ID_Result", db.Integer, primary_key=True)
    id_comentario = db.Column("ID_Comentario", db.Integer, db.ForeignKey("comentario.ID_Comentario"), unique=True, nullable=False)
    toxicity_score = db.Column("ToxicityScore", db.Numeric, default=0, nullable=False)
    decision = db.Column("Decision", db.String(20), nullable=False)
    model_name = db.Column("ModelName", db.String(100), default="gemini-safety", nullable=False)
    processed_at = db.Column("ProcessedAt", db.DateTime, default=datetime.utcnow, nullable=False)
    motivo = db.Column("motivo", db.String(250), nullable=True)
    comentario = db.relationship("Comentario", backref=db.backref("resultado_moderacao", uselist=False), lazy=True)

