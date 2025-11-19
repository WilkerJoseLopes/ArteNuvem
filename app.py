from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from config import Config
from models import db, Utilizador, Categoria, Imagem, Comentario, Reacao, Exposicao, Voto
from datetime import datetime
import os
import cloudconvert
from werkzeug.utils import secure_filename  # <- IMPORT NECESSÁRIO

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

# 🔥 cria as tabelas logo ao arrancar (tanto local como no Render / PostgreSQL)
with app.app_context():
    db.create_all()

# Config CloudConvert (se a API key não existir, a rota de PDF vai verificar)
cloudconvert.configure(api_key=app.config["CLOUDCONVERT_API_KEY"])

# Pasta local para guardar uploads (em Render é efémero, mas serve para demo)
UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# -------------------------
#   SIMULA LOGIN (demo)
#   Em tese aqui entraria GoogleAuth
# -------------------------
@app.before_request
def fake_login():
    # Para simplificar o vosso trabalho, vamos assumir que há sempre um utilizador aluno logado
    # Numa app real, isto seria sessão + GoogleAuth
    user = Utilizador.query.filter_by(email="aluno@exemplo.com").first()
    if not user:
        user = Utilizador(
            nome="Aluno Exemplo",
            email="aluno@exemplo.com",
            tipo_utilizador="Aluno"
        )
        db.session.add(user)
        db.session.commit()
    # guardar em g se quisesses, mas para simplificar só usamos query no momento


# -------------------------
#   ROTAS
# -------------------------

@app.route("/")
def index():
    categoria_id = request.args.get("categoria")
    query = Imagem.query.order_by(Imagem.data_upload.desc())
    if categoria_id:
        query = query.filter_by(id_categoria=categoria_id)

    imagens = query.all()
    categorias = Categoria.query.all()
    return render_template("index.html", imagens=imagens, categorias=categorias)


@app.route("/imagem/<int:imagem_id>")
def imagem_detalhe(imagem_id):
    img = Imagem.query.get_or_404(imagem_id)
    comentarios = Comentario.query.filter_by(id_imagem=imagem_id).order_by(Comentario.data.desc()).all()
    reacoes = Reacao.query.filter_by(id_imagem=imagem_id).all()
    likes = len([r for r in reacoes if r.tipo == "like"])
    return render_template("imagem_detalhe.html", imagem=img, comentarios=comentarios, likes=likes)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        ficheiro = request.files.get("ficheiro")
        titulo = request.form.get("titulo")
        categoria_id = request.form.get("categoria")

        if not ficheiro or ficheiro.filename == "":
            flash("Selecione um ficheiro.", "error")
            return redirect(request.url)

        if not allowed_file(ficheiro.filename):
            flash("Apenas ficheiros JPG/PNG.", "error")
            return redirect(request.url)

        if not titulo:
            flash("Título é obrigatório.", "error")
            return redirect(request.url)

        filename = secure_filename(ficheiro.filename)
        caminho_local = os.path.join(UPLOAD_FOLDER, filename)
        ficheiro.save(caminho_local)

        # Na SRS isto seria Azure Media Services; aqui é URL local
        caminho_url = "/" + caminho_local.replace("\\", "/")

        autor = Utilizador.query.filter_by(email="aluno@exemplo.com").first()

        img = Imagem(
            titulo=titulo,
            caminho_armazenamento=caminho_url,
            id_utilizador=autor.id,
            id_categoria=int(categoria_id) if categoria_id else None
        )
        db.session.add(img)
        db.session.commit()

        flash("Publicado com sucesso!", "success")
        return redirect(url_for("index"))

    categorias = Categoria.query.all()
    return render_template("upload.html", categorias=categorias)


@app.route("/comentario", methods=["POST"])
def comentario():
    texto = request.form.get("texto")
    imagem_id = request.form.get("imagem_id")

    if not texto or len(texto) > 140:
        flash("Comentário inválido ou demasiado longo (máx. 140).", "error")
        return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))

    user = Utilizador.query.filter_by(email="aluno@exemplo.com").first()

    c = Comentario(
        texto=texto,
        id_imagem=imagem_id,
        id_utilizador=user.id if user else None
    )
    db.session.add(c)
    db.session.commit()

    return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))


