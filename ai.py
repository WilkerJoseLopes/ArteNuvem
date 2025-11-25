# ai.py
import os
import openai
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from typing import List, Tuple

# Inicializar OpenAI a partir da variável de ambiente OPENAI_API_KEY
openai.api_key = os.getenv("OPENAI_API_KEY")

# Ajusta estes nomes se preferires outro modelo
EMBEDDING_MODEL = "text-embedding-3-small"   # ou outro disponível
GENERATION_MODEL = "gpt-4o-mini"             # sugestão; podes usar gpt-3.5-turbo

def create_embedding(text: str) -> List[float]:
    """Retorna embedding (lista de floats) para um texto."""
    if not openai.api_key:
        raise RuntimeError("OPENAI_API_KEY não definida")
    resp = openai.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return resp["data"][0]["embedding"]

def generate_caption(prompt: str, max_tokens: int = 150) -> str:
    """Gera uma legenda / descrição para uma obra a partir de um prompt/descritivo curto."""
    if not openai.api_key:
        raise RuntimeError("OPENAI_API_KEY não definida")
    resp = openai.chat.completions.create(
        model=GENERATION_MODEL,
        messages=[
            {"role": "system", "content": "You are an assistant that writes concise and evocative art descriptions."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=max_tokens,
        temperature=0.8
    )
    # adapta ao formato da resposta (depende da versão do SDK)
    text = resp["choices"][0]["message"]["content"].strip()
    return text

def find_similar(art_embeddings: List[Tuple[int, List[float]]], query_embedding: List[float], top_k: int = 5):
    """
    art_embeddings: lista de tuples (art_id, embedding_list)
    query_embedding: embedding para comparação
    Retorna top_k art_ids ordenados por similaridade.
    """
    ids = [t[0] for t in art_embeddings]
    mats = np.array([t[1] for t in art_embeddings])
    q = np.array(query_embedding).reshape(1, -1)
    sims = cosine_similarity(q, mats)[0]  # vetor de similaridades
    order = np.argsort(sims)[::-1]  # maior para menor
    results = [{"art_id": ids[i], "score": float(sims[i])} for i in order[:top_k]]
    return results
