# :contentReference[oaicite:0]{index=0}
from datetime import datetime
import os
import threading
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)
from werkzeug.utils import secure_filename
from sqlalchemy import func, desc

from config import Config
from models import db, Utilizador, Categoria, Imagem, Comentario, Reacao, Exposicao, Voto

from authlib.integrations.flask_client import OAuth

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

# OAuth / Google
oauth = OAuth(app)

google = oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# Folders
UPLOAD_FOLDER = os.path.join("static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

TEMP_FOLDER = "temp"
PDF_FOLDER = os.path.join("static", "pdf")
os.makedirs(TEMP_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def current_user():
    uid = session.get("user_id")
    if uid:
        return Utilizador.query.get(uid)
    return None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


# Ensure tables and default categories are created once on first requests.
_tables_lock = threading.Lock()


@app.before_request
def ensure_tables():
    if app.config.get("TABLES_INITIALIZED"):
        return

    with _tables_lock:
        if app.config.get("TABLES_INITIALIZED"):
            return
        # Use app_context to be safe when called from before_request
        with app.app_context():
            db.create_all()
            default = ["Todos", "Fotos", "Desenhos", "Outro"]
            for nome in default:
                if not Categoria.query.filter_by(nome=nome).first():
                    db.session.add(Categoria(nome=nome))
            db.session.commit()
        app.config["TABLES_INITIALIZED"] = True


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
        query = query.filter(
            (Imagem.titulo.ilike(like)) |
            (Imagem.categoria_texto.ilike(like)) |
            (Imagem.tags.ilike(like))
        )

    imagens = query.order_by(Imagem.data_upload.desc()).all()
    categorias = Categoria.query.all()

    return render_template(
        "index.html",
        fotos=fotos,
        imagens=imagens,
        categorias=categorias,
        query_text=q,
        selected_categoria=categoria_id,
    )


@app.route("/imagem/<int:imagem_id>")
def imagem_detalhe(imagem_id: int):
    img = Imagem.query.get_or_404(imagem_id)
    comentarios = Comentario.query.filter_by(id_imagem=imagem_id).order_by(Comentario.data.desc()).all()
    reacoes = Reacao.query.filter_by(id_imagem=imagem_id).all()
    likes = len([r for r in reacoes if r.tipo == "like"])
    categorias = Categoria.query.all()
    return render_template(
        "imagem.html",
        imagem=img,
        comentarios=comentarios,
        likes=likes,
        categorias=categorias,
        query_text="",
        selected_categoria=None,
    )


@app.route("/publicar", methods=["GET", "POST"])
@login_required
def publicar():
    user = current_user()
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
        # Evita sobrescrever ficheiros com o mesmo nome
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        filename = f"{timestamp}_{filename}"
        caminho_local = os.path.join(UPLOAD_FOLDER, filename)
        ficheiro.save(caminho_local)
        caminho_url = "/" + caminho_local.replace("\\", "/")

        categoria_obj = Categoria.query.get(categoria_id) if categoria_id else None

        img = Imagem(
            titulo=titulo,
            caminho_armazenamento=caminho_url,
            categoria_texto=categoria_obj.nome if categoria_obj else None,
            id_utilizador=user.id,
            id_categoria=categoria_id if categoria_id else None,
        )
        if tags:
            img.tags = tags

        db.session.add(img)
        db.session.commit()
        flash("Publicado com sucesso!", "success")
        return redirect(url_for("index"))

    categorias = Categoria.query.all()
    return render_template("upload.html", categorias=categorias, query_text="", selected_categoria=None)


@app.route("/apagar_imagem/<int:imagem_id>", methods=["POST"])
@login_required
def apagar_imagem(imagem_id: int):
    user = current_user()
    img = Imagem.query.get_or_404(imagem_id)

    # autorização: dono da imagem ou admin
    if not (user.id == img.id_utilizador or (user.email and user.email == ADMIN_EMAIL)):
        flash("Não tens permissão para apagar esta imagem.", "error")
        return redirect(url_for("index"))

    # Apaga comentários, reações e votos relacionados
    Comentario.query.filter_by(id_imagem=imagem_id).delete()
    Reacao.query.filter_by(id_imagem=imagem_id).delete()
    Voto.query.filter_by(id_imagem=imagem_id).delete()

    caminho_relativo = img.caminho_armazenamento.lstrip("/")
    caminho_ficheiro = os.path.join(app.root_path, caminho_relativo)

    db.session.delete(img)
    db.session.commit()

    try:
        os.remove(caminho_ficheiro)
    except FileNotFoundError:
        pass

    flash("Imagem apagada.", "success")
    return redirect(url_for("index"))


@app.route("/comentario", methods=["POST"])
@login_required
def comentario():
    user = current_user()
    texto = request.form.get("texto")
    imagem_id = request.form.get("imagem_id", type=int)

    if not texto or len(texto) > 140:
        flash("Comentário inválido ou demasiado longo (máx. 140).", "error")
        return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))

    c = Comentario(texto=texto, id_imagem=imagem_id, id_utilizador=user.id if user else None)
    db.session.add(c)
    db.session.commit()

    return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))


