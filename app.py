from datetime import datetime
import os
import threading

from dotenv import load_dotenv
load_dotenv() 
from cloudconvert_service import html_para_pdf

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
from models import db, Utilizador, Categoria, Imagem, Comentario, Reacao, Exposicao

from authlib.integrations.flask_client import OAuth

from sqlalchemy import text
from sqlalchemy import inspect
import traceback
from flask import make_response

import calendar
from datetime import date

from supabase import create_client
import uuid
import mimetypes

from moderacao import moderar_comentario

raw_admins = os.getenv("ADMIN_EMAIL", "")
# permite suportar 1 ou vários emails separados por vírgula
ADMIN_EMAILS = [e.strip().lower() for e in raw_admins.split(",") if e.strip()]


from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.jinja_env.globals.update(enumerate=enumerate)
app.config.from_object(Config)

app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

db.init_app(app)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

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

@app.errorhandler(500)
def internal_error(e):
    tb = traceback.format_exc()
    app.logger.error("Unhandled Exception on request: %s\n%s", request.path, tb)
    try:
        return make_response(render_template("500.html", message=str(e)), 500)
    except Exception as er:
        app.logger.exception("Falha a renderizar 500.html: %s", er)
        return make_response("Internal Server Error", 500)


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
    inspector = inspect(db.engine)
    if not inspector.has_table("utilizador"):
        app.logger.info("ensure_google_columns: tabela 'utilizador' não existe ainda — skipping.")
        return

    cols = {}
    try:
        cols['imagem'] = [c['name'] for c in inspector.get_columns('imagem')]
    except Exception:
        cols['imagem'] = []
    try:
        cols['comentario'] = [c['name'] for c in inspector.get_columns('comentario')]
    except Exception:
        cols['comentario'] = []
    try:
        cols['utilizador'] = [c['name'] for c in inspector.get_columns('utilizador')]
    except Exception:
        cols['utilizador'] = []
    try:
        cols['exposicao'] = [c['name'] for c in inspector.get_columns('exposicao')]
    except Exception:
        cols['exposicao'] = []

    with db.engine.begin() as conn:
        if "Google_ID" not in cols.get('utilizador', []):
            conn.execute(text('ALTER TABLE utilizador ADD COLUMN IF NOT EXISTS "Google_ID" VARCHAR(200);'))
        if "Foto_URL" not in cols.get('utilizador', []):
            conn.execute(text('ALTER TABLE utilizador ADD COLUMN IF NOT EXISTS "Foto_URL" VARCHAR(300);'))
        if "Tipo_Utilizador" not in cols.get('utilizador', []):
            conn.execute(text('ALTER TABLE utilizador ADD COLUMN IF NOT EXISTS "Tipo_Utilizador" VARCHAR(50);'))

        if "ID_Comentario_Pai" not in cols.get('comentario', []):
            conn.execute(text('ALTER TABLE comentario ADD COLUMN IF NOT EXISTS "ID_Comentario_Pai" INTEGER;'))
        if "Mes" in cols.get('exposicao', []):
            try:
                conn.execute(text('ALTER TABLE exposicao ALTER COLUMN "Mes" DROP NOT NULL;'))
            except Exception:
                pass
        if "Descricao" not in cols.get('exposicao', []):
            conn.execute(text('ALTER TABLE exposicao ADD COLUMN IF NOT EXISTS "Descricao" VARCHAR(500);'))
        if "Start_Date" not in cols.get('exposicao', []):
            conn.execute(text('ALTER TABLE exposicao ADD COLUMN IF NOT EXISTS "Start_Date" DATE;'))
        if "End_Date" not in cols.get('exposicao', []):
            conn.execute(text('ALTER TABLE exposicao ADD COLUMN IF NOT EXISTS "End_Date" DATE;'))
        if "Mes_Inteiro" not in cols.get('exposicao', []):
            conn.execute(text('ALTER TABLE exposicao ADD COLUMN IF NOT EXISTS "Mes_Inteiro" BOOLEAN DEFAULT FALSE;'))
        if "Categoria_ID" not in cols.get('exposicao', []):
            conn.execute(text('ALTER TABLE exposicao ADD COLUMN IF NOT EXISTS "Categoria_ID" INTEGER;'))

        if "Exposicoes_Ids" not in cols.get('imagem', []):
            conn.execute(text('ALTER TABLE imagem ADD COLUMN IF NOT EXISTS "Exposicoes_Ids" VARCHAR(300);'))


    try:
        with db.engine.begin() as conn:
            conn.execute(text('''
                ALTER TABLE comentario
                ADD CONSTRAINT IF NOT EXISTS comentario_parent_fk FOREIGN KEY ("ID_Comentario_Pai") REFERENCES comentario("ID_Comentario");
            '''))
    except Exception:
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
            # --- BLOCO DE LIMPEZA FORÇADA ---
            try:
                # Tenta apagar a tabela Voto explicitamente usando a sessão
                db.session.execute(text("DROP TABLE IF EXISTS voto CASCADE"))
                db.session.commit()
                app.logger.info(">>> SUCESSO: Tabela 'voto' apagada no arranque da aplicação. <<<")
            except Exception as e:
                db.session.rollback()
                app.logger.warning(f">>> AVISO: Não foi possível apagar a tabela voto (talvez já não exista): {e}")
            # -------------------------------

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
    exposicao_id = request.args.get("exposicao", type=int)
    ordenar = request.args.get("ordenar", "mais_recentes", type=str)

    categorias = Categoria.query.order_by(Categoria.nome).all()

 
    recomendacoes = []
    if not q and not categoria_id and not exposicao_id:
        recomendacoes = Imagem.query.order_by(db.func.random()).limit(12).all()

    
    base_q = Imagem.query

    exposicao_obj = None
    if exposicao_id:
        exposicao_obj = Exposicao.query.get(exposicao_id)
        if exposicao_obj:
            if exposicao_obj.start_date:
                base_q = base_q.filter(Imagem.data_upload >= datetime.combine(exposicao_obj.start_date, datetime.min.time()))
            if exposicao_obj.end_date:
                base_q = base_q.filter(Imagem.data_upload <= datetime.combine(exposicao_obj.end_date, datetime.max.time()))
            if getattr(exposicao_obj, "categoria_id", None):
                base_q = base_q.filter(Imagem.id_categoria == exposicao_obj.categoria_id)
            if getattr(exposicao_obj, "usar_tags", False) and getattr(exposicao_obj, "tags_filtro", None):
                tags = [t.strip() for t in (exposicao_obj.tags_filtro or "").split(",") if t.strip()]
                if tags:
                    cond = False
                    for t in tags:
                        cond = cond | (Imagem.tags.ilike(f"%{t}%"))
                    base_q = base_q.filter(cond)

    
    if categoria_id and not exposicao_id:
        base_q = base_q.filter_by(id_categoria=categoria_id)

    
    if q:
        like = f"%{q}%"
        base_q = base_q.filter(
            (Imagem.titulo.ilike(like)) |
            (Imagem.categoria_texto.ilike(like)) |
            (Imagem.tags.ilike(like))
        )

    
    imagens = []
    ordenar = ordenar or "mais_recentes"
    if ordenar in ("mais_curtidas", "menos_curtidas"):
        ids = [r.id for r in base_q.with_entities(Imagem.id).all()]
        if ids:
            order_dir = desc if ordenar == "mais_curtidas" else func.asc
            rows = (
                db.session.query(Imagem, func.count(Reacao.id).label("likes"))
                .outerjoin(Reacao, (Reacao.id_imagem == Imagem.id) & (Reacao.tipo == "like"))
                .filter(Imagem.id.in_(ids))
                .group_by(Imagem.id)
                .order_by(desc("likes") if ordenar == "mais_curtidas" else func.min("likes"))  # fallback
                .all()
            )
            
            imagens = [r[0] for r in rows]
        else:
            imagens = []
    else:
        if ordenar == "mais_antigas":
            imagens = base_q.order_by(Imagem.data_upload.asc()).all()
        else:  
            imagens = base_q.order_by(Imagem.data_upload.desc()).all()

    is_search = bool(q)
    is_categoria = bool(categoria_id and not exposicao_id)
    categoria_obj = Categoria.query.get(categoria_id) if categoria_id else None

    return render_template(
        "index.html",
        recomendacoes=recomendacoes,
        imagens=imagens,
        categorias=categorias,
        query_text=q,
        selected_categoria=categoria_id,
        exposicao=exposicao_obj,
        is_search=is_search,
        is_categoria=is_categoria,
        categoria_obj=categoria_obj,
        ordenar=ordenar
    )





