from datetime import datetime
import os
import threading
from functools import wraps
from flask import abort
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
)
from werkzeug.utils import secure_filename
from sqlalchemy import func, desc

from config import Config
from models import db, Utilizador, Categoria, Imagem, Comentario, Reacao, Exposicao, Voto

from authlib.integrations.flask_client import OAuth

from sqlalchemy import text

import traceback
from flask import make_response

from supabase import create_client
import uuid
import mimetypes

raw_admins = os.getenv("ADMIN_EMAIL", "")
# permite suportar 1 ou vários emails separados por vírgula
ADMIN_EMAILS = [e.strip().lower() for e in raw_admins.split(",") if e.strip()]


from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.config.from_object(Config)

app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

db.init_app(app)

# --- Substituir bloco de criação do cliente Supabase por este ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# normalizar URL (remove trailing slash só para garantir)
if SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.rstrip("/")

supabase = None
supabase_service = None

if not SUPABASE_URL:
    app.logger.error("SUPABASE_URL não definido. Verifica as env vars no Render.")
else:
    if SUPABASE_ANON_KEY:
        try:
            supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
            app.logger.info("Supabase (anon) client criado com sucesso.")
        except Exception as e:
            app.logger.exception("Falha ao criar supabase anon client: %s", e)
            supabase = None
    else:
        app.logger.warning("SUPABASE_ANON_KEY não definido. Cliente de leitura não será criado.")

    if SUPABASE_SERVICE_ROLE_KEY:
        try:
            supabase_service = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
            app.logger.info("Supabase (service role) client criado com sucesso.")
        except Exception as e:
            app.logger.exception("Falha ao criar supabase service client: %s", e)
            supabase_service = None
    else:
        app.logger.warning("SUPABASE_SERVICE_ROLE_KEY não definido. Uploads via server podem falhar.")
# ----------------------------------------------------------------
@app.errorhandler(500)
def internal_error(e):
    tb = traceback.format_exc()
    app.logger.error("Unhandled Exception on request: %s\n%s", request.path, tb)
    # devolve uma página simples (evita expor stacktrace ao user)
    return make_response(render_template("500.html", message=str(e)), 500)

def upload_imagem_supabase(file):
    if not supabase_service:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY não definido no ambiente — define SUPABASE_SERVICE_ROLE_KEY no Render.")

    ext = file.filename.rsplit(".", 1)[1].lower() if "." in file.filename else "bin"
    nome_unico = f"{uuid.uuid4()}.{ext}"
    content_type = mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    file.stream.seek(0)
    res = supabase_service.storage.from_("imagens").upload(nome_unico, file.stream.read(), {"content-type": content_type})
    public_url = supabase.storage.from_("imagens").get_public_url(nome_unico) if supabase else f"{SUPABASE_URL}/storage/v1/object/public/imagens/{nome_unico}"
    return public_url, nome_unico


def ensure_google_columns():
    with db.engine.begin() as conn:
        conn.execute(text('''
            ALTER TABLE utilizador
            ADD COLUMN IF NOT EXISTS "Google_ID" VARCHAR(200);
        '''))
        conn.execute(text('''
            ALTER TABLE utilizador
            ADD COLUMN IF NOT EXISTS "Foto_URL" VARCHAR(300);
        '''))
        conn.execute(text('''
            ALTER TABLE utilizador
            ADD COLUMN IF NOT EXISTS "Tipo_Utilizador" VARCHAR(50);
        '''))
        # garante a coluna pai de comentário (para threads/respostas)
        conn.execute(text('''
            ALTER TABLE comentario
            ADD COLUMN IF NOT EXISTS "ID_Comentario_Pai" INTEGER;
        '''))
        # opcional: criar FK só se não existir (Postgres não tem ADD CONSTRAINT IF NOT EXISTS em todas as versões,
        # por isso tentamos criar e ignoramos erro)
        try:
            conn.execute(text('''
                ALTER TABLE comentario
                ADD CONSTRAINT comentario_parent_fk FOREIGN KEY ("ID_Comentario_Pai") REFERENCES comentario("ID_Comentario");
            '''))
        except Exception:
            # se já existe, ignora
            pass

