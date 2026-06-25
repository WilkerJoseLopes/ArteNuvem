from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import desc, func

from models import Categoria, Comentario, Exposicao, Imagem, Reacao, Utilizador, db, imagem_exposicao, Notification


def _last_days_labels(days=7):
    today = datetime.utcnow().date()
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def _count_by_day(items, date_attr, labels):
    counter = Counter()
    for item in items:
        value = getattr(item, date_attr, None)
        if value:
            counter[value.date()] += 1
    return [counter[label] for label in labels]


def build_dashboard_data(user_id):
    labels = _last_days_labels(7)
    since = datetime.combine(labels[0], datetime.min.time())

    # User's uploaded images during the last 7 days
    recent_images = Imagem.query.filter(
        Imagem.data_upload >= since, 
        Imagem.id_utilizador == user_id
    ).all()
    
    # Comments received on user's public images during the last 7 days
    recent_comments = (
        Comentario.query.join(Imagem, Comentario.id_imagem == Imagem.id)
        .filter(Comentario.data >= since, Imagem.id_utilizador == user_id)
        .all()
    )

    # User's images ordered by likes count
    top_images = (
        db.session.query(Imagem, func.count(Reacao.id).label("likes"))
        .outerjoin(Reacao, (Reacao.id_imagem == Imagem.id) & (Reacao.tipo == "like"))
        .filter(Imagem.id_utilizador == user_id)
        .group_by(Imagem.id)
        .order_by(desc("likes"), Imagem.data_upload.desc())
        .limit(8)
        .all()
    )

    # User's category distribution
    top_categories = (
        db.session.query(Categoria.nome, func.count(Imagem.id).label("total"))
        .join(Imagem, Imagem.id_categoria == Categoria.id)
        .filter(Imagem.id_utilizador == user_id)
        .group_by(Categoria.id, Categoria.nome)
        .order_by(desc("total"), Categoria.nome)
        .limit(8)
        .all()
    )

    # User's exposures distribution
    exposure_rows = (
        db.session.query(Exposicao, func.count(imagem_exposicao.c.ID_Imagem).label("total"))
        .join(imagem_exposicao, imagem_exposicao.c.ID_Exposicao == Exposicao.id)
        .join(Imagem, imagem_exposicao.c.ID_Imagem == Imagem.id)
        .filter(Imagem.id_utilizador == user_id)
        .group_by(Exposicao.id)
        .order_by(desc("total"), Exposicao.id.desc())
        .limit(5)
        .all()
    )

    # Totals specific to the user
    total_uploads = Imagem.query.filter_by(id_utilizador=user_id).count()
    
    total_likes_received = (
        db.session.query(func.count(Reacao.id))
        .join(Imagem, Reacao.id_imagem == Imagem.id)
        .filter(Imagem.id_utilizador == user_id, Reacao.tipo == "like")
        .scalar() or 0
    )
    
    total_comments_received = (
        db.session.query(func.count(Comentario.id))
        .join(Imagem, Comentario.id_imagem == Imagem.id)
        .filter(Imagem.id_utilizador == user_id)
        .scalar() or 0
    )
    
    total_likes_given = Reacao.query.filter_by(id_utilizador=user_id, tipo="like").count()
    unread_notifs = Notification.query.filter_by(id_utilizador=user_id, is_read=False).count()

    totals = {
        "uploads": total_uploads,
        "likes": total_likes_received,
        "comentarios": total_comments_received,
        "gostos_dados": total_likes_given,
        "unread_notifs": unread_notifs,
    }

    return {
        "totals": totals,
        "top_images": top_images,
        "top_categories": top_categories,
        "top_expositions": exposure_rows,
        "activity": {
            "labels": [label.strftime("%d/%m") for label in labels],
            "uploads": _count_by_day(recent_images, "data_upload", labels),
            "comentarios": _count_by_day(recent_comments, "data", labels),
        },
    }


def serialize_dashboard(data):
    return {
        "totals": data["totals"],
        "top_images": [
            {
                "id": image.id,
                "titulo": image.titulo,
                "likes": int(likes),
                "url": image.caminho_armazenamento,
            }
            for image, likes in data["top_images"]
        ],
        "top_categories": [
            {"nome": nome, "total": int(total)}
            for nome, total in data["top_categories"]
        ],
        "top_expositions": [
            {"id": exposition.id, "nome": exposition.nome, "total_imagens": int(total)}
            for exposition, total in data["top_expositions"]
        ],
        "activity": data["activity"],
    }
