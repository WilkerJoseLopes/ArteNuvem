from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import desc, func

from models import Comentario, Exposicao, Imagem, Reacao, Utilizador, db


def split_tags(value):
    return [tag.strip().lower() for tag in (value or "").split(",") if tag.strip()]


def _counts_by_image(model, image_ids):
    if not image_ids:
        return {}
    rows = (
        db.session.query(model.id_imagem, func.count(model.id).label("total"))
        .filter(model.id_imagem.in_(image_ids))
        .group_by(model.id_imagem)
        .all()
    )
    return {image_id: int(total) for image_id, total in rows}


def _interaction_profile(user):
    if not user:
        return Counter(), Counter(), Counter(), set()

    liked_ids = [
        row.id_imagem
        for row in Reacao.query.filter_by(id_utilizador=user.id, tipo="like")
        .with_entities(Reacao.id_imagem)
        .all()
    ]
    commented_ids = [
        row.id_imagem
        for row in Comentario.query.filter_by(id_utilizador=user.id)
        .with_entities(Comentario.id_imagem)
        .all()
    ]
    interacted_ids = set(liked_ids + commented_ids)

    category_weights = Counter()
    tag_weights = Counter()
    author_weights = Counter()
    if not interacted_ids:
        return category_weights, tag_weights, author_weights, interacted_ids

    images = Imagem.query.filter(Imagem.id.in_(interacted_ids)).all()
    liked_set = set(liked_ids)
    commented_set = set(commented_ids)
    for image in images:
        weight = 0
        if image.id in liked_set:
            weight += 5
        if image.id in commented_set:
            weight += 3
        if image.id_categoria:
            category_weights[image.id_categoria] += weight
        if image.id_utilizador:
            author_weights[image.id_utilizador] += max(1, weight // 2)
        for tag in split_tags(image.tags):
            tag_weights[tag] += max(1, weight // 2)

    return category_weights, tag_weights, author_weights, interacted_ids


def build_recommendations(user=None, limit=12):
    category_weights, tag_weights, author_weights, interacted_ids = _interaction_profile(user)

    query = Imagem.query.filter(Imagem.publica == True)
    if user:
        query = query.filter(Imagem.id_utilizador != user.id)
    if interacted_ids:
        query = query.filter(~Imagem.id.in_(interacted_ids))

    # Se o utilizador não tem histórico de interação (ex: novo registo),
    # carregamos os candidatos ordenados por número de gostos para destacar o melhor conteúdo.
    if not interacted_ids:
        candidates_query = (
            db.session.query(Imagem)
            .outerjoin(Reacao, (Reacao.id_imagem == Imagem.id) & (Reacao.tipo == "like"))
            .filter(Imagem.publica == True)
        )
        if user:
            candidates_query = candidates_query.filter(Imagem.id_utilizador != user.id)
            
        candidates = (
            candidates_query.group_by(Imagem.id)
            .order_by(func.count(Reacao.id).desc(), Imagem.data_upload.desc())
            .limit(200)
            .all()
        )
    else:
        candidates = query.order_by(Imagem.data_upload.desc()).limit(1000).all()

    image_ids = [image.id for image in candidates]
    likes = _counts_by_image(Reacao, image_ids)
    comments = _counts_by_image(Comentario, image_ids)

    # Calcular a média global de curtidas dos posts públicos
    total_public_posts = Imagem.query.filter_by(publica=True).count()
    total_public_likes = Reacao.query.filter_by(tipo="like").count()
    media_curtidas = total_public_likes / max(1, total_public_posts)

    import hashlib
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    scored = []
    now = datetime.utcnow()
    # Top 3 tags mais interagidas para bónus de afinidade
    fav_tags = [t[0] for t in tag_weights.most_common(3)]

    for image in candidates:
        score = 0.0
        reasons = []

        # 1. Correspondência de Categoria (Afinidade)
        category_score = category_weights.get(image.id_categoria, 0)
        if category_score:
            score += category_score * 5.0
            reasons.append("categoria favorita")

        # 2. Correspondência de Tags (Afinidade)
        image_tags = split_tags(image.tags)
        matched_tags = [tag for tag in image_tags if tag in tag_weights]
        if matched_tags:
            score += sum(tag_weights[tag] for tag in matched_tags) * 4.0
            reasons.append("temas relacionados")
            # Bónus extra se a tag for uma das top 3 favoritas
            if any(t in fav_tags for t in matched_tags):
                score += 8.0

        # 3. Correspondência de Autor (Afinidade)
        author_score = author_weights.get(image.id_utilizador, 0)
        if author_score:
            score += author_score * 3.0
            reasons.append("artista que gostas")

        # 4. Métricas de Popularidade Global vs Média de Curtidas
        likes_score = likes.get(image.id, 0)
        comments_score = comments.get(image.id, 0)
        
        if likes_score > media_curtidas:
            score += (likes_score - media_curtidas) * 5.0
            reasons.append("acima da média de curtidas")
        elif likes_score > 0:
            score += (likes_score / max(0.1, media_curtidas)) * 2.0
            reasons.append("obra recomendada")
            
        popularity_score = likes_score * 2.5 + comments_score * 1.5
        score += popularity_score
        if likes_score >= 3:
            reasons.append("popular na comunidade")

        # 5. Decaimento Temporal (Boost de Frescura vs Obras Lendárias)
        age_days = (now - image.data_upload).days if image.data_upload else 30
        decay = 1.0 / (1.0 + 0.03 * max(0, age_days))
        score = score * decay

        if age_days <= 5:
            reasons.append("novidade recente")

        # 6. Multiplicador de Reset Diário (Sufle determinístico diário via hash)
        hash_val = hashlib.sha256(f"{image.id}-{today_str}".encode()).hexdigest()
        daily_shuffle = 0.8 + (int(hash_val[:6], 16) % 401) / 1000.0  # Fator entre 0.8 e 1.2
        score = score * daily_shuffle

        # Adicionar fallback de motivo
        if not reasons:
            reasons.append("sugestão ArteNuvem")

        # Manter apenas motivos únicos e limitar a 2 para não encher a UI
        unique_reasons = []
        for r in reasons:
            if r not in unique_reasons:
                unique_reasons.append(r)
        reasons_str = " · ".join(unique_reasons[:2])

        scored.append((score, image, reasons_str))

    # Ordenar por pontuação (score) decrescente, usando a data como critério de desempate
    scored.sort(key=lambda item: (item[0], item[1].data_upload or datetime.min), reverse=True)

    if not scored:
        fallback = (
            Imagem.query.filter(Imagem.publica == True).order_by(Imagem.data_upload.desc())
            .limit(limit)
            .all()
        )
        scored = [(0, image, "destaque recente") for image in fallback]

    images = [item[1] for item in scored[:limit]]
    return {
        "images": images,
        "reasons": {item[1].id: item[2] for item in scored[:limit]},
        "favorite_tags": tag_weights.most_common(8),
        "favorite_categories": category_weights.most_common(8),
        "authors": recommend_authors(user, category_weights, tag_weights, limit=6),
        "expositions": recommend_expositions(category_weights, tag_weights, limit=6),
    }


def recommend_authors(user, category_weights=None, tag_weights=None, limit=6):
    category_weights = category_weights or Counter()
    tag_weights = tag_weights or Counter()

    users = Utilizador.query.order_by(Utilizador.nome).all()
    results = []
    for candidate in users:
        if user and candidate.id == user.id:
            continue
        images = Imagem.query.filter_by(id_utilizador=candidate.id).limit(100).all()
        if not images:
            continue
        score = len(images)
        for image in images:
            score += category_weights.get(image.id_categoria, 0)
            score += sum(tag_weights.get(tag, 0) for tag in split_tags(image.tags))
        results.append((score, candidate, len(images)))

    results.sort(key=lambda item: (item[0], item[2], item[1].nome or ""), reverse=True)
    return results[:limit]


def recommend_expositions(category_weights=None, tag_weights=None, limit=6):
    category_weights = category_weights or Counter()
    tag_weights = tag_weights or Counter()

    rows = Exposicao.query.filter_by(ativo=True).order_by(Exposicao.id.desc()).all()
    results = []
    for exposition in rows:
        score = 1
        if exposition.categoria_id:
            score += category_weights.get(exposition.categoria_id, 0) * 2
        for tag in split_tags(exposition.tags_filtro):
            score += tag_weights.get(tag, 0)
        results.append((score, exposition))

    results.sort(key=lambda item: (item[0], item[1].id), reverse=True)
    return results[:limit]


def serialize_image(image, reason=None):
    return {
        "id": image.id,
        "titulo": image.titulo,
        "categoria": image.categoria_texto,
        "tags": split_tags(image.tags),
        "url": image.caminho_armazenamento,
        "autor_id": image.id_utilizador,
        "data_upload": image.data_upload.isoformat() if image.data_upload else None,
        "reason": reason,
    }