@app.route("/imagem/<int:imagem_id>")
def imagem_detalhe(imagem_id: int):
    img = Imagem.query.get_or_404(imagem_id)
    autor = Utilizador.query.get(img.id_utilizador) if img.id_utilizador else None

    comentarios_tuplas = (
        db.session.query(Comentario, Utilizador)
        .outerjoin(Utilizador, Comentario.id_utilizador == Utilizador.id)
        .filter(Comentario.id_imagem == imagem_id)
        .order_by(Comentario.data.desc())
        .all()
    )

    likes = Reacao.query.filter_by(id_imagem=imagem_id, tipo="like").count()

    user = current_user()
    user_liked = False
    if user:
        user_liked = (
            Reacao.query.filter_by(id_imagem=imagem_id, id_utilizador=user.id, tipo="like").first()
            is not None
        )

    pending_text = session.pop("pending_comment_text", "") if session.get("pending_comment_text") else ""

    return render_template(
        "imagem.html",
        imagem=img,
        autor=autor,
        comentarios=comentarios_tuplas,
        likes=likes,
        user_liked=user_liked,
        pending_text=pending_text
    )



    
    likes = Reacao.query.filter_by(id_imagem=imagem_id, tipo="like").count()

    
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

        # Upload para Supabase
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

        # --- ALTERAÇÃO AQUI: Lógica Many-to-Many ---
        selected = request.form.getlist("exposicoes")
        if selected:
            for eid in selected:
                if eid:
                    exp_obj = Exposicao.query.get(int(eid))
                    if exp_obj:
                        img.exposicoes.append(exp_obj)
        # -------------------------------------------

        db.session.add(img)
        db.session.commit()
        flash("Publicado com sucesso!", "success")
        return redirect(url_for("index"))

    # GET request
    categorias = Categoria.query.all()
    hoje = date.today()
    exposicoes_all = Exposicao.query.filter_by(ativo=True).all()
    exposicoes_disponiveis = []

    for e in exposicoes_all:
        valido = False
        if e.mes_inteiro and e.mes:
            try:
                m, y = map(int, e.mes.split("/"))
                if m == hoje.month and y == hoje.year:
                    valido = True
            except Exception:
                valido = False
        else:
            if e.start_date and e.end_date and e.start_date <= hoje <= e.end_date:
                valido = True

        if valido:
            exposicoes_disponiveis.append(e)

    return render_template(
        "upload.html",
        categorias=categorias,
        exposicoes=exposicoes_disponiveis,
        query_text="",
        selected_categoria=None,
    )

