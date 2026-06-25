import os
import re
import unicodedata
import requests
import json
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GEMINI_DEFAULT_MODEL = "gemini-2.5-flash-lite"


def _get_gemini_api_key():
    for env_name in ("gemini_moder", "GEMINI_MODER", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(env_name)
        if value:
            return value.strip().strip('"').strip("'")
    return None


def _get_gemini_model():
    return (os.environ.get("GEMINI_MODEL") or GEMINI_DEFAULT_MODEL).strip()


def _get_gemini_models():
    configured = os.environ.get("GEMINI_MODEL")
    if configured:
        return [model.strip() for model in configured.split(",") if model.strip()]
    return [GEMINI_DEFAULT_MODEL, "gemini-2.5-flash"]


def _extract_google_error(response):
    try:
        payload = response.json()
    except ValueError:
        text = (response.text or "").strip()
        return text[:500] if text else "Sem detalhe devolvido pelo Google."

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        status = error.get("status")
        message = error.get("message")
        if status and message:
            return f"{status}: {message}"
        if message:
            return message
    return json.dumps(payload, ensure_ascii=False)[:500]


def _public_referer(referer=None):
    value = (
        referer
        or os.environ.get("GEMINI_HTTP_REFERER")
        or os.environ.get("APP_PUBLIC_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
    )
    if not value:
        return None
    value = value.strip()
    if value and not value.endswith("/"):
        value += "/"
    return value


def _normalizar_e_deobfuscar(texto: str) -> str:
    if not texto:
        return ""
    # Transforma em minúsculas
    texto = texto.lower()
    
    # Substituições comuns de caracteres para desofuscar
    subs = {
        '@': 'o',  # ex: p@rra -> porra
        '$': 's',
        '0': 'o',
        '3': 'e',
        '4': 'a',
        '1': 'i',
        '!': 'i',
        '*': '',
        '_': '',
        '-': ''
    }
    
    # Aplicar substituições
    for char, sub in subs.items():
        texto = texto.replace(char, sub)
        
    # Remove acentos
    nfkd = unicodedata.normalize("NFKD", texto)
    texto = "".join([c for c in nfkd if not unicodedata.combining(c)])
    
    # Remove pontuação restante e mantém apenas letras, números e espaços
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    # Junta múltiplos espaços
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def avaliar_comentario(texto: str) -> dict:
    """
    Avalia o comentário usando heurísticas locais por código (regex, deobfuscation, scoring).
    Esta moderação segue estritamente a tabela s.sql.
    """
    if not texto:
        return {
            "blocked": False,
            "toxicity_score": 0.0,
            "decision": "aprovado",
            "model_name": "local-heuristics",
            "matches": [],
            "motivo": None
        }

    # 1. Normalizar e desofuscar
    texto_limpo = _normalizar_e_deobfuscar(texto)
    
    # 2. Palavras proibidas graves e leves
    GRAVES = {
        "porra", "caralho", "coralho", "puta", "pota", "foda", "foder", "fodasse", "fodace",
        "viado", "fdp", "filhodaputa", "cona", "corno", "paneleiro", "fuck", "shit", "bitch",
        "asshole", "motherfucker", "chupa"
    }
    
    LEVES = {
        "merda", "idiota", "otario", "otaria", "bastardo", "cabrao", "cabroes", "cu"
    }
    
    # Combinar todas para busca
    todas_proibidas = GRAVES.union(LEVES)
    
    # Encontrar palavras encontradas
    matches = []
    
    # 1. Procurar por palavra exata (tokens)
    tokens = texto_limpo.split()
    for t in tokens:
        if t in todas_proibidas:
            matches.append(t)
            
    # 2. Procurar por substrings caso tenhamos espaços ocultos (ex: "filho da puta" -> "filhodaputa")
    texto_sem_espacos = texto_limpo.replace(" ", "")
    for p in todas_proibidas:
        if len(p) > 3 and p in texto_sem_espacos:
            if p not in matches:
                matches.append(p)
                
    # 3. Remover duplicados mantendo ordem
    matches = list(dict.fromkeys(matches))
    
    # 4. Calcular pontuação e decisão
    if not matches:
        return {
            "blocked": False,
            "toxicity_score": 0.0,
            "decision": "aprovado",
            "model_name": "local-heuristics",
            "matches": [],
            "motivo": None
        }
        
    # Verificar se há alguma palavra grave
    tem_grave = any(m in GRAVES for m in matches)
    
    if tem_grave:
        # Bloqueio automático imediato
        toxicity_score = min(1.0, 0.80 + 0.05 * len(matches))
        decision = "bloqueado"
        motivo = f"Comentário bloqueado automaticamente devido ao termo: {', '.join(matches)}"
    else:
        # Pendente para revisão manual
        toxicity_score = min(0.79, 0.30 + 0.15 * len(matches))
        decision = "pendente"
        motivo = f"Comentário enviado para revisão devido ao termo: {', '.join(matches)}"
        
    return {
        "blocked": decision in ("pendente", "bloqueado"),
        "toxicity_score": toxicity_score,
        "decision": decision,
        "model_name": "local-heuristics",
        "matches": matches,
        "motivo": motivo
    }


def gerar_sugestao_obra(ideia: str, referer=None) -> dict:
    """
    Usa o Gemini para sugerir um titulo e uma descricao artistica com base
    num rascunho, tema ou ideia do utilizador.
    """
    load_dotenv()
    api_key = _get_gemini_api_key()
    if not api_key:
        return {"error": "API Key Gemini nao configurada. Define gemini_moder ou GEMINI_API_KEY no Render."}

    prompt = (
        "Es um assistente de IA altamente criativo integrado na plataforma de arte ArteNuvem.\n"
        "O utilizador quer publicar uma obra mas tem falta de ideias. Ele forneceu o seguinte tema, rascunho ou ideia:\n"
        f"\"{ideia}\"\n\n"
        "Gera um titulo chamativo e criativo para a obra e uma descricao poetica, artistica e envolvente "
        "(com cerca de 2 a 4 frases, em portugues de Portugal).\n\n"
        "Responde APENAS com um objeto JSON valido, sem qualquer texto adicional ou blocos de codigo. "
        "O formato do JSON deve ser exatamente:\n"
        "{\n"
        '  "titulo": "Sugestao de titulo",\n'
        '  "descricao": "Sugestao de descricao artistica"\n'
        "}"
    )

    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": api_key,
        "User-Agent": "ArteNuvem/1.0",
    }
    public_referer = _public_referer(referer)
    if public_referer:
        headers["Referer"] = public_referer

    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 350,
            "responseMimeType": "application/json",
        },
    }

    try:
        last_status = None
        last_detail = None
        for model_name in _get_gemini_models():
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code == 200:
                res_json = response.json()
                candidates = res_json.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if parts:
                        raw_text = parts[0].get("text", "").strip()
                        if not raw_text:
                            logger.error("Gemini devolveu texto vazio no modelo %s: %s", model_name, json.dumps(res_json, ensure_ascii=False)[:500])
                            last_status = 200
                            last_detail = "Resposta vazia"
                            continue
                        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                        if match:
                            raw_text = match.group(0)
                        try:
                            data = json.loads(raw_text)
                        except json.JSONDecodeError:
                            logger.error("Gemini devolveu JSON invalido no modelo %s: %s", model_name, raw_text[:500])
                            last_status = 200
                            last_detail = "JSON invalido"
                            continue
                        return {
                            "titulo": data.get("titulo", "").strip(),
                            "descricao": data.get("descricao", "").strip(),
                        }

                logger.error("Gemini respondeu sem sugestao valida no modelo %s: %s", model_name, json.dumps(res_json, ensure_ascii=False)[:500])
                return {"error": "A IA respondeu, mas nao devolveu uma sugestao valida. Tenta novamente."}

            last_status = response.status_code
            last_detail = _extract_google_error(response)
            logger.error("Erro Gemini HTTP %s no modelo %s: %s", last_status, model_name, last_detail)

            if last_status in (429, 500, 502, 503, 504):
                continue
            if last_status == 403:
                return {
                    "error": (
                        "A chave Gemini foi recusada pelo Google (HTTP 403). "
                        "Verifica no Google AI Studio/Cloud se a key tem acesso ao Gemini "
                        "e se as restricoes permitem chamadas a partir de https://artenuvem.onrender.com."
                    )
                }
            return {"error": f"Erro de comunicacao com o servico de IA (HTTP {last_status})."}

        if last_status in (429, 503):
            return {"error": "O Gemini esta temporariamente ocupado ou em limite de quota. Tenta novamente dentro de instantes."}
        if last_status == 200:
            return {"error": "A IA respondeu, mas nao devolveu uma sugestao valida. Tenta novamente."}
        return {"error": f"Erro de comunicacao com o servico de IA (HTTP {last_status})."}
    except Exception as e:
        logger.exception("Erro ao contactar Gemini")
        return {"error": f"Ocorreu um erro ao contactar a IA: {e}"}


# Teste local
if __name__ == "__main__":
    testes = [
        "Este quadro é absolutamente magnífico!",
        "Que caralho é isto?",
        "P@rra, que feio.",
        "hello friend, great work!",
        "Vai tomar no c*, idiota.",
    ]
    for t in testes:
        print("-" * 60)
        print("Texto:", t)
        print("Resultado:", json.dumps(avaliar_comentario(t), indent=2, ensure_ascii=False))