with app.app_context():
    ensure_google_columns()

oauth = OAuth(app)

google = oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

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

_tables_lock = threading.Lock()

raw_admins = os.getenv("ADMIN_EMAIL", "")
ADMIN_EMAILS = [e.strip().lower() for e in raw_admins.split(",") if e.strip()]
ADMIN_EMAIL = ADMIN_EMAILS[0] if ADMIN_EMAILS else None

@app.context_processor
def inject_user():
    return {"current_user": current_user(), "ADMIN_EMAILS": ADMIN_EMAILS, "ADMIN_EMAIL": ADMIN_EMAIL}



@app.before_request
def ensure_tables():
    if app.config.get("TABLES_INITIALIZED"):
        return
    with _tables_lock:
        if app.config.get("TABLES_INITIALIZED"):
            return
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
def imagem_detalhe(imagem_id):
    img = Imagem.query.get_or_404(imagem_id)

    autor = Utilizador.query.get(img.id_utilizador) if img.id_utilizador else None

    comentarios = (
        db.session.query(Comentario, Utilizador)
        .join(Utilizador, Comentario.id_utilizador == Utilizador.id)
        .filter(Comentario.id_imagem == imagem_id)
        .order_by(Comentario.data.desc())
        .all()
    )

    # total likes
    likes = Reacao.query.filter_by(id_imagem=imagem_id, tipo="like").count()

    # se houver um user logado, verifica se ele já deu like (para evitar queries no template)
    user = current_user()
    user_liked = False
    if user:
        user_liked = (
            Reacao.query.filter_by(id_imagem=imagem_id, id_utilizador=user.id, tipo="like").first()
            is not None
        )

    return render_template(
        "imagem.html",
        imagem=img,
        autor=autor,
        comentarios=comentarios,
        likes=likes,
        user_liked=user_liked
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
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        filename = f"{timestamp}_{filename}"
        caminho_url, object_key = upload_imagem_supabase(ficheiro)


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
    user_email = (user.email or "").strip().lower() if user else ""
    # permite que o dono da imagem ou admin apague
    if not user or not (user.id == img.id_utilizador or (ADMIN_EMAILS and user_email in ADMIN_EMAILS)):
        flash("Não tens permissão para apagar esta imagem.", "error")
        return redirect(url_for("index"))


    # Apagar dependências na BD
    Comentario.query.filter_by(id_imagem=imagem_id).delete()
    Reacao.query.filter_by(id_imagem=imagem_id).delete()
    Voto.query.filter_by(id_imagem=imagem_id).delete()

    # Se havia ficheiro local (caso legado), tenta remover
    try:
        caminho_relativo = (img.caminho_armazenamento or "").lstrip("/")
        caminho_ficheiro = os.path.join(app.root_path, caminho_relativo)
        if os.path.exists(caminho_ficheiro):
            try:
                os.remove(caminho_ficheiro)
            except Exception as e:
                app.logger.warning("Falha a remover ficheiro local: %s", e)
    except Exception:
        # não falha se img.caminho_armazenamento não estiver no formato local
        pass

    # Remove do BD
    db.session.delete(img)
    db.session.commit()

    # tentar apagar do Supabase também (se existir)
    try:
        if img.caminho_armazenamento and supabase_service:
            object_key = img.caminho_armazenamento.rstrip("/").split("/")[-1]
            supabase_service.storage.from_("imagens").remove([object_key])
    except Exception as e:
        app.logger.warning("Falha a remover ficheiro no Supabase: %s", e)

    flash("Imagem apagada com sucesso.", "success")
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

# fallback (mantém compatibilidade com forms antigos)
@app.route("/reacao", methods=["POST"])
@login_required
def reacao():
    tipo = request.form.get("tipo")
    imagem_id = request.form.get("imagem_id", type=int)

    if not tipo or not imagem_id:
        return redirect(url_for("index"))

    user = current_user()  # <<--- NOTE: chamada da função

    existente = Reacao.query.filter_by(
        tipo=tipo,
        id_imagem=imagem_id,
        id_utilizador=user.id
    ).first()

    if existente:
        db.session.delete(existente)
        db.session.commit()
    else:
        nova = Reacao(tipo=tipo, id_imagem=imagem_id, id_utilizador=user.id)
        db.session.add(nova)
        db.session.commit()

    return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))