@app.route("/apagar_imagem/<int:imagem_id>", methods=["POST"])
@login_required
def apagar_imagem(imagem_id: int):
    user = current_user()
    img = Imagem.query.get_or_404(imagem_id)
    user_email = (user.email or "").strip().lower() if user else ""
    
    if not user or not (user.id == img.id_utilizador or (ADMIN_EMAILS and user_email in ADMIN_EMAILS)):
        flash("Não tens permissão para apagar esta imagem.", "error")
        return redirect(url_for("index"))

    # Apagar dependências
    Comentario.query.filter_by(id_imagem=imagem_id).delete()
    Reacao.query.filter_by(id_imagem=imagem_id).delete()
    
    # Limpar associações Many-to-Many antes de apagar
    img.exposicoes = []

    # Tentar apagar ficheiro local (se existir)
    try:
        caminho_relativo = (img.caminho_armazenamento or "").lstrip("/")
        caminho_ficheiro = os.path.join(app.root_path, caminho_relativo)
        if os.path.exists(caminho_ficheiro):
            try:
                os.remove(caminho_ficheiro)
            except Exception as e:
                app.logger.warning("Falha a remover ficheiro local: %s", e)
    except Exception:
        pass

    db.session.delete(img)
    db.session.commit()

    # Apagar do Supabase
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
    texto = (request.form.get("texto") or "").strip()
    imagem_id = request.form.get("imagem_id", type=int)

    if not texto or len(texto) > 140:
        flash("Comentário inválido ou demasiado longo (máx. 140).", "error")
        session["pending_comment_text"] = texto
        return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))

    try:

        bloqueado = moderar_comentario(texto)
    except Exception as e:
        app.logger.exception("Erro ao chamar moderador IA: %s", e)
        bloqueado = False

    if bloqueado:
        flash("Linguagem imprópria detectada. Edita o comentário.", "error")
        session["pending_comment_text"] = texto
        return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))

    c = Comentario(texto=texto, id_imagem=imagem_id, id_utilizador=user.id if user else None)
    db.session.add(c)
    db.session.commit()
    return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))


