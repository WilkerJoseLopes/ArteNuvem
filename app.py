from datetime import datetime
import os
import threading

from dotenv import load_dotenv
load_dotenv() 
from cloudconvert_service import html_para_pdf

from flask import render_template_string
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
from sqlalchemy import func, desc, or_

from config import Config

from models import (
    db,
    Utilizador,
    Categoria,
    Imagem,
    Comentario,
    Reacao,
    Exposicao,
    Localizacao,
    ResultadoModeracao,
    imagem_exposicao,
    Notification,
    PreferenciaNotificacao,
)

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

from moderacao import avaliar_comentario, gerar_sugestao_obra
from services.recommendation_service import build_recommendations, serialize_image
from services.email_service import (
    send_welcome_email,
    send_recommendation_email,
    get_or_create_preferences,
)

from werkzeug.middleware.proxy_fix import ProxyFix

_tables_lock = threading.Lock()

raw_admins = os.getenv("ADMIN_EMAIL", "")
# permite suportar 1 ou vários emails separados por vírgula
ADMIN_EMAILS = [e.strip().lower() for e in raw_admins.split(",") if e.strip()]
ADMIN_EMAIL = ADMIN_EMAILS[0] if ADMIN_EMAILS else None

app = Flask(__name__)
app.jinja_env.globals.update(enumerate=enumerate)
app.config.from_object(Config)

@app.context_processor
def inject_google_maps_api_key():
    return dict(GOOGLE_MAPS_API_KEY=os.getenv("GOOGLE_MAPS_API_KEY", ""))


app.config['SESSION_COOKIE_SECURE'] = os.getenv("FLASK_ENV", "production") == "production"
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "8")) * 1024 * 1024

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


SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "ImagePOST")

def ensure_supabase_bucket(bucket_name: str = SUPABASE_BUCKET) -> None:
    if not supabase_service:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY não definido no ambiente.")

    try:
        buckets = supabase_service.storage.list_buckets()
        for b in buckets or []:
            b_name = b.get("name") if isinstance(b, dict) else getattr(b, "name", None)
            b_id = b.get("id") if isinstance(b, dict) else getattr(b, "id", None)
            if bucket_name in {b_name, b_id}:
                return
    except Exception:
        pass

    create_bucket = getattr(supabase_service.storage, "create_bucket", None)
    if callable(create_bucket):
        try:
            create_bucket(bucket_name, {"public": True})
            app.logger.info("Bucket Supabase '%s' criado automaticamente.", bucket_name)
            return
        except TypeError:
            try:
                create_bucket(bucket_name, options={"public": True})
                app.logger.info("Bucket Supabase '%s' criado automaticamente.", bucket_name)
                return
            except Exception as e:
                app.logger.warning("Falha ao criar bucket via SDK: %s", e)
        except Exception as e:
            app.logger.warning("Falha ao criar bucket via SDK: %s", e)

    try:
        import requests
        headers = {
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Content-Type": "application/json",
        }
        payload = {"id": bucket_name, "name": bucket_name, "public": True}
        resp = requests.post(f"{SUPABASE_URL}/storage/v1/bucket", json=payload, headers=headers, timeout=20)
        if resp.status_code in (200, 201, 409):
            app.logger.info("Bucket Supabase '%s' confirmado/criado via REST.", bucket_name)
            return
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Bucket '{bucket_name}' não encontrado e não foi possível criá-lo: {e}")


def upload_imagem_supabase(file):
    if not supabase_service:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY não definido no ambiente.")

    ensure_supabase_bucket(SUPABASE_BUCKET)

    ext = file.filename.rsplit(".", 1)[1].lower() if "." in file.filename else "bin"
    nome_unico = f"{uuid.uuid4()}.{ext}"
    content_type = mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

    try:
        file.stream.seek(0)
        supabase_service.storage.from_(SUPABASE_BUCKET).upload(
            nome_unico,
            file.stream.read(),
            {"content-type": content_type}
        )
    except Exception as e:
        app.logger.exception("Erro no upload para Supabase Storage: %s", e)
        raise RuntimeError(f"Falha ao enviar imagem para o bucket '{SUPABASE_BUCKET}': {e}")

    public_url = (
        supabase.storage.from_(SUPABASE_BUCKET).get_public_url(nome_unico)
        if supabase else
        f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{nome_unico}"
    )
    return public_url, nome_unico


def ensure_google_columns():
    app.logger.info("Schema gerido externamente no Supabase; migrações DDL no arranque desativadas.")
    return


with app.app_context():
    ensure_google_columns()

oauth = OAuth(app)

google = oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    access_token_url="https://oauth2.googleapis.com/token",
    api_base_url="https://www.googleapis.com/oauth2/v3/",
    client_kwargs={
        "scope": "https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile",
    },
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
        return db.session.get(Utilizador, uid)
    return None

