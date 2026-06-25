import os
import threading
from flask import render_template, request
import resend
from models import db, Utilizador, PreferenciaNotificacao
from services.recommendation_service import build_recommendations

def send_email(to_email, subject, html):
    """
    Envia um e-mail usando a API do Resend diretamente para o utilizador.
    """
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        print(f"[EMAIL ERROR] Destino: {to_email} | Assunto: {subject} | Erro: RESEND_API_KEY não configurada no .env")
        return False

    resend.api_key = api_key
    
    try:
        response = resend.Emails.send({
            "from": "ArteNuvem <onboarding@resend.dev>",
            "to": to_email,
            "subject": subject,
            "html": html
        })
        print(f"[EMAIL SUCCESS] Destino: {to_email} | Assunto: {subject} | Response ID: {response.get('id') if isinstance(response, dict) else getattr(response, 'id', response)}")
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] Destino: {to_email} | Assunto: {subject} | Erro: {str(e)}")
        return False

def send_email_async(to_email, subject, html):
    """
    Cria uma thread em segundo plano para enviar o email sem bloquear o servidor.
    """
    thread = threading.Thread(target=send_email, args=(to_email, subject, html))
    thread.start()

def get_or_create_preferences(user):
    """
    Obtém as preferências de notificação do utilizador ou cria com valores padrão.
    """
    prefs = user.preferencia_notificacao
    if not prefs:
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
    return prefs

def send_welcome_email(user):
    """
    Envia email de boas-vindas ao utilizador no primeiro login.
    Verifica se já foi enviado e desativa a flag de boas-vindas.
    """
    prefs = get_or_create_preferences(user)
    if not prefs.email_boas_vindas:
        return False

    try:
        try:
            site_url = request.host_url
        except Exception:
            site_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SITE_URL") or "http://localhost:5000/"
            if not site_url.endswith("/"):
                site_url += "/"

        html = render_template(
            "emails/welcome.html",
            user=user,
            site_url=site_url
        )
        
        subject = "Bem-vindo à ArteNuvem!"
        
        # Desativa o envio de boas-vindas futuro e atualiza base de dados
        prefs.email_boas_vindas = False
        db.session.commit()
        
        send_email_async(user.email, subject, html)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] Falha ao processar email de boas-vindas para {user.email}: {str(e)}")
        return False

def send_recommendation_email(user):
    """
    Envia recomendações de arte baseadas nas preferências e interações do utilizador.
    """
    prefs = get_or_create_preferences(user)
    if not prefs.email_ativo or not prefs.email_recomendacoes:
        return False

    try:
        # Obter recomendações personalizadas
        rec_data = build_recommendations(user, limit=3)
        recommended_images = rec_data.get("images", [])
        reasons = rec_data.get("reasons", {})

        if not recommended_images:
            return False

        try:
            site_url = request.host_url
        except Exception:
            site_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SITE_URL") or "http://localhost:5000/"
            if not site_url.endswith("/"):
                site_url += "/"

        html = render_template(
            "emails/recommendations.html",
            user=user,
            site_url=site_url,
            images=recommended_images,
            reasons=reasons
        )

        subject = "ArteNuvem - Recomendações de Arte para Si"
        
        send_email_async(user.email, subject, html)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] Falha ao processar email de recomendações para {user.email}: {str(e)}")
        return False