@app.route("/apagar_comentario", methods=["POST"])
@login_required
def apagar_comentario():
    user = current_user()
    comentario_id = request.form.get("comentario_id", type=int)
    imagem_id = request.form.get("imagem_id", type=int)

    if not comentario_id:
        flash("Comentário inválido.", "error")
        return redirect(url_for("index"))

    c = Comentario.query.get_or_404(comentario_id)

    user_email = (user.email or "").strip().lower() if user else ""
    if not user or not (user.id == c.id_utilizador or (ADMIN_EMAILS and user_email in ADMIN_EMAILS)):
        flash("Não tens permissão para apagar este comentário.", "error")
        return redirect(url_for("imagem_detalhe", imagem_id=imagem_id or c.id_imagem))

    db.session.delete(c)
    db.session.commit()
    flash("Comentário apagado.", "success")
    return redirect(url_for("imagem_detalhe", imagem_id=imagem_id or c.id_imagem))



@app.route("/reacao", methods=["POST"])
@login_required
def reacao():
    tipo = request.form.get("tipo")
    imagem_id = request.form.get("imagem_id", type=int)

    if not tipo or not imagem_id:
        return redirect(url_for("index"))

    user = current_user()  

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



@app.route("/reacao/toggle", methods=["POST"])
@login_required
def reacao_toggle():
    
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
    exposicao_id = request.args.get("exposicao_id", type=int)
    if exposicao_id:
        e = Exposicao.query.get_or_404(exposicao_id)

        q = Imagem.query

        # --- ALTERAÇÃO: Lógica de Associação Many-to-Many ---
        # Verifica se a imagem está na lista de 'imagens_associadas' desta exposição
        # (Isso funciona graças ao backref definido no models.py ou relação direta)
        manual_cond = Imagem.exposicoes.any(Exposicao.id == e.id)
        # ----------------------------------------------------

        cond_intervalo = True
        if e.start_date and e.end_date:
            cond_intervalo = (Imagem.data_upload >= datetime.combine(e.start_date, datetime.min.time())) & (Imagem.data_upload <= datetime.combine(e.end_date, datetime.max.time()))

        if getattr(e, "usar_categorias", False) and getattr(e, "categoria_id", None):
            q = q.filter((manual_cond) | ((Imagem.id_categoria == e.categoria_id) & cond_intervalo))
        elif getattr(e, "usar_tags", False) and getattr(e, "tags_filtro", None):
            tags = [t.strip() for t in (e.tags_filtro or "").split(",") if t.strip()]
            tag_cond = False
            for t in tags:
                tag_cond = tag_cond | Imagem.tags.ilike(f"%{t}%")
            q = q.filter((manual_cond) | (tag_cond & cond_intervalo))
        else:
            q = q.filter((manual_cond) | cond_intervalo)

        ids = [row.id for row in q.with_entities(Imagem.id).all()]
        top = []
        if ids:
            top = (
                db.session.query(Imagem, func.count(Reacao.id).label("likes"))
                .outerjoin(Reacao, (Reacao.id_imagem == Imagem.id) & (Reacao.tipo == "like"))
                .filter(Imagem.id.in_(ids))
                .group_by(Imagem.id)
                .order_by(desc("likes"))
                .limit(10)
                .all()
            )

        return render_template("exposição.html", exposicao=e, top=top)
    else:
        exposicoes = Exposicao.query.order_by(Exposicao.id.desc()).all()
        return render_template("exposição.html", exposicoes=exposicoes)