def is_admin(user=None) -> bool:
    user = user or current_user()
    if not user or not ADMIN_EMAILS:
        return False
    return (user.email or "").strip().lower() in ADMIN_EMAILS

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            flash("Acesso restrito ao administrador.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated

def active_exposition():
    today = date.today()
    return (
        Exposicao.query.filter(
            Exposicao.ativo == True,
            or_(Exposicao.start_date == None, Exposicao.start_date <= today),
            or_(Exposicao.end_date == None, Exposicao.end_date >= today),
        )
        .order_by(Exposicao.end_date.asc().nullslast(), Exposicao.id.desc())
        .first()
    )

@app.after_request
def apply_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# Decorador personalizado para verificar autenticação nas rotas de API sem redirecionamento HTML
def api_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            return jsonify({"error": "Autenticação requerida. Faça login no navegador primeiro."}), 401
        return f(*args, **kwargs)
    return decorated


def adicionar_notificacao(id_utilizador_destino, tipo, id_imagem, titulo_imagem):
    # Não notifica se o utilizador estiver a interagir com o seu próprio post
    usuario_atual = current_user()
    if usuario_atual and usuario_atual.id == id_utilizador_destino:
        return

    # 1. Obter o utilizador destinatário da notificação
    destinatario = db.session.get(Utilizador, id_utilizador_destino)
    if not destinatario:
        return
    
    # 2. Verificar se o utilizador pausou as notificações e se a pausa ainda está ativa
    if destinatario.notifications_paused_until:
        if datetime.utcnow() < destinatario.notifications_paused_until:
            app.logger.info("Notificação ignorada devido a pausa ativa.")
            return

    # 3. Verificar se já existe uma notificação não lida deste tipo para este post
    notif_existente = Notification.query.filter_by(
        id_utilizador=id_utilizador_destino,
        type=tipo,
        id_imagem=id_imagem,
        is_read=False
    ).first()

    if notif_existente:
        # Incrementa a contagem e atualiza a mensagem
        notif_existente.count += 1
        if tipo == "like":
            notif_existente.message = f"A sua imagem '{titulo_imagem}' recebeu {notif_existente.count} novos likes."
        elif tipo == "comentario":
            notif_existente.message = f"A sua imagem '{titulo_imagem}' recebeu {notif_existente.count} novos comentários."
        
        notif_existente.created_at = datetime.utcnow()  # Atualiza a data para subir na lista
        db.session.add(notif_existente)
    else:
        # Cria uma nova notificação
        if tipo == "like":
            msg = f"A sua imagem '{titulo_imagem}' recebeu um novo like."
        elif tipo == "comentario":
            msg = f"A sua imagem '{titulo_imagem}' recebeu um novo comentário."
        else:
            msg = f"Nova interação na sua imagem '{titulo_imagem}'."

        nova_notif = Notification(
            id_utilizador=id_utilizador_destino,
            type=tipo,
            id_imagem=id_imagem,
            message=msg,
            count=1,
            is_read=False,
            created_at=datetime.utcnow()
        )
        db.session.add(nova_notif)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Erro ao adicionar notificação: %s", e)

_tables_lock = threading.Lock()

raw_admins = os.getenv("ADMIN_EMAIL", "")
ADMIN_EMAILS = [e.strip().lower() for e in raw_admins.split(",") if e.strip()]
ADMIN_EMAIL = ADMIN_EMAILS[0] if ADMIN_EMAILS else None

@app.context_processor
def inject_user():
    user = current_user()
    unread_notifs = []
    all_notifs = []
    is_paused = False
    paused_until_str = ""
    
    if user:
        all_notifs = Notification.query.filter_by(id_utilizador=user.id).order_by(Notification.created_at.desc()).all()
        unread_notifs = [n for n in all_notifs if not n.is_read]
        
        if user.notifications_paused_until and datetime.utcnow() < user.notifications_paused_until:
            is_paused = True
            paused_until_str = user.notifications_paused_until.strftime("%H:%M")

    return {
        "current_user": user,
        "ADMIN_EMAILS": ADMIN_EMAILS,
        "ADMIN_EMAIL": ADMIN_EMAIL,
        "notifications": all_notifs,
        "unread_notifications": unread_notifs,
        "notifications_paused": is_paused,
        "notifications_paused_until_str": paused_until_str
    }

@app.before_request
def ensure_tables():
    if app.config.get("TABLES_INITIALIZED"):
        return
    with _tables_lock:
        if app.config.get("TABLES_INITIALIZED"):
            return
        with app.app_context():
            inspector = inspect(db.engine)
            if not inspector.has_table("categoria"):
                if db.engine.url.drivername == "sqlite":
                    app.logger.info("Criando tabelas locais na base de dados SQLite...")
                    db.create_all()
                else:
                    app.logger.warning("Tabelas ainda não existem no Supabase. Executa o SQL de schema antes de usar a aplicação.")
                    app.config["TABLES_INITIALIZED"] = True
                    return

            # Garantir que a tabela 'notification' existe
            if not inspector.has_table("notification"):
                app.logger.info("Criando tabela 'notification'...")
                db.create_all()

            # Garantir que a tabela 'preferencia_notificacao' existe
            if not inspector.has_table("preferencia_notificacao"):
                app.logger.info("Criando tabela 'preferencia_notificacao'...")
                db.create_all()

            # Garantir que a coluna 'notificationspauseduntil' existe na tabela 'utilizador'
            if inspector.has_table("utilizador"):
                columns = [col["name"] for col in inspector.get_columns("utilizador")]
                if not any(c.lower() == "notificationspauseduntil" for c in columns):
                    app.logger.info("Adicionando coluna 'notificationspauseduntil' à tabela 'utilizador'...")
                    try:
                        with db.engine.begin() as conn:
                            conn.execute(text("ALTER TABLE utilizador ADD COLUMN notificationspauseduntil TIMESTAMP NULL"))
                    except Exception as e:
                        app.logger.error("Erro ao adicionar coluna notificationspauseduntil: %s", e)

            # Garantir que a tabela 'localizacao' existe
            if not inspector.has_table("localizacao"):
                app.logger.info("Criando tabela 'localizacao'...")
                try:
                    Localizacao.__table__.create(db.engine)
                except Exception as e:
                    app.logger.error("Erro ao criar tabela localizacao: %s", e)

            # Garantir que a coluna 'ID_Location' existe na tabela 'imagem'
            if inspector.has_table("imagem"):
                columns = [col["name"].lower() for col in inspector.get_columns("imagem")]
                if "id_location" not in columns:
                    app.logger.info("Adicionando coluna 'ID_Location' à tabela 'imagem'...")
                    try:
                        with db.engine.begin() as conn:
                            if db.engine.url.drivername == "sqlite":
                                conn.execute(text("ALTER TABLE imagem ADD COLUMN ID_Location INTEGER REFERENCES localizacao(ID_Location) NULL"))
                            else:
                                conn.execute(text("ALTER TABLE imagem ADD COLUMN \"ID_Location\" INTEGER REFERENCES localizacao(\"ID_Location\") NULL"))
                    except Exception as e:
                        app.logger.error("Erro ao adicionar coluna ID_Location: %s", e)

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
    user = current_user()
    exposicao_ativa = active_exposition()
    countdown_days = None
    if exposicao_ativa and exposicao_ativa.end_date:
        countdown_days = max((exposicao_ativa.end_date - date.today()).days, 0)

    recomendacoes = []
    recommendation_reasons = {}
    if not q and not categoria_id and not exposicao_id:
        recommendation_payload = build_recommendations(user, limit=12)
        recomendacoes = recommendation_payload["images"]
        recommendation_reasons = recommendation_payload["reasons"]

    
    base_q = Imagem.query.filter(Imagem.publica == True)

    exposicao_obj = None
    if exposicao_id:
        exposicao_obj = db.session.get(Exposicao, exposicao_id)
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
                    base_q = base_q.filter(or_(*[Imagem.tags.ilike(f"%{t}%") for t in tags]))

    
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
            likes_count = func.count(Reacao.id)
            rows = (
                db.session.query(Imagem, func.count(Reacao.id).label("likes"))
                .outerjoin(Reacao, (Reacao.id_imagem == Imagem.id) & (Reacao.tipo == "like"))
                .filter(Imagem.id.in_(ids))
                .group_by(Imagem.id)
                .order_by(likes_count.desc() if ordenar == "mais_curtidas" else likes_count.asc())
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
    categoria_obj = db.session.get(Categoria, categoria_id) if categoria_id else None

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
        ordenar=ordenar,
        recommendation_reasons=recommendation_reasons,
        exposicao_ativa=exposicao_ativa,
        countdown_days=countdown_days,
    )





@app.route("/imagem/<int:imagem_id>")
def imagem_detalhe(imagem_id: int):
    img = Imagem.query.get_or_404(imagem_id)
    autor = db.session.get(Utilizador, img.id_utilizador) if img.id_utilizador else None

    comentarios_tuplas = (
        db.session.query(Comentario, Utilizador)
        .outerjoin(Utilizador, Comentario.id_utilizador == Utilizador.id)
        .filter(Comentario.id_imagem == imagem_id)
        .filter(Comentario.estado_moderacao == "aprovado")
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



@app.route("/publicar", methods=["GET", "POST"])
@login_required
def publicar():
    user = current_user()

    if request.method == "POST":
        ficheiro = request.files.get("ficheiro")
        titulo = request.form.get("titulo")
        categoria_id = request.form.get("categoria", type=int)
        tags = request.form.get("tags", "")
        descricao = (request.form.get("descricao") or "").strip()
        address = (request.form.get("address") or "").strip()
        city = (request.form.get("city") or "").strip()
        country = (request.form.get("country") or "").strip()
        latitude = request.form.get("latitude", type=float)
        longitude = request.form.get("longitude", type=float)

        # ---------------- VALIDAÇÕES ----------------
        if not ficheiro or ficheiro.filename == "":
            flash("Selecione um ficheiro.", "error")
            return redirect(request.url)

        if not allowed_file(ficheiro.filename):
            flash("Apenas ficheiros JPG/PNG.", "error")
            return redirect(request.url)

        if ficheiro.mimetype not in {"image/png", "image/jpeg"}:
            flash("Tipo de ficheiro inválido.", "error")
            return redirect(request.url)

        if not titulo:
            flash("Título é obrigatório.", "error")
            return redirect(request.url)

        # ---------------- UPLOAD (SEGURANÇA ADICIONADA) ----------------
        try:
            caminho_url, object_key = upload_imagem_supabase(ficheiro)
        except Exception as e:
            app.logger.exception("Erro no upload Supabase: %s", e)
            flash("Erro ao enviar imagem. Verifica o bucket ou keys do Supabase.", "error")
            return redirect(request.url)

        # ---------------- CRIAR IMAGEM ----------------
        try:
            categoria_obj = db.session.get(Categoria, categoria_id) if categoria_id else None
            location_obj = None
            if address:
                from services.location_service import geocode_address
                geocoded = geocode_address(address)
                if geocoded:
                    lat_val = latitude if latitude is not None else geocoded.get("latitude")
                    lng_val = longitude if longitude is not None else geocoded.get("longitude")
                    city_val = city if city else geocoded.get("city")
                    country_val = country if country else geocoded.get("country")
                    formatted_address = geocoded.get("formatted_address") or address
                else:
                    lat_val = latitude
                    lng_val = longitude
                    city_val = city
                    country_val = country
                    formatted_address = address

                location_obj = Localizacao(
                    address=formatted_address,
                    city=city_val or None,
                    country=country_val or None,
                    latitude=lat_val,
                    longitude=lng_val,
                )
                db.session.add(location_obj)
                db.session.flush()

            img = Imagem(
                titulo=titulo,
                caminho_armazenamento=caminho_url,
                categoria_texto=categoria_obj.nome if categoria_obj else None,
                id_utilizador=user.id,
                id_categoria=categoria_id if categoria_id else None,
                descricao=descricao or None,
                id_location=location_obj.id if location_obj else None,
            )

            if tags:
                img.tags = tags

            # Many-to-Many exposições
            selected = request.form.getlist("exposicoes")
            for eid in selected:
                try:
                    exp_obj = db.session.get(Exposicao, int(eid))
                    if exp_obj:
                        img.exposicoes.append(exp_obj)
                except Exception:
                    continue

            db.session.add(img)
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            app.logger.exception("Erro ao guardar imagem na DB: %s", e)
            flash("Erro ao guardar imagem na base de dados.", "error")
            return redirect(request.url)

        flash("Publicado com sucesso!", "success")
        return redirect(url_for("index"))


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
                pass
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

    comentario_ids = [
        row.id
        for row in Comentario.query.filter_by(id_imagem=imagem_id)
        .with_entities(Comentario.id)
        .all()
    ]
    if comentario_ids:
        ResultadoModeracao.query.filter(
            ResultadoModeracao.id_comentario.in_(comentario_ids)
        ).delete(synchronize_session=False)
    Comentario.query.filter_by(id_imagem=imagem_id).delete()
    Reacao.query.filter_by(id_imagem=imagem_id).delete()
    Notification.query.filter_by(id_imagem=imagem_id).delete()
    

    img.exposicoes = []


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


    try:
        if img.caminho_armazenamento and supabase_service:
            object_key = img.caminho_armazenamento.rstrip("/").split("/")[-1]
            supabase_service.storage.from_(SUPABASE_BUCKET).remove([object_key])
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
        moderation = avaliar_comentario(texto)
    except Exception as e:
        app.logger.exception("Erro ao chamar moderador IA: %s", e)
        moderation = {
            "decision": "aprovado",
            "toxicity_score": 0,
            "model_name": "local-keyword-safety",
        }

    c = Comentario(
        texto=texto,
        id_imagem=imagem_id,
        id_utilizador=user.id if user else None,
        estado_moderacao=moderation["decision"],
    )
    db.session.add(c)
    db.session.flush()
    db.session.add(
        ResultadoModeracao(
            id_comentario=c.id,
            toxicity_score=moderation.get("toxicity_score", 0),
            decision=moderation["decision"],
            model_name=moderation.get("model_name", "local-keyword-safety"),
            motivo=moderation.get("motivo"),
        )
    )
    db.session.commit()

    if moderation["decision"] == "bloqueado":
        flash("Comentário bloqueado automaticamente por conter conteúdo inadequado.", "error")
        return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))

    if moderation["decision"] == "pendente":
        flash("Comentário enviado para revisão automática de segurança.", "success")
        return redirect(url_for("imagem_detalhe", imagem_id=imagem_id))


    if moderation["decision"] == "aprovado":
        img = db.session.get(Imagem, imagem_id)
        if img:
            adicionar_notificacao(img.id_utilizador, "comentario", imagem_id, img.titulo)

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

    ResultadoModeracao.query.filter_by(id_comentario=c.id).delete()
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
        # Disparar notificação de like
        img = db.session.get(Imagem, imagem_id)
        if img and tipo == "like":
            adicionar_notificacao(img.id_utilizador, "like", imagem_id, img.titulo)

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
            # Disparar notificação de like
            img = db.session.get(Imagem, imagem_id)
            if img and tipo == "like":
                adicionar_notificacao(img.id_utilizador, "like", imagem_id, img.titulo)
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


        manual_cond = Imagem.exposicoes.any(Exposicao.id == e.id)

        cond_intervalo = True
        if e.start_date and e.end_date:
            cond_intervalo = (Imagem.data_upload >= datetime.combine(e.start_date, datetime.min.time())) & (Imagem.data_upload <= datetime.combine(e.end_date, datetime.max.time()))

        if getattr(e, "usar_categorias", False) and getattr(e, "categoria_id", None):
            q = q.filter((manual_cond) | ((Imagem.id_categoria == e.categoria_id) & cond_intervalo))
        elif getattr(e, "usar_tags", False) and getattr(e, "tags_filtro", None):
            tags = [t.strip() for t in (e.tags_filtro or "").split(",") if t.strip()]
            if tags:
                tag_cond = or_(*[Imagem.tags.ilike(f"%{t}%") for t in tags])
                q = q.filter((manual_cond) | (tag_cond & cond_intervalo))
            else:
                q = q.filter((manual_cond) | cond_intervalo)
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




