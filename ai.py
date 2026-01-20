import requests

OLLAMA_URL = "https://sleekiest-alayah-duddy.ngrok-free.dev"
MODEL = "mistral"

def moderar_comentario(texto: str) -> bool:
    prompt = (
        "Este comentário contém linguagem ofensiva, palavrões, insultos, discurso de ódio "
        "ou conteúdo impróprio? Responde apenas com SIM ou NÃO.\n\n"
        f"Comentário: {texto}"
    )

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False
            },
            timeout=15
        )
        data = resp.json()
        resposta = data.get("response", "").strip().upper()
        return "SIM" in resposta
    except Exception as e:
        print("Erro ao chamar Ollama:", e)
        return False
