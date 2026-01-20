# ai.py
import os
import requests

OLLAMA_URL = os.getenv("OLLAMA_URL") or "https://sleekiest-alayah-duddy.ngrok-free.dev/api/generate"
MODEL = os.getenv("OLLAMA_MODEL", "mistral")
TIMEOUT = 8

def _try_extract_response_json(j):
    if not j:
        return ""
    if isinstance(j, dict):
        # Ollama style: {"id":..., "result":[{"id":..., "message": {"content": [{"type":"output_text","text":"..."}]}}]}
        if "response" in j and isinstance(j["response"], str):
            return j["response"]
        if "result" in j and isinstance(j["result"], list) and len(j["result"])>0:
            msg = j["result"][0].get("message", {})
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list) and len(content)>0:
                    # try find text inside content objects
                    for c in content:
                        if isinstance(c, dict):
                            # common keys
                            if "text" in c:
                                return c["text"]
                            if "output" in c:
                                return c["output"]
                            if "parts" in c and isinstance(c["parts"], list):
                                return " ".join([str(p) for p in c["parts"]])
                    # last resort: join str of all
                    return " ".join([str(c) for c in content])
        # fallback: maybe API returned {"choices": [{"text": "..."}]}
        if "choices" in j and isinstance(j["choices"], list) and len(j["choices"])>0:
            c0 = j["choices"][0]
            if isinstance(c0, dict):
                if "text" in c0:
                    return c0["text"]
                if "message" in c0 and isinstance(c0["message"], dict) and "content" in c0["message"]:
                    return c0["message"]["content"]
    return ""

def moderar_comentario(texto: str) -> bool:
    prompt = (
        "Este comentário contém linguagem ofensiva, palavrões, insultos, discurso de ódio "
        "ou conteúdo impróprio? Responde apenas com SIM ou NAO.\n\n"
        f"Comentário: {texto}"
    )
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False
    }
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(OLLAMA_URL, json=payload, headers=headers, timeout=TIMEOUT)
        # sucesso HTTP?
        if resp.status_code != 200:
            return False
        j = None
        try:
            j = resp.json()
        except Exception:
            text = resp.text or ""
            # fallback: try quick check
            return "SIM" in text.upper()
        out = _try_extract_response_json(j) or ""
        out = out.strip().upper()
        if "SIM" in out:
            return True
        if "NÃO" in out or "NAO" in out:
            return False
        # fallback heuristics: look for curse words (very small blacklist)
        small_bad = ["merda","fdp","filho da puta","caralho","porra","idiota","nojento","imbecil","fuck","bastard"]
        low = texto.lower()
        for b in small_bad:
            if b in low:
                return True
        return False
    except Exception:
        return False