@app.route("/admin", methods=["GET", "POST"])
def admin():
    user = current_user()
    if not is_admin(user):
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
                c = db.session.get(Categoria, categoria_id)
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
            e = db.session.get(Exposicao, exposicao_id)
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
            e = db.session.get(Exposicao, exposicao_id)
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


@app.route("/recommendations")
@login_required
def recommendations_page():
    user = current_user()
    payload = build_recommendations(user, limit=24)
    categorias = Categoria.query.order_by(Categoria.nome).all()
    return render_template(
        "recommendations.html",
        recommendations=payload,
        categorias=categorias,
        query_text="",
        selected_categoria=None,
    )


@app.route("/api/recommendations")
def api_recommendations():
    user = current_user()
    payload = build_recommendations(user, limit=request.args.get("limit", 12, type=int))
    return jsonify({
        "images": [
            serialize_image(image, payload["reasons"].get(image.id))
            for image in payload["images"]
        ],
        "favorite_tags": payload["favorite_tags"],
        "authors": [
            {"id": author.id, "nome": author.nome, "email": author.email, "total_imagens": total}
            for _, author, total in payload["authors"]
        ],
        "expositions": [
            {"id": exposition.id, "nome": exposition.nome, "score": score}
            for score, exposition in payload["expositions"]
        ],
    })




@app.route("/admin/moderation", methods=["GET", "POST"])
@login_required
@admin_required
def admin_moderation():
    if request.method == "POST":
        comentario_id = request.form.get("comentario_id", type=int)
        action = request.form.get("action")
        comentario_obj = db.session.get(Comentario, comentario_id)
        if not comentario_obj or action not in {"aprovado", "pendente", "bloqueado"}:
            flash("Pedido de moderação inválido.", "error")
            return redirect(url_for("admin_moderation"))

        comentario_obj.estado_moderacao = action
        resultado = ResultadoModeracao.query.filter_by(id_comentario=comentario_obj.id).first()
        if resultado:
            resultado.decision = action
            resultado.processed_at = datetime.utcnow()
        else:
            db.session.add(
                ResultadoModeracao(
                    id_comentario=comentario_obj.id,
                    toxicity_score=0,
                    decision=action,
                    model_name="admin-review",
                )
            )
        db.session.commit()

        if action == "aprovado":
            img = db.session.get(Imagem, comentario_obj.id_imagem)
            if img:
                adicionar_notificacao(img.id_utilizador, "comentario", img.id, img.titulo)

        flash("Comentário atualizado.", "success")
        return redirect(url_for("admin_moderation", estado=request.args.get("estado", "pendente")))

    estado = request.args.get("estado", "pendente")
    query = (
        db.session.query(Comentario, Imagem, Utilizador, ResultadoModeracao)
        .join(Imagem, Comentario.id_imagem == Imagem.id)
        .outerjoin(Utilizador, Comentario.id_utilizador == Utilizador.id)
        .outerjoin(ResultadoModeracao, ResultadoModeracao.id_comentario == Comentario.id)
    )
    if estado != "todos":
        query = query.filter(Comentario.estado_moderacao == estado)
    rows = query.order_by(Comentario.data.desc()).limit(200).all()

    stats = {
        "pendente": Comentario.query.filter_by(estado_moderacao="pendente").count(),
        "aprovado": Comentario.query.filter_by(estado_moderacao="aprovado").count(),
        "bloqueado": Comentario.query.filter_by(estado_moderacao="bloqueado").count(),
    }
    return render_template(
        "moderation.html",
        rows=rows,
        stats=stats,
        estado=estado,
        categorias=Categoria.query.order_by(Categoria.nome).all(),
        query_text="",
        selected_categoria=None,
    )


def _apply_search_filters(query):
    q = request.args.get("q", "", type=str).strip()
    categoria_id = request.args.get("categoria", type=int)
    autor = request.args.get("autor", "", type=str).strip()
    tags = request.args.get("tags", "", type=str).strip()
    cidade = request.args.get("cidade", "", type=str).strip()
    data_inicio = request.args.get("data_inicio", "", type=str).strip()
    data_fim = request.args.get("data_fim", "", type=str).strip()

    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Imagem.titulo.ilike(like),
            Imagem.tags.ilike(like),
            Imagem.categoria_texto.ilike(like),
            Imagem.descricao.ilike(like),
            Utilizador.nome.ilike(like),
        ))
    if categoria_id:
        query = query.filter(Imagem.id_categoria == categoria_id)
    if autor:
        like = f"%{autor}%"
        query = query.filter(or_(Utilizador.nome.ilike(like), Utilizador.email.ilike(like)))
    if tags:
        for tag in [t.strip() for t in tags.split(",") if t.strip()]:
            query = query.filter(Imagem.tags.ilike(f"%{tag}%"))
    if cidade:
        query = query.filter(Localizacao.city.ilike(f"%{cidade}%"))
    if data_inicio:
        try:
            query = query.filter(Imagem.data_upload >= datetime.combine(date.fromisoformat(data_inicio), datetime.min.time()))
        except ValueError:
            pass
    if data_fim:
        try:
            query = query.filter(Imagem.data_upload <= datetime.combine(date.fromisoformat(data_fim), datetime.max.time()))
        except ValueError:
            pass
    return query