@app.route("/reacao", methods=["POST"])
@login_required
def reacao():
    user = current_user()
    tipo = request.form.get("tipo")
    imagem_id = request.form.get("imagem_id", type=int)

    if not tipo or not imagem_id:
        return redirect(url_for("index"))

    r = Reacao(tipo=tipo, id_imagem=imagem_id, id_utilizador=user.id if user else None)
    db.session.add(r)
    db.session.commit()

    return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))


@app.route("/exposicao")
def exposicao():
    exposicoes = Exposicao.query.order_by(Exposicao.id.desc()).all()
    categorias = Categoria.query.all()
    return render_template(
        "exposição.html",
        exposicoes=exposicoes,
        categorias=categorias,
        query_text="",
        selected_categoria=None,
    )


@app.route("/admin", methods=["GET", "POST"])
def admin():
    user = current_user()
    if not user or user.email != ADMIN_EMAIL:
        flash("Acesso restrito. Apenas o administrador pode aceder a esta secção.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create_categoria":
            nome = request.form.get("nome")
            if nome:
                c = Categoria(nome=nome)
                db.session.add(c)
                db.session.commit()
                flash("Categoria criada.", "success")

        elif action == "create_exposicao":
            nome = request.form.get("nome")
            mes = request.form.get("mes")
            if nome and mes:
                e = Exposicao(nome=nome, mes=mes)
                db.session.add(e)
                db.session.commit()
                flash("Exposição criada.", "success")

        elif action == "update_exposicao":
            exposicao_id = request.form.get("exposicao_id", type=int)
            e = Exposicao.query.get(exposicao_id)
            if e:
                novo_nome = request.form.get("nome") or e.nome
                novo_mes = request.form.get("mes") or e.mes
                e.nome = novo_nome
                e.mes = novo_mes
                db.session.commit()
                flash("Exposição atualizada.", "success")

        elif action == "delete_exposicao":
            exposicao_id = request.form.get("exposicao_id", type=int)
            e = Exposicao.query.get(exposicao_id)
            if e:
                db.session.delete(e)
                db.session.commit()
                flash("Exposição apagada.", "success")

    categorias = Categoria.query.all()
    exposicoes = Exposicao.query.all()
    return render_template(
        "admin.html",
        categorias=categorias,
        exposicoes=exposicoes,
        query_text="",
        selected_categoria=None,
    )


@app.route("/exportar_exposicao", methods=["GET", "POST"])
def exportar_exposicao():
    exposicoes = Exposicao.query.all()
    categorias = Categoria.query.all()
    pdf_url = None
    exposicao_selecionada = None
    top = []

    if request.method == "POST":
        exposicao_id = request.form.get("exposicao_id", type=int)
        if exposicao_id:
            exposicao_selecionada = Exposicao.query.get(exposicao_id)
            if exposicao_selecionada:
                top = (
                    db.session.query(Imagem, func.count(Voto.id).label("total_votos"))
                    .join(Voto, Voto.id_imagem == Imagem.id)
                    .filter(Voto.id_exposicao == exposicao_id)
                    .group_by(Imagem.id)
                    .order_by(desc("total_votos"))
                    .limit(10)
                    .all()
                )

                from cloudconvert_service import html_para_pdf

                html_content = render_template(
                    "catalogo.html",
                    exposicao=exposicao_selecionada,
                    top=top
                )
                html_path = os.path.join(TEMP_FOLDER, f"catalogo_exposicao_{exposicao_id}.html")
                pdf_path = os.path.join(PDF_FOLDER, f"catalogo_exposicao_{exposicao_id}.pdf")

                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)

                html_para_pdf(html_path, pdf_path)
                pdf_url = f"/static/pdf/catalogo_exposicao_{exposicao_id}.pdf"

    return render_template(
        "exportar_exposicao.html",
        exposicoes=exposicoes,
        pdf_url=pdf_url,
        exposicao=exposicao_selecionada,
        top=top,
        categorias=categorias,
        query_text="",
        selected_categoria=None,
    )


