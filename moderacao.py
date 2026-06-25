import os
import re
import unicodedata
import requests
import json
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


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


def gerar_sugestao_obra(ideia: str) -> dict:
    """
    Usa o Gemini para sugerir um título e uma descrição artística com base
    num rascunho, tema ou ideia do utilizador.
    """
    load_dotenv()
    api_key = os.environ.get("gemini_moder")
    if not api_key:
        return {"error": "API Key não configurada no ficheiro .env."}

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
    
    prompt = (
        "És um assistente de IA altamente criativo integrado na plataforma de arte ArteNuvem.\n"
        "O utilizador quer publicar uma obra mas tem falta de ideias. Ele forneceu o seguinte tema, rascunho ou ideia:\n"
        f"\"{ideia}\"\n\n"
        "Gera um título chamativo e criativo para a obra e uma descrição poética, artística e envolvente (com cerca de 2 a 4 frases, em português de Portugal).\n\n"
        "Responde APENAS com um objeto JSON válido, sem qualquer texto adicional ou blocos de código. O formato do JSON deve ser exatamente:\n"
        "{\n"
        '  "titulo": "Sugestão de título",\n'
        '  "descricao": "Sugestão de descrição artística"\n'
        "}"
    )

    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": api_key,
    }
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
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            res_json = response.json()
            candidates = res_json.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    raw_text = parts[0].get("text", "").strip()
                    # Extrair objeto JSON de forma robusta
                    import re
                    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                    if match:
                        raw_text = match.group(0)
                    data = json.loads(raw_text)
                    return {
                        "titulo": data.get("titulo", "").strip(),
                        "descricao": data.get("descricao", "").strip(),
                    }
        return {"error": f"Erro de comunicação com o serviço de IA (HTTP {response.status_code})."}
    except Exception as e:
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
