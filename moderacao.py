import re
import unicodedata

# lista simples de palavras proibidas (pt + en). Expande à vontade.
PROIBIDAS = {
    # português (exemplos)
    "caralho","porra","foda","fode","fodasse","p*ta","puta","merda","burro","idiota","otario","otário",
    "bastardo","viado","filho da puta","fdp",
    # inglês comum
    "fuck","shit","bitch","bastard","asshole","motherfucker"
}

# normalizar: remove acentos, põe minúsculas e só letras/números/espaços
def _normaliza(texto: str) -> str:
    texto = texto or ""
    # remove acentos
    nfkd = unicodedata.normalize("NFKD", texto)
    texto = "".join([c for c in nfkd if not unicodedata.combining(c)])
    texto = texto.lower()
    # substitui símbolos por espaços (ajuda a detectar "f0da", "f*da" -> f da)
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    # junta múltiplos espaços
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto

# detecta obfuscações simples (ex.: f0da -> foda)
def _deobfusca(texto: str) -> str:
    subs = {
        "0":"o", "1":"i", "3":"e", "4":"a", "5":"s", "7":"t", "@":"a", "$":"s"
    }
    out = []
    for ch in texto:
        out.append(subs.get(ch, ch))
    return "".join(out)

# tenta separar palavras compostas (por exemplo 'filho da puta' -> detetável)
def _gera_ngrams(tokens, max_len=3):
    n = len(tokens)
    for L in range(1, max_len+1):
        for i in range(0, n-L+1):
            yield " ".join(tokens[i:i+L])

def moderar_comentario(texto: str) -> bool:
    """
    Retorna True se o texto contém linguagem imprópria (bloquear).
    Retorna False se está limpo.
    """
    if not texto:
        return False

    txt = _normaliza(texto)
    txt = _deobfusca(txt)

    tokens = txt.split()

    # 1) checa palavras isoladas
    for t in tokens:
        if t in PROIBIDAS:
            return True

    # 2) checa n-grams (até 4 palavras) para frases como "filho da puta"
    for ngram in _gera_ngrams(tokens, max_len=4):
        if ngram in PROIBIDAS:
            return True

    # 3) checa formas parciais (contains) — evita false positives com cuidado
    for bad in PROIBIDAS:
        # usa boundary check simples: se bad aparece com letras adjacentes pode causar false positives,
        # por isso apenas usa contains se bad tem >=4 chars
        if len(bad) >= 4 and bad in txt:
            return True

    return False

# quick test runner (vai facilitar testar localmente)
if __name__ == "__main__":
    testes = [
        "Que caralho é isto?",
        "isso é f0da", 
        "hello friend",
        "filho da puta!",
        "this is fuck",
        "isso é fo-da", 
        "palavra neutra"
    ]
    for t in testes:
        print(t, "->", moderar_comentario(t))