@app.route("/catalogo")
def gerar_catalogo():
    imagens = Imagem.query.order_by(Imagem.data_upload.desc()).limit(20).all()

    from cloudconvert_service import html_para_pdf

    html_content = render_template("catalogo.html", imagens=imagens, exposicao=None)
    html_path = os.path.join(TEMP_FOLDER, "catalogo.html")
    pdf_path = os.path.join(PDF_FOLDER, "catalogo.pdf")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    html_para_pdf(html_path, pdf_path)

    return redirect("/static/pdf/catalogo.pdf")


@app.route("/certificado/<int:user_id>")
@login_required
def gerar_certificado(user_id):
    # apenas users logados (ou admin) podem gerar certificado para si ou admin para outro
    requester = current_user()
    if not requester:
        return redirect(url_for("login"))

    # permitir só para o próprio user ou admin
    if requester.id != user_id and (requester.email != ADMIN_EMAIL):
        flash("Não tens permissão para gerar este certificado.", "error")
        return redirect(url_for("index"))

    user = Utilizador.query.get_or_404(user_id)

    html_content = render_template("certificado.html", user=user)
    html_path = os.path.join(TEMP_FOLDER, f"certificado_{user.id}.html")
    pdf_path = os.path.join(PDF_FOLDER, f"certificado_{user.id}.pdf")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # usar cloudconvert_service (assume que existe e está configurado)
    try:
        from cloudconvert_service import html_para_pdf
        html_para_pdf(html_path, pdf_path)
    except Exception:
        # fallback simples: gravar HTML e não converter se o serviço falhar
        flash("Geração de PDF falhou (CloudConvert). HTML guardado temporariamente.", "error")

    return redirect("/" + pdf_path)


@app.route("/login")
def login():
    redirect_uri = url_for("google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route("/login/google/callback")
def google_callback():
    # Tenta obter token e userinfo de forma robusta
    token = google.authorize_access_token()
    user_info = {}

    # 1) Tentar endpoint /userinfo
    try:
        resp = google.get("userinfo")
        if resp and resp.ok:
            user_info = resp.json()
    except Exception:
        user_info = {}

    # 2) fallback para id_token parsing
    if not user_info:
        try:
            user_info = google.parse_id_token(token)
        except Exception:
            user_info = token.get("userinfo") or token.get("id_token") or {}

    email = user_info.get("email")
    if not email:
        flash("Erro ao obter email do Google. Tenta de novo.", "error")
        return redirect(url_for("index"))

    nome = user_info.get("name", email)
    foto = user_info.get("picture")
    google_id = user_info.get("sub")

    user = Utilizador.query.filter_by(email=email).first()

    if not user:
        user = Utilizador(
            google_id=google_id,
            nome=nome,
            email=email,
            foto_url=foto,
        )
        db.session.add(user)
        db.session.commit()

    session["user_id"] = user.id
    session["user_email"] = user.email

    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    # Nota: em produção, gunicorn vai usar o app. Este run é apenas para testes locais.
    app.run(debug=True)