def _search_base_query():
    return (
        Imagem.query
        .outerjoin(Utilizador, Imagem.id_utilizador == Utilizador.id)
        .outerjoin(Localizacao, Imagem.id_location == Localizacao.id)
        .filter(Imagem.publica == True)
    )


def _serialize_search_image(image):
    return {
        "id": image.id,
        "titulo": image.titulo,
        "url": image.caminho_armazenamento,
        "categoria": image.categoria_texto,
        "tags": image.tags,
        "autor_id": image.id_utilizador,
        "localizacao": {
            "address": image.localizacao.address if image.localizacao else None,
            "city": image.localizacao.city if image.localizacao else None,
            "country": image.localizacao.country if image.localizacao else None,
            "latitude": image.localizacao.latitude if image.localizacao else None,
            "longitude": image.localizacao.longitude if image.localizacao else None,
        },
        "data_upload": image.data_upload.isoformat() if image.data_upload else None,
    }


@app.route("/pesquisa")
def pesquisa_avancada():
    query = _apply_search_filters(_search_base_query())
    ordenar = request.args.get("ordenar", "mais_recentes")
    if ordenar == "mais_antigas":
        query = query.order_by(Imagem.data_upload.asc())
    else:
        query = query.order_by(Imagem.data_upload.desc())
    imagens = query.limit(80).all()
    return render_template(
        "pesquisa.html",
        imagens=imagens,
        categorias=Categoria.query.order_by(Categoria.nome).all(),
        filtros=request.args,
        query_text=request.args.get("q", ""),
        selected_categoria=request.args.get("categoria", type=int),
    )


@app.route("/api/search")
def api_search():
    page = max(request.args.get("page", 1, type=int), 1)
    per = min(max(request.args.get("per", 20, type=int), 1), 100)
    ordenar = request.args.get("ordenar", "mais_recentes")
    query = _apply_search_filters(_search_base_query())

    total = query.count()
    if ordenar in {"mais_curtidas", "menos_curtidas"}:
        ids = [row.id for row in query.with_entities(Imagem.id).all()]
        if ids:
            likes_count = func.count(Reacao.id)
            rows = (
                db.session.query(Imagem)
                .outerjoin(Reacao, (Reacao.id_imagem == Imagem.id) & (Reacao.tipo == "like"))
                .filter(Imagem.id.in_(ids))
                .group_by(Imagem.id)
                .order_by(likes_count.desc() if ordenar == "mais_curtidas" else likes_count.asc())
                .offset((page - 1) * per)
                .limit(per)
                .all()
            )
        else:
            rows = []
    else:
        query = query.order_by(Imagem.data_upload.asc() if ordenar == "mais_antigas" else Imagem.data_upload.desc())
        rows = query.offset((page - 1) * per).limit(per).all()

    return jsonify({
        "total": total,
        "page": page,
        "per": per,
        "imagens": [_serialize_search_image(image) for image in rows],
    })


@app.route("/api/location/<int:image_id>")
def api_location(image_id):
    image = Imagem.query.get_or_404(image_id)
    if not image.localizacao:
        return jsonify({"error": "Esta imagem não possui localização registada."}), 404
    return jsonify({
        "latitude": image.localizacao.latitude,
        "longitude": image.localizacao.longitude,
        "address": image.localizacao.address,
        "city": image.localizacao.city,
        "country": image.localizacao.country
    })


@app.route("/api/reverse-geocode")
def reverse_geocode():
    lat = request.args.get("lat")
    lng = request.args.get("lng")
    if not lat or not lng:
        return jsonify({"error": "Latitude e Longitude são obrigatórias"}), 400
        
    import requests as py_requests
    try:
        headers = {"User-Agent": "ArteNuvem-App/1.0"}
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}"
        resp = py_requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            address_data = data.get("address", {})
            city = address_data.get("city") or address_data.get("town") or address_data.get("village") or address_data.get("municipality")
            country = address_data.get("country")
            
            # Construir uma morada limpa
            road = address_data.get("road")
            suburb = address_data.get("suburb")
            display_name = data.get("display_name", "")
            if road:
                formatted_address = f"{road}"
                if suburb:
                    formatted_address += f", {suburb}"
            else:
                formatted_address = display_name.split(",")[0]
                
            return jsonify({
                "address": formatted_address,
                "city": city,
                "country": country
            })
    except Exception as e:
        app.logger.error("Erro no reverse geocoding do Nominatim: %s", e)
        
    return jsonify({"error": "Não foi possível resolver o endereço."}), 500




@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


@app.route("/api/status")
def api_status():
    return jsonify({
        "app": "ArteNuvem",
        "status": "ok",
        "database": "configured" if app.config.get("SQLALCHEMY_DATABASE_URI") else "missing",
        "supabase": bool(supabase or supabase_service),
        "ai_moderation": "local-keyword-safety",
    })



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
            exposicao_selecionada = db.session.get(Exposicao, exposicao_id)
            if exposicao_selecionada:
                
                q = Imagem.query
                
                manual_cond = Imagem.exposicoes.any(Exposicao.id == exposicao_selecionada.id)

                cond_intervalo = True
                if exposicao_selecionada.start_date and exposicao_selecionada.end_date:
                    cond_intervalo = (Imagem.data_upload >= datetime.combine(exposicao_selecionada.start_date, datetime.min.time())) & (Imagem.data_upload <= datetime.combine(exposicao_selecionada.end_date, datetime.max.time()))

                if getattr(exposicao_selecionada, "usar_categorias", False) and getattr(exposicao_selecionada, "categoria_id", None):
                    q = q.filter((manual_cond) | ((Imagem.id_categoria == exposicao_selecionada.categoria_id) & cond_intervalo))
                elif getattr(exposicao_selecionada, "usar_tags", False) and getattr(exposicao_selecionada, "tags_filtro", None):
                    tags = [t.strip() for t in (exposicao_selecionada.tags_filtro or "").split(",") if t.strip()]
                    if tags:
                        tag_cond = or_(*[Imagem.tags.ilike(f"%{t}%") for t in tags])
                        q = q.filter((manual_cond) | (tag_cond & cond_intervalo))
                    else:
                        q = q.filter((manual_cond) | cond_intervalo)
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

    query = Imagem.query.filter(Imagem.publica == True)
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
            "descricao": getattr(img, "descricao", None),
            "id_utilizador": getattr(img, "id_utilizador", None),
            "data_upload": getattr(img, "data_upload").isoformat() if getattr(img, "data_upload", None) else None,
            "localizacao": {
                "address": img.localizacao.address if img.localizacao else None,
                "city": img.localizacao.city if img.localizacao else None,
                "country": img.localizacao.country if img.localizacao else None,
                "latitude": img.localizacao.latitude if img.localizacao else None,
                "longitude": img.localizacao.longitude if img.localizacao else None,
            }
        }

    return jsonify({
        "total": total,
        "page": page,
        "per": per,
        "imagens": [to_dict(i) for i in items]
    })


