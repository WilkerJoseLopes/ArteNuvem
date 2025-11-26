from datetime import datetime
import os
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from config import Config
from models import db, Utilizador, Categoria, Imagem, Comentario, Reacao, Exposicao, Voto

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

with app.app_context():
    db.create_all()
    default = ["Todos", "Fotos", "Desenhos", "Outro"]
    for nome in default:
        if not Categoria.query.filter_by(nome=nome).first():
            db.session.add(Categoria(nome=nome))
    db.session.commit()

UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

TEMP_FOLDER = "temp"
PDF_FOLDER = os.path.join("static", "pdf")
os.makedirs(TEMP_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.before_request
def fake_login():
    user = Utilizador.query.filter_by(email="aluno@exemplo.com").first()
    if not user:
        user = Utilizador(nome="Aluno Exemplo", email="aluno@exemplo.com", tipo_utilizador="Aluno")
        db.session.add(user)
        db.session.commit()


@app.route("/")
def index():
    q = request.args.get("q", "", type=str).strip()
    categoria_id = request.args.get("categoria", type=int)

    fotos_cat = Categoria.query.filter_by(nome="Fotos").first()
    fotos = []
    if fotos_cat:
        fotos = Imagem.query.filter_by(id_categoria=fotos_cat.id).order_by(Imagem.data_upload.desc()).all()

    query = Imagem.query
    if categoria_id:
        query = query.filter_by(id_categoria=categoria_id)
    if q:
        like = f"%{q}%"
        query = query.filter((Imagem.titulo.ilike(like)) | (Imagem.categoria_texto.ilike(like)))

    imagens = query.order_by(Imagem.data_upload.desc()).all()
    categorias = Categoria.query.all()
    other_cats = [c for c in categorias if c.nome != "Fotos"]

    return render_template(
        "index.html",
        fotos=fotos,
        imagens=imagens,
        categorias=categorias,
        other_cats=other_cats,
        query_text=q,
        selected_categoria=categoria_id,
    )


@app.route("/imagem/<int:imagem_id>")
def imagem_detalhe(imagem_id: int):
    img = Imagem.query.get_or_404(imagem_id)
    comentarios = Comentario.query.filter_by(id_imagem=imagem_id).order_by(Comentario.data.desc()).all()
    reacoes = Reacao.query.filter_by(id_imagem=imagem_id).all()
    likes = len([r for r in reacoes if r.tipo == "like"])
    return render_template("imagem.html", imagem=img, comentarios=comentarios, likes=likes)


@app.route("/publicar", methods=["GET", "POST"])
def publicar():
    if request.method == "POST":
        ficheiro = request.files.get("ficheiro")
        titulo = request.form.get("titulo")
        categoria_id = request.form.get("categoria", type=int)
        tags = request.form.get("tags", "")

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
        caminho_url = "/" + caminho_local.replace("\\", "/")

        autor = Utilizador.query.filter_by(email="aluno@exemplo.com").first()
        categoria_obj = Categoria.query.get(categoria_id) if categoria_id else None

        img = Imagem(
            titulo=titulo,
            caminho_armazenamento=caminho_url,
            categoria_texto=categoria_obj.nome if categoria_obj else None,
            id_utilizador=autor.id,
            id_categoria=categoria_id if categoria_id else None,
        )
        if tags:
            img.tags = tags

        db.session.add(img)
        db.session.commit()
        flash("Publicado com sucesso!", "success")
        return redirect(url_for("index"))

    categorias = Categoria.query.all()
    return render_template("upload.html", categorias=categorias)


@app.route("/comentario", methods=["POST"])
def comentario():
    texto = request.form.get("texto")
    imagem_id = request.form.get("imagem_id", type=int)

    if not texto or len(texto) > 140:
        flash("Comentário inválido ou demasiado longo (máx. 140).", "error")
        return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))

    user = Utilizador.query.filter_by(email="aluno@exemplo.com").first()

    c = Comentario(texto=texto, id_imagem=imagem_id, id_utilizador=user.id if user else None)
    db.session.add(c)
    db.session.commit()

    return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))


@app.route("/reacao", methods=["POST"])
def reacao():
    tipo = request.form.get("tipo")
    imagem_id = request.form.get("imagem_id", type=int)

    if not tipo or not imagem_id:
        return redirect(url_for("index"))

    user = Utilizador.query.filter_by(email="aluno@exemplo.com").first()

    r = Reacao(tipo=tipo, id_imagem=imagem_id, id_utilizador=user.id if user else None)
    db.session.add(r)
    db.session.commit()

    return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))


@app.route("/exposicao")
def exposicao():
    top = (
        db.session.query(Imagem, db.func.count(Voto.id).label("total_votos"))
        .outerjoin(Voto, Voto.id_imagem == Imagem.id)
        .group_by(Imagem.id)
        .order_by(db.desc("total_votos"))
        .limit(10)
        .all()
    )
    return render_template("exposicao.html", top=top)


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        tipo_form = request.form.get("tipo_form")
        if tipo_form == "categoria":
            nome = request.form.get("nome")
            if nome:
                c = Categoria(nome=nome)
                db.session.add(c)
                db.session.commit()
                flash("Categoria criada.", "success")
        elif tipo_form == "exposicao":
            nome = request.form.get("nome")
            mes = request.form.get("mes")
            if nome and mes:
                e = Exposicao(nome=nome, mes=mes)
                db.session.add(e)
                db.session.commit()
                flash("Exposição criada.", "success")

    categorias = Categoria.query.all()
    exposicoes = Exposicao.query.all()
    return render_template("admin.html", categorias=categorias, exposicoes=exposicoes)


@app.route("/certificado/<int:user_id>")
def gerar_certificado(user_id):
    user = Utilizador.query.get_or_404(user_id)

    html_content = render_template("certificado.html", user=user)
    html_path = os.path.join(TEMP_FOLDER, f"certificado_{user.id}.html")
    pdf_path = os.path.join(PDF_FOLDER, f"certificado_{user.id}.pdf")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    from cloudconvert_service import html_para_pdf
    html_para_pdf(html_path, pdf_path)

    return redirect("/static/pdf/certificado_" + str(user.id) + ".pdf")


@app.route("/catalogo")
def gerar_catalogo():
    top_imagens = Imagem.query.order_by(Imagem.data_upload.desc()).limit(20).all()

    html_content = render_template("catalogo.html", imagens=top_imagens)
    html_path = os.path.join(TEMP_FOLDER, "catalogo.html")
    pdf_path = os.path.join(PDF_FOLDER, "catalogo.pdf")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    from cloudconvert_service import html_para_pdf
    html_para_pdf(html_path, pdf_path)

    return redirect("/static/pdf/catalogo.pdf")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