# AJAX toggle endpoint -> devolve JSON { status: "liked"|"unliked", likes: N }
@app.route("/reacao/toggle", methods=["POST"])
@login_required
def reacao_toggle():
    # aceita form ou json
    if request.is_json:
        data = request.get_json()
        imagem_id = int(data.get("imagem_id", 0))
        tipo = data.get("tipo", "like")
    else:
        imagem_id = request.form.get("imagem_id", type=int)
        tipo = request.form.get("tipo", "like")

    if not imagem_id or not tipo:
        return jsonify({"error": "missing parameters"}), 400

    user = current_user()

    existente = Reacao.query.filter_by(
        tipo=tipo,
        id_imagem=imagem_id,
        id_utilizador=user.id
    ).first()

    if existente:
        db.session.delete(existente)
        db.session.commit()
        status = "unliked"
    else:
        nova = Reacao(tipo=tipo, id_imagem=imagem_id, id_utilizador=user.id)
        db.session.add(nova)
        try:
            db.session.commit()
            status = "liked"
        except Exception:
            db.session.rollback()
            return jsonify({"error": "db error"}), 500

    likes = Reacao.query.filter_by(id_imagem=imagem_id, tipo="like").count()

    return jsonify({"status": status, "likes": likes})


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
    user_email = (user.email or "").strip().lower() if user else ""
    if not user or (ADMIN_EMAILS and user_email not in ADMIN_EMAILS):
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
    requester = current_user()
    if not requester:
        return redirect(url_for("login"))
    if requester.id != user_id and (requester.email != ADMIN_EMAIL):
        flash("Não tens permissão para gerar este certificado.", "error")
        return redirect(url_for("index"))
    user = Utilizador.query.get_or_404(user_id)
    html_content = render_template("certificado.html", user=user)
    html_path = os.path.join(TEMP_FOLDER, f"certificado_{user.id}.html")
    pdf_path = os.path.join(PDF_FOLDER, f"certificado_{user.id}.pdf")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    try:
        from cloudconvert_service import html_para_pdf
        html_para_pdf(html_path, pdf_path)
    except Exception:
        flash("Geração de PDF falhou (CloudConvert). HTML guardado temporariamente.", "error")
    return redirect("/" + pdf_path)

# API endpoints
@app.route("/api/imagens", methods=["GET"])
def api_imagens():
    q = request.args.get("q", "", type=str).strip()
    categoria_id = request.args.get("categoria", type=int)
    page = max(request.args.get("page", 1, type=int), 1)
    per = min(max(request.args.get("per", 20, type=int), 1), 200)

    query = Imagem.query
    if categoria_id:
        query = query.filter_by(id_categoria=categoria_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Imagem.titulo.ilike(like)) |
            (Imagem.tags.ilike(like)) |
            (Imagem.categoria_texto.ilike(like))
        )

    total = query.count()
    items = query.order_by(Imagem.data_upload.desc()).offset((page - 1) * per).limit(per).all()

    def to_dict(img):
        caminho = getattr(img, "caminho_armazenamento", "") or ""
        if caminho.startswith("http://") or caminho.startswith("https://"):
            url_publica = caminho
        else:
            url_publica = request.host_url.rstrip("/") + caminho

        return {
            "id": getattr(img, "id", None),
            "titulo": getattr(img, "titulo", None),
            "caminho_armazenamento": caminho,
            "url_publica": url_publica,
            "categoria_texto": getattr(img, "categoria_texto", None),
            "id_categoria": getattr(img, "id_categoria", None),
            "tags": getattr(img, "tags", None),
            "id_utilizador": getattr(img, "id_utilizador", None),
            "data_upload": getattr(img, "data_upload").isoformat() if getattr(img, "data_upload", None) else None
        }

    return jsonify({
        "total": total,
        "page": page,
        "per": per,
        "imagens": [to_dict(i) for i in items]
    })