@app.route("/api/imagens/<int:imagem_id>", methods=["GET"])
def api_imagem_detalhe(imagem_id):
    img = Imagem.query.get_or_404(imagem_id)
    likes = Reacao.query.filter_by(id_imagem=imagem_id, tipo="like").count()
    comentarios = Comentario.query.filter_by(id_imagem=imagem_id, estado_moderacao="aprovado").count()
    return jsonify({
        "id": img.id,
        "titulo": img.titulo,
        "descricao": img.descricao,
        "categoria": img.categoria_texto,
        "tags": img.tags,
        "url": img.caminho_armazenamento,
        "id_utilizador": img.id_utilizador,
        "likes": likes,
        "comentarios": comentarios,
        "data_upload": img.data_upload.isoformat() if img.data_upload else None,
        "localizacao": {
            "address": img.localizacao.address if img.localizacao else None,
            "city": img.localizacao.city if img.localizacao else None,
            "country": img.localizacao.country if img.localizacao else None,
            "latitude": img.localizacao.latitude if img.localizacao else None,
            "longitude": img.localizacao.longitude if img.localizacao else None,
        },
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


@app.route("/api/v1/imagens", methods=["POST"])
@api_login_required
def api_publicar_imagem():
    user = current_user()
    
    # Obter dados de multipart/form-data
    ficheiro = request.files.get("ficheiro")
    titulo = request.form.get("titulo")
    categoria_id = request.form.get("categoria_id", type=int)
    tags = request.form.get("tags", "")
    descricao = (request.form.get("descricao") or "").strip()
    address = (request.form.get("address") or "").strip()
    city = (request.form.get("city") or "").strip()
    country = (request.form.get("country") or "").strip()
    latitude = request.form.get("latitude", type=float)
    longitude = request.form.get("longitude", type=float)

    if not ficheiro or ficheiro.filename == "":
        return jsonify({"error": "Ficheiro de imagem é obrigatório"}), 400
    if not allowed_file(ficheiro.filename):
        return jsonify({"error": "Apenas são permitidos ficheiros JPG/PNG"}), 400
    if not titulo:
        return jsonify({"error": "O título é obrigatório"}), 400

    try:
        caminho_url, object_key = upload_imagem_supabase(ficheiro)
    except Exception as e:
        app.logger.exception("Erro no upload Supabase via API: %s", e)
        return jsonify({"error": "Falha ao carregar imagem para o armazenamento na cloud"}), 500

    try:
        categoria_obj = db.session.get(Categoria, categoria_id) if categoria_id else None
        location_obj = None
        if address:
            from services.location_service import geocode_address
            geocoded = geocode_address(address)
            if geocoded:
                lat_val = latitude if latitude is not None else geocoded.get("latitude")
                lng_val = longitude if longitude is not None else geocoded.get("longitude")
                city_val = city if city else geocoded.get("city")
                country_val = country if country else geocoded.get("country")
                formatted_address = geocoded.get("formatted_address") or address
            else:
                lat_val = latitude
                lng_val = longitude
                city_val = city
                country_val = country
                formatted_address = address

            location_obj = Localizacao(
                address=formatted_address,
                city=city_val or None,
                country=country_val or None,
                latitude=lat_val,
                longitude=lng_val,
            )
            db.session.add(location_obj)
            db.session.flush()

        img = Imagem(
            titulo=titulo,
            caminho_armazenamento=caminho_url,
            categoria_texto=categoria_obj.nome if categoria_obj else None,
            id_utilizador=user.id,
            id_categoria=categoria_id if categoria_id else None,
            descricao=descricao or None,
            id_location=location_obj.id if location_obj else None,
        )

        if tags:
            img.tags = tags

        # Associar exposições se fornecidas
        exposicoes_list = request.form.getlist("exposicoes")
        for eid in exposicoes_list:
            try:
                exp_obj = db.session.get(Exposicao, int(eid))
                if exp_obj:
                    img.exposicoes.append(exp_obj)
            except Exception:
                continue

        db.session.add(img)
        db.session.commit()

        # Resposta JSON estruturada
        return jsonify({
            "success": True,
            "message": "Obra publicada com sucesso!",
            "data": {
                "id": img.id,
                "titulo": img.titulo,
                "caminho_armazenamento": img.caminho_armazenamento,
                "categoria": img.categoria_texto,
                "tags": img.tags,
                "descricao": img.descricao,
                "id_utilizador": img.id_utilizador,
                "data_upload": img.data_upload.isoformat() if img.data_upload else None,
                "localizacao": {
                    "id": location_obj.id if location_obj else None,
                    "address": location_obj.address if location_obj else None,
                    "city": location_obj.city if location_obj else None,
                    "country": location_obj.country if location_obj else None,
                    "latitude": location_obj.latitude if location_obj else None,
                    "longitude": location_obj.longitude if location_obj else None,
                } if location_obj else None
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        app.logger.exception("Erro ao guardar imagem na DB via API: %s", e)
        return jsonify({"error": "Erro ao gravar dados da obra no servidor"}), 500


@app.route("/api/v1/imagens/<int:imagem_id>", methods=["DELETE"])
@api_login_required
def api_apagar_imagem(imagem_id):
    user = current_user()
    img = Imagem.query.get_or_404(imagem_id)
    user_email = (user.email or "").strip().lower() if user else ""
    
    if not user or not (user.id == img.id_utilizador or (ADMIN_EMAILS and user_email in ADMIN_EMAILS)):
        return jsonify({"error": "Não tens permissão para apagar esta imagem"}), 403

    try:
        # Apagar dependências
        comentario_ids = [
            row.id
            for row in Comentario.query.filter_by(id_imagem=imagem_id)
            .with_entities(Comentario.id)
            .all()
        ]
        if comentario_ids:
            ResultadoModeracao.query.filter(
                ResultadoModeracao.id_comentario.in_(comentario_ids)
            ).delete(synchronize_session=False)
        Comentario.query.filter_by(id_imagem=imagem_id).delete()
        Reacao.query.filter_by(id_imagem=imagem_id).delete()
        Notification.query.filter_by(id_imagem=imagem_id).delete()
        
        # Limpar associações Many-to-Many
        img.exposicoes = []

        # Tentar apagar ficheiro local (se existir)
        try:
            caminho_relativo = (img.caminho_armazenamento or "").lstrip("/")
            caminho_ficheiro = os.path.join(app.root_path, caminho_relativo)
            if os.path.exists(caminho_ficheiro):
                os.remove(caminho_ficheiro)
        except Exception:
            pass

        db.session.delete(img)
        db.session.commit()

        # Apagar do Supabase
        try:
            if img.caminho_armazenamento and supabase_service:
                object_key = img.caminho_armazenamento.rstrip("/").split("/")[-1]
                supabase_service.storage.from_(SUPABASE_BUCKET).remove([object_key])
        except Exception:
            pass

        return jsonify({
            "success": True,
            "message": "Imagem apagada com sucesso do sistema e armazenamento na cloud."
        }), 200

    except Exception as e:
        db.session.rollback()
        app.logger.exception("Erro ao apagar imagem via API: %s", e)
        return jsonify({"error": "Erro interno ao tentar apagar a imagem"}), 500


@app.route("/api/v1/comentarios", methods=["POST"])
@api_login_required
def api_criar_comentario():
    user = current_user()
    data = request.get_json() or {}
    
    texto = (data.get("texto") or "").strip()
    imagem_id = data.get("imagem_id")

    if not texto or len(texto) > 140:
        return jsonify({"error": "Comentário inválido ou demasiado longo (máx. 140 caracteres)"}), 400
    if not imagem_id:
        return jsonify({"error": "ID da imagem é obrigatório"}), 400

    img = db.session.get(Imagem, imagem_id)
    if not img:
        return jsonify({"error": "Imagem não encontrada"}), 442

    try:
        moderation = avaliar_comentario(texto)
    except Exception as e:
        app.logger.exception("Erro ao chamar moderador IA via API: %s", e)
        moderation = {
            "decision": "aprovado",
            "toxicity_score": 0,
            "model_name": "local-keyword-safety",
        }

    try:
        c = Comentario(
            texto=texto,
            id_imagem=imagem_id,
            id_utilizador=user.id,
            estado_moderacao=moderation["decision"],
        )
        db.session.add(c)
        db.session.flush()

        res_mod = ResultadoModeracao(
            id_comentario=c.id,
            toxicity_score=moderation.get("toxicity_score", 0),
            decision=moderation["decision"],
            model_name=moderation.get("model_name", "local-keyword-safety"),
            motivo=moderation.get("motivo"),
        )
        db.session.add(res_mod)
        db.session.commit()

        # Disparar notificação apenas se aprovado
        if moderation["decision"] == "aprovado":
            adicionar_notificacao(img.id_utilizador, "comentario", imagem_id, img.titulo)

        msg = "Comentário adicionado com sucesso!"
        if moderation["decision"] == "pendente":
            msg = "Comentário enviado para revisão automática de segurança."
        elif moderation["decision"] == "bloqueado":
            msg = "Comentário bloqueado automaticamente por conter conteúdo inadequado."

        return jsonify({
            "success": True if moderation["decision"] != "bloqueado" else False,
            "message": msg,
            "data": {
                "id": c.id,
                "texto": c.texto,
                "data": c.data.isoformat() if c.data else None,
                "id_imagem": c.id_imagem,
                "id_utilizador": c.id_utilizador,
                "estado_moderacao": c.estado_moderacao,
                "moderacao": {
                    "toxicity_score": float(res_mod.toxicity_score),
                    "decision": res_mod.decision,
                    "model_name": res_mod.model_name,
                    "motivo": res_mod.motivo
                }
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        app.logger.exception("Erro ao guardar comentário via API: %s", e)
        return jsonify({"error": "Erro ao gravar comentário no servidor"}), 500


@app.route("/api/v1/comentarios/<int:comentario_id>", methods=["DELETE"])
@api_login_required
def api_apagar_comentario(comentario_id):
    user = current_user()
    c = Comentario.query.get_or_404(comentario_id)
    user_email = (user.email or "").strip().lower() if user else ""
    
    if not user or not (user.id == c.id_utilizador or (ADMIN_EMAILS and user_email in ADMIN_EMAILS)):
        return jsonify({"error": "Não tens permissão para apagar este comentário"}), 403

    try:
        ResultadoModeracao.query.filter_by(id_comentario=c.id).delete()
        db.session.delete(c)
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Comentário apagado com sucesso."
        }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Erro ao apagar comentário via API: %s", e)
        return jsonify({"error": "Erro interno ao tentar apagar o comentário"}), 500


@app.route("/api/v1/reacoes/toggle", methods=["POST"])
@api_login_required
def api_reacao_toggle():
    data = request.get_json() or {}
    imagem_id = data.get("imagem_id")
    tipo = data.get("tipo", "like")

    if not imagem_id:
        return jsonify({"error": "ID da imagem é obrigatório"}), 400

    user = current_user()
    
    existente = Reacao.query.filter_by(
        tipo=tipo,
        id_imagem=imagem_id,
        id_utilizador=user.id
    ).first()

    try:
        if existente:
            db.session.delete(existente)
            db.session.commit()
            status = "unliked"
        else:
            nova = Reacao(tipo=tipo, id_imagem=imagem_id, id_utilizador=user.id)
            db.session.add(nova)
            db.session.commit()
            status = "liked"
            
            # Disparar notificação de like
            img = db.session.get(Imagem, imagem_id)
            if img and tipo == "like":
                adicionar_notificacao(img.id_utilizador, "like", imagem_id, img.titulo)

        likes = Reacao.query.filter_by(id_imagem=imagem_id, tipo="like").count()
        return jsonify({
            "success": True,
            "status": status,
            "likes": likes
        }), 200

    except Exception as e:
        db.session.rollback()
        app.logger.exception("Erro ao alternar reação via API: %s", e)
        return jsonify({"error": "Erro no banco de dados"}), 500


@app.route("/api/v1/imagens/localizacoes", methods=["GET"])
def api_imagens_localizacoes():
    imagens = Imagem.query.filter(Imagem.id_location.isnot(None), Imagem.publica == True).all()
    data = []
    for img in imagens:
        if img.localizacao:
            data.append({
                "id_imagem": img.id,
                "titulo": img.titulo,
                "url": img.caminho_armazenamento,
                "categoria": img.categoria_texto,
                "localizacao": {
                    "id_location": img.localizacao.id,
                    "address": img.localizacao.address,
                    "city": img.localizacao.city,
                    "country": img.localizacao.country,
                    "latitude": img.localizacao.latitude,
                    "longitude": img.localizacao.longitude
                }
            })
    return jsonify(data), 200

@app.route("/api/v1/imagens/<int:imagem_id>/localizacao", methods=["GET"])
def api_imagem_localizacao(imagem_id):
    img = Imagem.query.get_or_404(imagem_id)
    if not img.localizacao:
        return jsonify({"error": "Esta imagem não possui localização registada."}), 404
    return jsonify({
        "id_imagem": img.id,
        "id_location": img.localizacao.id,
        "address": img.localizacao.address,
        "city": img.localizacao.city,
        "country": img.localizacao.country,
        "latitude": img.localizacao.latitude,
        "longitude": img.localizacao.longitude
    }), 200

@app.route("/api/v1/reverse-geocode", methods=["GET"])
def api_v1_reverse_geocode():
    lat = request.args.get("lat")
    lng = request.args.get("lng")
    if not lat or not lng:
        return jsonify({"error": "Latitude e Longitude são obrigatórias"}), 400
        
    import requests as py_requests
    try:
        headers = {"User-Agent": "ArteNuvem-App/1.0"}
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}"
        resp = py_requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            address_data = data.get("address", {})
            city = address_data.get("city") or address_data.get("town") or address_data.get("village") or address_data.get("municipality")
            country = address_data.get("country")
            
            # Construir uma morada limpa
            road = address_data.get("road")
            suburb = address_data.get("suburb")
            display_name = data.get("display_name", "")
            if road:
                formatted_address = f"{road}"
                if suburb:
                    formatted_address += f", {suburb}"
            else:
                formatted_address = display_name.split(",")[0]
                
            return jsonify({
                "address": formatted_address,
                "city": city,
                "country": country
            }), 200
    except Exception as e:
        app.logger.error("Erro no reverse geocoding do Nominatim via API v1: %s", e)
        
    return jsonify({"error": "Não foi possível resolver o endereço."}), 500

@app.route("/api/v1/public/estatisticas", methods=["GET"])
def api_public_estatisticas():
    try:
        total_utilizadores = Utilizador.query.count()
        total_imagens = Imagem.query.filter_by(publica=True).count()
        total_comentarios = Comentario.query.count()
        total_categorias = Categoria.query.count()
        total_exposicoes = Exposicao.query.filter_by(ativo=True).count()
        
        return jsonify({
            "status": "success",
            "dados": {
                "total_utilizadores": total_utilizadores,
                "total_imagens": total_imagens,
                "total_comentarios": total_comentarios,
                "total_categorias": total_categorias,
                "total_exposicoes_ativas": total_exposicoes
            }
        }), 200
    except Exception as e:
        app.logger.exception("Erro ao obter estatísticas públicas: %s", e)
        return jsonify({"status": "error", "message": "Erro ao consultar a base de dados"}), 500

@app.route("/estatisticas")
def public_estatisticas():
    return render_template(
        "estatisticas.html",
        categorias=Categoria.query.all(),
        query_text="",
        selected_categoria=None
    )

@app.route("/api/v1/public/utilizadores/pesquisa", methods=["GET"])
def api_pesquisa_utilizadores():
    try:
        q = request.args.get("q", "").strip()
        if not q:
            return jsonify([]), 200
        utilizadores = Utilizador.query.filter(Utilizador.nome.ilike(f"%{q}%")).all()
        res = [{"id": u.id, "nome": u.nome, "foto_url": u.foto_url} for u in utilizadores]
        return jsonify(res), 200
    except Exception as e:
        app.logger.exception("Erro ao pesquisar utilizadores: %s", e)
        return jsonify({"status": "error", "message": "Erro ao pesquisar utilizadores"}), 500

@app.route("/api/v1/public/estatisticas/utilizador/<int:user_id>", methods=["GET"])
def api_public_estatisticas_utilizador(user_id):
    try:
        user = db.session.get(Utilizador, user_id)
        if not user:
            return jsonify({"status": "error", "message": "Utilizador não encontrado"}), 404
            
        user_imgs = Imagem.query.filter_by(id_utilizador=user.id, publica=True).all()
        total_imagens = len(user_imgs)
        
        # Calcular likes e comentários totais nas imagens públicas dele
        total_likes = db.session.query(func.count(Reacao.id))\
            .join(Imagem, Reacao.id_imagem == Imagem.id)\
            .filter(Imagem.id_utilizador == user.id, Imagem.publica == True, Reacao.tipo == 'like')\
            .scalar() or 0
            
        total_comentarios = db.session.query(func.count(Comentario.id))\
            .join(Imagem, Comentario.id_imagem == Imagem.id)\
            .filter(Imagem.id_utilizador == user.id, Imagem.publica == True)\
            .scalar() or 0
            
        avg_likes = round(total_likes / total_imagens, 1) if total_imagens > 0 else 0.0
        
        # Encontrar imagem mais popular (com mais likes)
        most_popular = None
        max_likes = -1
        for img in user_imgs:
            l_count = Reacao.query.filter_by(id_imagem=img.id, tipo='like').count()
            if l_count > max_likes:
                max_likes = l_count
                most_popular = {
                    "id": img.id,
                    "titulo": img.titulo,
                    "url": img.caminho_armazenamento,
                    "likes": l_count
                }
                
        # Distribuição de categorias
        cat_counts = {}
        for img in user_imgs:
            cat = img.categoria_texto or "Sem Categoria"
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
            
        return jsonify({
            "status": "success",
            "dados": {
                "utilizador_id": user.id,
                "nome": user.nome,
                "foto_url": user.foto_url,
                "total_imagens": total_imagens,
                "total_likes": total_likes,
                "total_comentarios": total_comentarios,
                "avg_likes_por_imagem": avg_likes,
                "imagem_mais_popular": most_popular,
                "categorias_distribuicao": cat_counts
            }
        }), 200
    except Exception as e:
        app.logger.exception("Erro ao obter estatísticas do utilizador %d: %s", user_id, e)
        return jsonify({"status": "error", "message": "Erro ao processar as estatísticas"}), 500

@app.route("/api/v1/notificacoes", methods=["GET"])
@api_login_required
def api_listar_notificacoes():
    user = current_user()
    notifs = Notification.query.filter_by(id_utilizador=user.id).order_by(Notification.created_at.desc()).all()
    
    data = []
    for n in notifs:
        data.append({
            "id": n.id,
            "type": n.type,
            "message": n.message,
            "count": n.count,
            "is_read": n.is_read,
            "id_imagem": n.id_imagem,
            "created_at": n.created_at.isoformat() if n.created_at else None
        })
    return jsonify(data), 200

@app.route("/api/v1/notificacoes/<int:notif_id>/ler", methods=["PUT"])
@api_login_required
def api_ler_notificacao(notif_id):
    user = current_user()
    notif = Notification.query.get_or_404(notif_id)
    if notif.id_utilizador != user.id:
        return jsonify({"error": "Não tens permissão para aceder a esta notificação."}), 403
    
    notif.is_read = True
    db.session.commit()
    return jsonify({
        "success": True,
        "message": f"Notificação {notif_id} marcada como lida."
    }), 200

@app.route("/api/v1/notificacoes", methods=["DELETE"])
@api_login_required
def api_limpar_notificacoes():
    user = current_user()
    try:
        Notification.query.filter_by(id_utilizador=user.id).delete()
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Todas as notificações do utilizador foram limpas."
        }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Erro ao limpar notificações via API: %s", e)
        return jsonify({"error": "Erro no banco de dados"}), 500

@app.route("/api/v1/notificacoes/pausar", methods=["POST"])
@api_login_required
def api_pausar_notificacoes():
    from datetime import timedelta
    user = current_user()
    data = request.get_json() or {}
    duracao = data.get("duracao") # em minutos

    if duracao is None or not isinstance(duracao, int) or duracao < 0:
        return jsonify({"error": "Duração inválida (deve ser um inteiro >= 0)"}), 400

    try:
        if duracao == 0:
            user.notifications_paused_until = None
            message = "Notificações reativadas."
        else:
            paused_until = datetime.utcnow() + timedelta(minutes=duracao)
            user.notifications_paused_until = paused_until
            message = f"Notificações pausadas por {duracao} minutos."

        db.session.commit()
        return jsonify({
            "success": True,
            "message": message,
            "notifications_paused_until": user.notifications_paused_until.isoformat() if user.notifications_paused_until else None
        }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Erro ao pausar notificações via API: %s", e)
        return jsonify({"error": "Erro interno do servidor"}), 500


@app.route("/notificacoes/ler/<int:notif_id>", methods=["POST"])
@login_required
def ler_notificacao(notif_id):
    user = current_user()
    notif = Notification.query.get_or_404(notif_id)
    if notif.id_utilizador != user.id:
        return jsonify({"error": "Unauthorized"}), 403
    
    notif.is_read = True
    db.session.commit()
    return jsonify({"status": "success"})

@app.route("/notificacoes/limpar", methods=["POST"])
@login_required
def limpar_notificacoes():
    user = current_user()
    Notification.query.filter_by(id_utilizador=user.id).delete()
    db.session.commit()
    flash("Lista de notificações limpa.", "success")
    return redirect(request.referrer or url_for("index"))

@app.route("/notificacoes/pausar", methods=["POST"])
@login_required
def pausar_notificacoes():
    from datetime import timedelta
    user = current_user()
    duracao = request.form.get("duracao", type=int)
    
    if duracao is None or duracao < 0:
        flash("Duração inválida.", "error")
        return redirect(request.referrer or url_for("index"))
    
    if duracao == 0:
        user.notifications_paused_until = None
        flash("Notificações reativadas.", "success")
    else:
        user.notifications_paused_until = datetime.utcnow() + timedelta(minutes=duracao)
        if duracao < 60:
            tempo_str = f"{duracao} minutos"
        elif duracao == 60:
            tempo_str = "1 hora"
        elif duracao == 480:
            tempo_str = "8 horas"
        elif duracao == 1440:
            tempo_str = "24 horas"
        else:
            tempo_str = f"{duracao // 60} horas"
        flash(f"Notificações pausadas por {tempo_str}.", "success")
        
    db.session.commit()
    return redirect(request.referrer or url_for("index"))

@app.route("/login")
def login():
    redirect_uri = url_for("google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/login/google/callback")
def google_callback():
    try:
        google.authorize_access_token()
        resp = google.get("userinfo")
        resp.raise_for_status()
        user_info = resp.json()
    except Exception as e:
        app.logger.exception("Erro no login com Google: %s", e)
        flash("Erro ao iniciar sessao com o Google. Tenta de novo.", "error")
        return redirect(url_for("index"))

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
        db.session.flush()
        
        # Criar preferências de notificação padrão para o novo utilizador
        prefs = PreferenciaNotificacao(
            id_utilizador=user.id,
            email_boas_vindas=True,
            email_likes=True,
            email_comentarios=True,
            email_recomendacoes=False,
            email_ativo=True
        )
        db.session.add(prefs)
        db.session.commit()
    else:
        user.google_id = user.google_id or google_id
        user.nome = user.nome or nome
        user.foto_url = user.foto_url or foto
        db.session.commit()

    # Enviar email de boas-vindas se for o primeiro login
    try:
        send_welcome_email(user)
    except Exception as e:
        app.logger.error("Erro ao enviar email de boas-vindas: %s", e)

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

@app.route("/email-settings", methods=["GET", "POST"])
@login_required
def email_settings():
    user = current_user()
    prefs = get_or_create_preferences(user)
    
    if request.method == "POST":
        prefs.email_recomendacoes = bool(request.form.get("email_recomendacoes"))
        prefs.email_ativo = True
        prefs.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash("Preferências de email atualizadas com sucesso.", "success")
        except Exception as e:
            db.session.rollback()
            app.logger.exception("Erro ao guardar preferências de email: %s", e)
            flash("Erro ao guardar preferências de email.", "error")
            
        return redirect(url_for("email_settings"))
        
    return render_template("email_settings.html", prefs=prefs, categorias=Categoria.query.all(), query_text="", selected_categoria=None)


@app.route("/perfil/<int:imagem_id>")
def perfil(imagem_id: int):
    user = Utilizador.query.get_or_404(imagem_id)
    imagens = Imagem.query.filter_by(id_utilizador=user.id).order_by(Imagem.data_upload.desc()).all()
    
    total_likes = (
        db.session.query(func.count(Reacao.id))
        .join(Imagem, Reacao.id_imagem == Imagem.id)
        .filter(Imagem.id_utilizador == user.id, Reacao.tipo == "like")
        .scalar() or 0
    )
    
    return render_template(
        "perfil.html", 
        user=user, 
        imagens=imagens, 
        total_likes=total_likes, 
        categorias=Categoria.query.all(), 
        query_text="", 
        selected_categoria=None
    )

@app.route("/perfil/editar", methods=["GET", "POST"])
@login_required
def editar_perfil():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("O nome não pode ficar vazio.", "error")
            return redirect(url_for("editar_perfil"))
        user.nome = nome

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


@app.route("/admin/ver_base_dados")
@login_required
def ver_base_dados():
    user = current_user()
    user_email = (user.email or "").strip().lower() if user else ""
    if not user or (ADMIN_EMAILS and user_email not in ADMIN_EMAILS):
        return "Acesso negado.", 403

    dados = {}

    try:
        # 1. Utilizadores (Inclui foto_url)
        dados["utilizadores"] = [
            {
                "id": u.id, 
                "nome": u.nome, 
                "email": u.email, 
                "google_id": u.google_id,
                "foto_url": u.foto_url
            } 
            for u in Utilizador.query.order_by(Utilizador.id).all()
        ]
        
        # 2. Categorias
        dados["categorias"] = [{"id": c.id, "nome": c.nome} for c in Categoria.query.order_by(Categoria.id).all()]
        
        # 3. Exposições (Inclui imagem_destaque)
        expos = []
        for e in Exposicao.query.order_by(Exposicao.id).all():
            expos.append({
                "id": e.id, 
                "nome": e.nome, 
                "ativo": e.ativo,
                "mes": e.mes,
                "mes_inteiro": e.mes_inteiro,
                "datas": f"{e.start_date} a {e.end_date}" if e.start_date else "N/A",
                "descricao": e.descricao,
                "img_destaque": e.imagem_destaque,
                "usar_tags": e.usar_tags,
                "tags_filtro": e.tags_filtro,
                "usar_cats": e.usar_categorias,
                "cat_id": e.categoria_id,
                "cats_ids": e.categorias_ids
            })
        dados["exposicoes"] = expos

        # 4. Imagens (Inclui caminho_armazenamento)
        imgs = []
        for i in Imagem.query.order_by(Imagem.id).all():
            ids_expos = [e.id for e in i.exposicoes] 
            imgs.append({
                "id": i.id, 
                "titulo": i.titulo, 
                "autor_id": i.id_utilizador, 
                "cat_id": i.id_categoria, 
                "cat_txt": i.categoria_texto,
                "tags": i.tags,
                "caminho": i.caminho_armazenamento,
                "data": i.data_upload,
                "exposicoes": str(ids_expos)
            })
        dados["imagens"] = imgs

        # 5. Comentários
        dados["comentarios"] = [
            {
                "id": c.id, 
                "texto": c.texto, 
                "img_id": c.id_imagem, 
                "user_id": c.id_utilizador, 
                "data": c.data
            } 
            for c in Comentario.query.order_by(Comentario.id).all()
        ]
        
        # 6. Reações
        dados["reacoes"] = [
            {"id": r.id, "tipo": r.tipo, "img_id": r.id_imagem, "user_id": r.id_utilizador}
            for r in Reacao.query.order_by(Reacao.id).all()
        ]

        # 7. Tabela Intermédia
        associacoes = db.session.query(imagem_exposicao).all()
        dados["associacoes"] = [
            {"img_id": row[0], "exp_id": row[1]} for row in associacoes
        ]
        
    except Exception as e:
        return f"Erro ao ler base de dados: {str(e)}"

    formato = request.args.get("format", "tabela")

    if formato == "json":
        return jsonify(dados)

    html_template = """
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <title>Debug Base de Dados Completa</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; background: #f0f2f5; font-size: 13px; margin: 0; }
            h1 { color: #333; text-align: center; margin-bottom: 20px; }
            
            /* Estilo dos Títulos das Tabelas */
            h2 { 
                border-left: 5px solid #007bff; 
                padding-left: 10px; 
                margin-top: 40px; 
                color: #2c3e50; 
                background: #e9ecef; 
                padding: 10px; 
                border-radius: 0 5px 5px 0;
            }
            
            /* Container Responsivo para não esmagar as colunas */
            .table-responsive {
                width: 100%;
                overflow-x: auto; 
                margin-bottom: 20px;
                background: white;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                border-radius: 5px;
            }

            table { 
                width: 100%; 
                border-collapse: collapse; 
                min-width: 900px; /* Garante largura mínima para leitura */
            }
            
            th, td { 
                padding: 12px 15px; 
                border-bottom: 1px solid #ddd; 
                text-align: left; 
                white-space: nowrap; /* Impede quebra de linha nas células */
            }
            
            th { background-color: #343a40; color: white; position: sticky; top: 0; }
            tr:nth-child(even) { background-color: #f8f9fa; }
            tr:hover { background-color: #e2e6ea; }
            
            .nav { margin-bottom: 30px; text-align: center; }
            .btn { 
                text-decoration: none; 
                background: #333; 
                color: white; 
                padding: 10px 20px; 
                border-radius: 5px; 
                margin: 0 10px; 
                font-weight: bold;
            }
            .btn:hover { background-color: #555; }
            .count { font-size: 0.8em; color: #666; font-weight: normal; margin-left: 10px; }
            
            .true { color: green; font-weight: bold; }
            .false { color: red; font-weight: bold; }
            
            /* Coluna para URLs longos */
            .url-col { 
                max-width: 250px; 
                overflow: hidden; 
                text-overflow: ellipsis; 
                color: #007bff;
            }
        </style>
    </head>
    <body>
        <h1>🔍 Base de Dados Completa</h1>
        <div class="nav">
            <a href="/" class="btn">← Voltar ao Site</a>
            <a href="?format=json" class="btn" style="background:#17a2b8;">Ver JSON Bruto</a>
        </div>

        <h2>1. Utilizador <span class="count">({{ dados.utilizadores|length }})</span></h2>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Nome</th>
                        <th>Email</th>
                        <th>Tipo</th>
                        <th>Google ID</th>
                        <th>Foto Perfil (URL)</th> </tr>
                </thead>
                <tbody>
                    {% for u in dados.utilizadores %}
                    <tr>
                        <td>{{ u.id }}</td>
                        <td>{{ u.nome }}</td>
                        <td>{{ u.email }}</td>
                        <td>{{ u.tipo }}</td>
                        <td>{{ u.google_id }}</td>
                        <td class="url-col" title="{{ u.foto_url }}">{{ u.foto_url }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <h2>2. Categoria <span class="count">({{ dados.categorias|length }})</span></h2>
        <div class="table-responsive">
            <table>
                <thead><tr><th>ID</th><th>Nome</th></tr></thead>
                <tbody>
                    {% for c in dados.categorias %}
                    <tr><td>{{ c.id }}</td><td>{{ c.nome }}</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <h2>3. Exposição <span class="count">({{ dados.exposicoes|length }})</span></h2>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>ID</th><th>Nome</th><th>Ativo</th>
                        <th>Imagem Destaque (URL)</th> <th>Datas</th><th>Mês/Ano</th><th>Mes Int.</th>
                        <th>Desc.</th><th>Tags (Bool)</th><th>Filtro Tags</th>
                        <th>Cats (Bool)</th><th>Cat ID</th><th>Lista Cats</th>
                    </tr>
                </thead>
                <tbody>
                    {% for e in dados.exposicoes %}
                    <tr>
                        <td>{{ e.id }}</td>
                        <td>{{ e.nome }}</td>
                        <td class="{{ 'true' if e.ativo else 'false' }}">{{ 'SIM' if e.ativo else 'NÃO' }}</td>
                        <td class="url-col" title="{{ e.img_destaque }}">{{ e.img_destaque }}</td>
                        <td>{{ e.datas }}</td>
                        <td>{{ e.mes }}</td>
                        <td>{{ e.mes_inteiro }}</td>
                        <td class="url-col" title="{{ e.descricao }}">{{ e.descricao }}</td>
                        <td>{{ e.usar_tags }}</td>
                        <td>{{ e.tags_filtro }}</td>
                        <td>{{ e.usar_cats }}</td>
                        <td>{{ e.cat_id }}</td>
                        <td>{{ e.cats_ids }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <h2>4. Imagem <span class="count">({{ dados.imagens|length }})</span></h2>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>ID</th><th>Título</th>
                        <th>Caminho (URL Supabase)</th> <th>Autor ID</th><th>Cat ID</th><th>Cat (Txt)</th>
                        <th>Tags</th><th>Data</th><th>Exposições (N:M)</th>
                    </tr>
                </thead>
                <tbody>
                    {% for i in dados.imagens %}
                    <tr>
                        <td>{{ i.id }}</td>
                        <td>{{ i.titulo }}</td>
                        <td class="url-col" title="{{ i.caminho }}">{{ i.caminho }}</td>
                        <td>{{ i.autor_id }}</td>
                        <td>{{ i.cat_id }}</td>
                        <td>{{ i.cat_txt }}</td>
                        <td>{{ i.tags }}</td>
                        <td>{{ i.data }}</td>
                        <td>{{ i.exposicoes }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <h2 style="color: #d35400;">5. Imagem_Exposicao (Tabela Intermédia) <span class="count">({{ dados.associacoes|length }})</span></h2>
        <div class="table-responsive">
            <table>
                <thead><tr><th>ID Imagem</th><th>ID Exposição</th></tr></thead>
                <tbody>
                    {% for a in dados.associacoes %}
                    <tr><td>{{ a.img_id }}</td><td>{{ a.exp_id }}</td></tr>
                    {% else %}
                    <tr><td colspan="2">Sem associações registadas.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <h2>6. Comentário <span class="count">({{ dados.comentarios|length }})</span></h2>
        <div class="table-responsive">
            <table>
                <thead><tr><th>ID</th><th>Texto</th><th>Img ID</th><th>User ID</th><th>Data</th></tr></thead>
                <tbody>
                    {% for c in dados.comentarios %}
                    <tr>
                        <td>{{ c.id }}</td>
                        <td>{{ c.texto }}</td>
                        <td>{{ c.img_id }}</td>
                        <td>{{ c.user_id }}</td>
                        <td>{{ c.data }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <h2>7. Reação <span class="count">({{ dados.reacoes|length }})</span></h2>
        <div class="table-responsive">
            <table>
                <thead><tr><th>ID</th><th>Tipo</th><th>Img ID</th><th>User ID</th></tr></thead>
                <tbody>
                    {% for r in dados.reacoes %}
                    <tr>
                        <td>{{ r.id }}</td>
                        <td>{{ r.tipo }}</td>
                        <td>{{ r.img_id }}</td>
                        <td>{{ r.user_id }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <br><br>
    </body>
    </html>
    """
    return render_template_string(html_template, dados=dados)

@app.route("/api/sugestao_ia", methods=["POST"])
@login_required
def api_sugestao_ia():
    data = request.get_json() or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "A descrição da ideia não pode estar vazia."}), 400
    
    if len(prompt) > 500:
        return jsonify({"error": "A ideia é demasiado longa (máx. 500 caracteres)."}), 400
        
    resultado = gerar_sugestao_obra(prompt)
    if "error" in resultado:
        return jsonify({"error": resultado["error"]}), 500
        
    return jsonify(resultado)

@app.route("/api/testar")
def api_testar():
    """
    Página 'Cliente' para testar os Web Services.
    Isto simula um site externo a consumir a tua API.
    """
    return render_template("api_tester.html")
    
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