@app.route("/exposicao")
def exposicao_redirect():
    exposicao_id = request.args.get("exposicao_id", type=int)
    if exposicao_id:
        return redirect(url_for("index", exposicao=exposicao_id))
    return redirect(url_for("index"))


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
            nome = (request.form.get("nome") or "").strip()
            if nome:
            
                if not Categoria.query.filter(func.lower(Categoria.nome) == nome.lower()).first():
                    c = Categoria(nome=nome)
                    db.session.add(c)
                    db.session.commit()
                    flash("Categoria criada.", "success")
                else:
                    flash("Já existe uma categoria com esse nome.", "error")
            else:
                flash("Nome inválido.", "error")

        elif action == "delete_categoria":
            categoria_id = request.form.get("categoria_id", type=int)
            if categoria_id:
                c = Categoria.query.get(categoria_id)
                if c:
                    
                    Imagem.query.filter_by(id_categoria=c.id).update({"id_categoria": None, "categoria_texto": None})
                    db.session.delete(c)
                    db.session.commit()
                    flash("Categoria apagada.", "success")
                else:
                    flash("Categoria não encontrada.", "error")

        elif action == "create_exposicao":
            nome = request.form.get("nome")
            descricao = request.form.get("descricao", "").strip() or None
            categoria_id = request.form.get("categoria_id", type=int) or None
            tags_filtro = request.form.get("tags_filtro", "").strip() or None
            usar_tags = bool(request.form.get("usar_tags"))
            usar_categorias = bool(request.form.get("usar_categorias"))

            tipo_periodo = request.form.get("tipo_periodo", "mes_inteiro")
            start = None
            end = None
            mes_val = None
            mes_inteiro_flag = False

            if tipo_periodo == "mes_inteiro":
                mes_text = request.form.get("mes")
                ano_text = request.form.get("ano")
                if mes_text and ano_text:
                    y = int(ano_text)
                    m = int(mes_text)
                    start = date(y, m, 1)
                    last_day = calendar.monthrange(y, m)[1]
                    end = date(y, m, last_day)
                    mes_val = f"{m:02d}/{y}"
                    mes_inteiro_flag = True
            else:
                sd = request.form.get("start_date")
                ed = request.form.get("end_date")
                if sd:
                    start = date.fromisoformat(sd)
                if ed:
                    end = date.fromisoformat(ed)
                mes_val = None
                mes_inteiro_flag = False

            if nome:
                e = Exposicao(
                    nome=nome,
                    descricao=descricao,
                    mes=mes_val,
                    mes_inteiro=mes_inteiro_flag,
                    start_date=start,
                    end_date=end,
                    categoria_id=categoria_id,
                    tags_filtro=tags_filtro,
                    usar_tags=usar_tags,
                    usar_categorias=usar_categorias,
                    ativo=True
                )
                db.session.add(e)
                db.session.commit()
                flash("Exposição criada.", "success")
            else:
                flash("Nome da exposição obrigatório.", "error")

        elif action == "update_exposicao":
            exposicao_id = request.form.get("exposicao_id", type=int)
            e = Exposicao.query.get(exposicao_id)
            if e:
                e.nome = request.form.get("nome") or e.nome
                e.descricao = request.form.get("descricao", "").strip() or e.descricao
                e.ativo = bool(int(request.form.get("ativo", 1)))
                e.categoria_id = request.form.get("categoria_id", type=int) or e.categoria_id
                e.tags_filtro = request.form.get("tags_filtro", "").strip() or e.tags_filtro
                db.session.commit()
                flash("Exposição atualizada.", "success")

        elif action == "delete_exposicao":
            exposicao_id = request.form.get("exposicao_id", type=int)
            e = Exposicao.query.get(exposicao_id)
            if e:
                db.session.delete(e)
                db.session.commit()
                flash("Exposição apagada.", "success")

    categorias = Categoria.query.order_by(Categoria.nome).all()
    exposicoes = Exposicao.query.order_by(Exposicao.id.desc()).all()
    return render_template(
        "admin.html",
        categorias=categorias,
        exposicoes=exposicoes,
        query_text="",
        selected_categoria=None,
    )