@app.route("/api/imagens/<int:imagem_id>", methods=["GET"])
def api_imagem_detail(imagem_id):
    img = Imagem.query.get_or_404(imagem_id)
    votos = db.session.query(func.count(Voto.id)).filter(Voto.id_imagem == imagem_id).scalar() or 0
    num_comentarios = Comentario.query.filter_by(id_imagem=imagem_id).count()

    caminho = getattr(img, "caminho_armazenamento", "") or ""
    if caminho.startswith("http://") or caminho.startswith("https://"):
        url_publica = caminho
    else:
        url_publica = request.host_url.rstrip("/") + caminho

    data = {
        "id": getattr(img, "id", None),
        "titulo": getattr(img, "titulo", None),
        "caminho_armazenamento": caminho,
        "url_publica": url_publica,
        "categoria_texto": getattr(img, "categoria_texto", None),
        "id_categoria": getattr(img, "id_categoria", None),
        "tags": getattr(img, "tags", None),
        "id_utilizador": getattr(img, "id_utilizador", None),
        "data_upload": getattr(img, "data_upload").isoformat() if getattr(img, "data_upload", None) else None,
        "votos": int(votos),
        "comentarios": int(num_comentarios)
    }

    return jsonify(data)

@app.route("/api/categorias", methods=["GET"])
def api_categorias():
    categorias = Categoria.query.order_by(Categoria.nome).all()
    data = [{"id": c.id, "nome": c.nome} for c in categorias]
    return jsonify(data)

@app.route("/api/exposicoes/<int:exposicao_id>/top", methods=["GET"])
def api_exposicao_top(exposicao_id):
    exposicao = Exposicao.query.get_or_404(exposicao_id)
    rows = db.session.query(
        Imagem,
        func.count(Voto.id).label("total_votos")
    ).outerjoin(Voto, Voto.id_imagem == Imagem.id).group_by(Imagem.id).order_by(func.count(Voto.id).desc()).limit(10).all()
    def to_min(img, votos):
        return {
            "id": getattr(img, "id", None),
            "titulo": getattr(img, "titulo", None),
            "caminho_armazenamento": getattr(img, "caminho_armazenamento", None),
            "categoria_texto": getattr(img, "categoria_texto", None),
            "votos": int(votos)
        }
    top = [to_min(img, votos) for img, votos in rows]
    return jsonify({
        "exposicao_id": exposicao.id,
        "exposicao_nome": getattr(exposicao, "nome", None),
        "top": top
    })

@app.route("/login")
def login():
    redirect_uri = url_for("google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/login/google/callback")
def google_callback():
    token = google.authorize_access_token()
    user_info = {}
    try:
        resp = google.get("userinfo")
        if resp and resp.ok:
            user_info = resp.json()
    except Exception:
        user_info = {}
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

@app.route("/perfil")
def perfil_me():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    return redirect(url_for("perfil", imagem_id=user.id))

@app.route("/perfil/<int:imagem_id>")
def perfil(imagem_id: int):
    user = Utilizador.query.get_or_404(imagem_id)
    imagens = Imagem.query.filter_by(id_utilizador=user.id).order_by(Imagem.data_upload.desc()).all()
    return render_template("perfil.html", user=user, imagens=imagens, categorias=Categoria.query.all(), query_text="", selected_categoria=None)

@app.route("/perfil/editar", methods=["GET", "POST"])
@login_required
def editar_perfil():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        descricao = request.form.get("descricao", "").strip()
        if not nome:
            flash("O nome não pode ficar vazio.", "error")
            return redirect(url_for("editar_perfil"))
        user.nome = nome
        # tenta definir ambos os possíveis nomes de coluna/atributo para compatibilidade
        try:
            setattr(user, "Descricao", descricao)
        except Exception:
            pass
        try:
            setattr(user, "descricao", descricao)
        except Exception:
            pass
        try:
            db.session.add(user)
            db.session.commit()
            flash("Perfil atualizado.", "success")
        except Exception as e:
            db.session.rollback()
            flash("Erro ao guardar perfil.", "error")
        return redirect(url_for("perfil", imagem_id=user.id))
    return render_template("editar_perfil.html", categorias=Categoria.query.all(), query_text="", selected_categoria=None)

if __name__ == "__main__":
    app.run(debug=True)





