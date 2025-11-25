class Imagem(db.Model):
    __tablename__ = "imagem"
    id = db.Column("ID_Imagem", db.Integer, primary_key=True)
    titulo = db.Column("Titulo", db.String(150), nullable=False)
    categoria_texto = db.Column("Categoria", db.String(80))
    caminho_armazenamento = db.Column("Caminho_Armazenamento", db.String(500), nullable=False)
    data_upload = db.Column("Data_Upload", db.DateTime, default=datetime.utcnow)
    id_utilizador = db.Column("ID_Utilizador", db.Integer, db.ForeignKey("utilizador.ID_Utilizador"), nullable=False)
    id_categoria = db.Column("ID_Categoria", db.Integer, db.ForeignKey("categoria.ID_Categoria"), nullable=True)
    tags = db.Column("Tags", db.String(300), nullable=True)