@app.route("/exportar_exposicao", methods=["GET", "POST"])
def exportar_exposicao():
    exposicoes = Exposicao.query.order_by(Exposicao.id.desc()).all()
    categorias = Categoria.query.all()
    pdf_url = None
    exposicao_selecionada = None
    top = []
    
    if request.method == "POST":
        exposicao_id = request.form.get("exposicao_id", type=int)
        if exposicao_id:
            exposicao_selecionada = Exposicao.query.get(exposicao_id)
            if exposicao_selecionada:
                
                q = Imagem.query
                
                # --- ALTERAÇÃO: Filtro Many-to-Many ---
                manual_cond = Imagem.exposicoes.any(Exposicao.id == exposicao_selecionada.id)
                # --------------------------------------

                cond_intervalo = True
                if exposicao_selecionada.start_date and exposicao_selecionada.end_date:
                    cond_intervalo = (Imagem.data_upload >= datetime.combine(exposicao_selecionada.start_date, datetime.min.time())) & (Imagem.data_upload <= datetime.combine(exposicao_selecionada.end_date, datetime.max.time()))

                if getattr(exposicao_selecionada, "usar_categorias", False) and getattr(exposicao_selecionada, "categoria_id", None):
                    q = q.filter((manual_cond) | ((Imagem.id_categoria == exposicao_selecionada.categoria_id) & cond_intervalo))
                elif getattr(exposicao_selecionada, "usar_tags", False) and getattr(exposicao_selecionada, "tags_filtro", None):
                    tags = [t.strip() for t in (exposicao_selecionada.tags_filtro or "").split(",") if t.strip()]
                    tag_cond = False
                    for t in tags:
                        tag_cond = tag_cond | Imagem.tags.ilike(f"%{t}%")
                    q = q.filter((manual_cond) | (tag_cond & cond_intervalo))
                else:
                    q = q.filter((manual_cond) | cond_intervalo)

                ids = [r.id for r in q.with_entities(Imagem.id).all()]
                if ids:
                    top = (
                        db.session.query(Imagem, func.count(Reacao.id).label("likes"))
                        .outerjoin(Reacao, (Reacao.id_imagem == Imagem.id) & (Reacao.tipo == "like"))
                        .filter(Imagem.id.in_(ids))
                        .group_by(Imagem.id)
                        .order_by(desc("likes"))
                        .limit(10)
                        .all()
                    )

                html_content = render_template("catalogo_exposicao.html", exposicao=exposicao_selecionada, top=top, now=lambda: datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S"))
                html_path = os.path.join(TEMP_FOLDER, f"catalogo_exposicao_{exposicao_selecionada.id}.html")
                pdf_path = os.path.join(PDF_FOLDER, f"catalogo_exposicao_{exposicao_selecionada.id}.pdf")
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                try:
                    from cloudconvert_service import html_para_pdf
                    html_para_pdf(html_path, pdf_path)
                    pdf_url = f"/static/pdf/catalogo_exposicao_{exposicao_selecionada.id}.pdf"
                    flash("PDF gerado com sucesso.", "success")
                    return redirect(pdf_url)
                except Exception as ex:
                    app.logger.exception("Erro ao gerar PDF: %s", ex)
                    flash("Falha ao gerar PDF. Vê os logs.", "error")
                    
    return render_template("exportar_exposicao.html", exposicoes=exposicoes, pdf_url=pdf_url, exposicao=exposicao_selecionada, top=top, categorias=categorias, query_text="", selected_categoria=None)

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



@app.route("/api/categorias", methods=["GET"])
def api_categorias():
    categorias = Categoria.query.order_by(Categoria.nome).all()
    data = [{"id": c.id, "nome": c.nome} for c in categorias]
    return jsonify(data)

@app.route("/api/exposicoes/<int:exposicao_id>/top", methods=["GET"])
def api_exposicao_top(exposicao_id):
    exposicao = Exposicao.query.get_or_404(exposicao_id)
    
    # Obter apenas imagens associadas a esta exposição
    q_imgs = Imagem.query.filter(Imagem.exposicoes.any(Exposicao.id == exposicao_id))
    img_ids = [i.id for i in q_imgs.with_entities(Imagem.id).all()]

    if not img_ids:
        return jsonify({
            "exposicao_id": exposicao.id,
            "exposicao_nome": getattr(exposicao, "nome", None),
            "top": []
        })

    # Consulta atualizada para contar Likes (Reacao)
    rows = db.session.query(
        Imagem,
        func.count(Reacao.id).label("total_likes")
    ).outerjoin(Reacao, (Reacao.id_imagem == Imagem.id) & (Reacao.tipo == 'like')) \
     .filter(Imagem.id.in_(img_ids)) \
     .group_by(Imagem.id) \
     .order_by(desc("total_likes")) \
     .limit(10).all()
     
    def to_min(img, likes):
        return {
            "id": getattr(img, "id", None),
            "titulo": getattr(img, "titulo", None),
            "caminho_armazenamento": getattr(img, "caminho_armazenamento", None),
            "categoria_texto": getattr(img, "categoria_texto", None),
            "votos": int(likes) 
        }
    
    top = [to_min(img, likes) for img, likes in rows]
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

@app.route("/_fix_exposicoes_once")
def fix_exposicoes_once():
    from datetime import date
    import calendar

    exposicoes = Exposicao.query.filter(
        (Exposicao.start_date == None) | (Exposicao.end_date == None)
    ).all()

    total = 0

    for e in exposicoes:
        if e.mes and "/" in e.mes:
            try:
                m, y = map(int, e.mes.split("/"))
                first = date(y, m, 1)
                last_day = calendar.monthrange(y, m)[1]
                last = date(y, m, last_day)

                if not e.start_date:
                    e.start_date = first
                if not e.end_date:
                    e.end_date = last

                db.session.add(e)
                total += 1
            except Exception:
                pass

    db.session.commit()
    return f"Migração concluída. Exposições corrigidas: {total}"

if __name__ == "__main__":
    app.run(debug=True)