@app.route("/reacao", methods=["POST"])
def reacao():
    tipo = request.form.get("tipo")  # like/emoji
    imagem_id = request.form.get("imagem_id")

    user = Utilizador.query.filter_by(email="aluno@exemplo.com").first()

    r = Reacao(
        tipo=tipo,
        id_imagem=imagem_id,
        id_utilizador=user.id if user else None
    )
    db.session.add(r)
    db.session.commit()

    return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))


@app.route("/exposicao")
def exposicao():
    # Top 10 imagens por número de votos
    # Aqui simplificamos: contamos o número de votos por imagem
    top = (
        db.session.query(Imagem, db.func.count(Voto.id).label("total_votos"))
        .outerjoin(Voto, Voto.id_imagem == Imagem.id)
        .group_by(Imagem.id)
        .order_by(db.desc("total_votos"))
        .limit(10)
        .all()
    )
    return render_template("exposicao.html", top=top)


# -------------------------
#   ADMIN (simples)
# -------------------------

@app.route("/admin/categorias", methods=["GET", "POST"])
def admin_categorias():
    # Não estou a fazer autenticação forte, mas no relatório vocês dizem
    # que isto seria protegido por tipo_utilizador == 'Admin'
    if request.method == "POST":
        nome = request.form.get("nome")
        if nome:
            c = Categoria(nome=nome)
            db.session.add(c)
            db.session.commit()
    categorias = Categoria.query.all()
    return render_template("admin_categorias.html", categorias=categorias)


@app.route("/admin/exposicoes", methods=["GET", "POST"])
def admin_exposicoes():
    if request.method == "POST":
        nome = request.form.get("nome")
        mes = request.form.get("mes")
        if nome and mes:
            e = Exposicao(nome=nome, mes=mes)
            db.session.add(e)
            db.session.commit()
    exposicoes = Exposicao.query.all()
    return render_template("admin_exposicoes.html", exposicoes=exposicoes)


# -------------------------
#   GERAR PDF (CloudConvert)
# -------------------------

@app.route("/pdf/<tipo>")
def gerar_pdf(tipo):
    """
    tipo = 'certificado' ou 'catalogo'
    Aqui fazemos um exemplo simples: gerar PDF com HTML básico.
    Numa versão mais avançada, apontavas para uma página HTML hosted.
    """
    if tipo not in ["certificado", "catalogo"]:
        return "Tipo inválido", 400

    if not app.config["CLOUDCONVERT_API_KEY"]:
        # evita crash se não tiver API key no Render
        return jsonify({"error": "CLOUDCONVERT_API_KEY não configurada"}), 500

    # Exemplo: gerar um HTML dinâmico
    if tipo == "certificado":
        user = Utilizador.query.filter_by(email="aluno@exemplo.com").first()
        nome = user.nome if user else "Participante"
        html_content = f"""
        <html><body>
        <h1>Certificado de Participação</h1>
        <p>Certificamos que <strong>{nome}</strong> participou na plataforma ArteNuvem.</p>
        <p>Data: {datetime.utcnow().strftime('%d/%m/%Y')}</p>
        </body></html>
        """
    else:  # catalogo da exposição
        imagens = (
            db.session.query(Imagem)
            .join(Voto, isouter=True)
            .group_by(Imagem.id)
            .all()
        )
        html_items = "".join(
            f"<li>{img.titulo} - Autor ID {img.id_utilizador}</li>" for img in imagens
        )
        html_content = f"""
        <html><body>
        <h1>Catálogo da Exposição</h1>
        <ul>{html_items}</ul>
        </body></html>
        """

    # CloudConvert job - import raw HTML e converter para PDF
    job = cloudconvert.Job.create(payload={
        "tasks": {
            "import-html": {
                "operation": "import/raw",
                "content": html_content,
                "filename": f"{tipo}.html"
            },
            "convert": {
                "operation": "convert",
                "input": "import-html",
                "output_format": "pdf"
            },
            "export-url": {
                "operation": "export/url",
                "input": "convert"
            }
        }
    })

    job = cloudconvert.Job.find(id=job["id"])
    export_task = [t for t in job["tasks"] if t["name"] == "export-url"][0]
    file_info = export_task.get("result", {}).get("files", [])[0]
    download_url = file_info["url"]

    # Para simplificar, devolvo só o link:
    return jsonify({"pdf_url": download_url})


# -------------------------
#   MAIN (uso local)
# -------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
