#!/usr/bin/env python3
"""Normalizador fonético PT-BR e ES para síntese de voz (XTTS v2).

Suporta Português Brasileiro ('pt') e Espanhol ('es') com detecção automática:
  1. Detecta o idioma automaticamente por léxico e marcadores ortográficos.
  2. Expande abreviações comuns (p. ex., etc., Dr., Sr., cap.) antes da divisão de frases.
  3. Normaliza siglas e variáveis maiúsculas (X, Y, IA, GPU, CPU, API, SQL...).
  4. Trata termos técnicos em inglês para pronúncia fonética aproximada no idioma alvo.
  5. Converte números/porcentagens/unidades para extenso em português quando idioma='pt'
     (em espanhol o XTTS v2 já expande números nativamente com alta fidelidade).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Detecção Automática de Idioma
# ---------------------------------------------------------------------------
_TOKENS_ES = {
    "el", "la", "los", "las", "del", "al", "y", "en", "es", "un", "una",
    "unos", "unas", "con", "por", "para", "su", "sus", "como", "más",
    "pero", "este", "esta", "estos", "estas", "entre", "cuando", "también",
    "sobre", "ser", "son", "fue", "había", "era", "tiene", "tienen", "hacer",
    "todo", "todos", "toda", "todas", "puede", "pueden", "así", "desde",
    "hasta", "sin", "año", "años", "después", "hacia", "decir", "aprendizaje",
    "inteligencia", "modelo", "datos", "redes", "entrenamiento", "red",
}

_TOKENS_PT = {
    "o", "a", "os", "as", "do", "da", "dos", "das", "no", "na", "nos",
    "nas", "em", "é", "um", "uma", "uns", "umas", "com", "por", "para",
    "seu", "sua", "seus", "suas", "como", "mais", "mas", "este", "esta",
    "estes", "estas", "entre", "quando", "também", "sobre", "ser", "são",
    "foi", "havia", "era", "tem", "têm", "fazer", "tudo", "todos", "toda",
    "todas", "pode", "podem", "assim", "desde", "até", "sem", "ano",
    "anos", "depois", "não", "dizer", "você", "vocês", "aprendizado",
    "inteligência", "dados", "treinamento", "rede",
}


def detectar_idioma(texto: str) -> str:
    """Detecta automaticamente se o texto está em espanhol ('es') ou português ('pt')."""
    t = texto.lower()
    # Marcadores exclusivos
    if any(c in t for c in ("¿", "¡", "ñ")):
        return "es"
    if any(c in t for c in ("ã", "õ", "ç", "à")):
        return "pt"

    palavras = re.findall(r"\b[a-záéíóúâêôãõàüñ]+\b", t)
    if not palavras:
        return "pt"

    score_es = sum(1 for p in palavras if p in _TOKENS_ES)
    score_pt = sum(1 for p in palavras if p in _TOKENS_PT)

    if "es decir" in t or "por ejemplo" in t:
        score_es += 3
    if "ou seja" in t or "por exemplo" in t:
        score_pt += 3

    return "es" if score_es > score_pt else "pt"


# ---------------------------------------------------------------------------
# 2. Abreviações
# ---------------------------------------------------------------------------
ABREVIACOES_PT: list[tuple[str, str]] = [
    (r"\bp\.\s*ex\.", "por exemplo,"),
    (r"\bex\.\s*:", "por exemplo:"),
    (r"\bex\.", "por exemplo,"),
    (r"\betc\.", "etcétera"),
    (r"\bvs\.", "versus"),
    (r"\bvs\b", "versus"),
    (r"\bDr\.", "Doutor"),
    (r"\bDra\.", "Doutora"),
    (r"\bSr\.", "Senhor"),
    (r"\bSra\.", "Senhora"),
    (r"\bProf\.", "Professor"),
    (r"\bProfa\.", "Professora"),
    (r"\bpág\.", "página"),
    (r"\bpágs\.", "páginas"),
    (r"\bfig\.", "figura"),
    (r"\bfigs\.", "figuras"),
    (r"\bcap\.", "capítulo"),
    (r"\baprox\.", "aproximadamente"),
]

ABREVIACOES_ES: list[tuple[str, str]] = [
    (r"\bp\.\s*ej\.", "por ejemplo,"),
    (r"\bej\.\s*:", "por ejemplo:"),
    (r"\bej\.", "por ejemplo,"),
    (r"\betc\.", "etcétera"),
    (r"\bvs\.", "versus"),
    (r"\bvs\b", "versus"),
    (r"\bDr\.", "Doctor"),
    (r"\bDra\.", "Doctora"),
    (r"\bSr\.", "Señor"),
    (r"\bSra\.", "Señora"),
    (r"\bProf\.", "Profesor"),
    (r"\bProfa\.", "Profesora"),
    (r"\bpág\.", "página"),
    (r"\bpágs\.", "páginas"),
    (r"\bfig\.", "figura"),
    (r"\bfigs\.", "figuras"),
    (r"\bcap\.", "capítulo"),
    (r"\baprox\.", "aproximadamente"),
]


# ---------------------------------------------------------------------------
# 3. Glossários de Termos Técnicos em Inglês
# ---------------------------------------------------------------------------
TERMOS_INGLES_PTBR: dict[str, str] = {
    "deep learning": "díp lérnin",
    "machine learning": "maxíne lérnin",
    "reinforcement learning": "reinforcement lérnin",
    "transfer learning": "trânsfer lérnin",
    "supervised learning": "superváized lérnin",
    "unsupervised learning": "ãn-superváized lérnin",
    "self-supervised learning": "sélf superváized lérnin",
    "federated learning": "féderêited lérnin",
    "forward pass": "fóruard páss",
    "backward pass": "béqui-uard páss",
    "fine-tuning": "fáin túnin",
    "fine tuning": "fáin túnin",
    "zero-shot": "zéro xót",
    "zero shot": "zéro xót",
    "few-shot": "fíu xót",
    "few shot": "fíu xót",
    "one-shot": "uãn xót",
    "chain-of-thought": "tchêin óv fót",
    "chain of thought": "tchêin óv fót",
    "random forest": "rândom fórest",
    "gradient boosting": "grêidient bústin",
    "learning rate": "lârnin rêit",
    "batch normalization": "bétch normalizêixon",
    "layer normalization": "lêier normalizêixon",
    "feature engineering": "fítchur endjinírin",
    "ground truth": "gráund trúf",
    "bounding box": "báundin bóks",
    "bounding boxes": "báundin bókses",
    "grid search": "gríd sârtch",
    "random search": "rândom sârtch",
    "data science": "dêita sáiens",
    "data scientist": "dêita sáientist",
    "big data": "bíg dêita",
    "data mining": "dêita máinin",
    "data warehouse": "dêita uér-ráus",
    "data lake": "dêita lêik",
    "open source": "ôupen sôrs",
    "open-source": "ôupen sôrs",
    "cloud computing": "cláud compíutin",
    "edge computing": "édj compíutin",
    "computer vision": "compíuter víjon",
    "natural language processing": "nétchural lênguadj procéssin",
    "large language models": "lárdj lênguadj módels",
    "large language model": "lárdj lênguadj módel",
    "neural networks": "níural nétuorks",
    "neural network": "níural nétuork",
    "state-of-the-art": "stêit óv dê árt",
    "state of the art": "stêit óv dê árt",
    "trade-offs": "trêid-ófs",
    "trade-off": "trêid-óf",
    "tradeoff": "trêid-óf",
    "self-attention": "sélf atênxon",
    "cross-attention": "crós atênxon",
    "multi-head attention": "mâlti-réd atênxon",
    "mini-batch": "míni-bétch",
    "mini-batches": "míni-bétches",
    "backpropagation": "béqui-propagêixon",
    "overfitting": "ôver-fítin",
    "underfitting": "ânder-fítin",
    "dropout": "dróp-áut",
    "pooling": "púlin",
    "max-pooling": "méks-púlin",
    "stride": "stráid",
    "padding": "pédin",
    "softmax": "sóft-méks",
    "relu": "rê-lú",
    "leaky relu": "líki rê-lú",
    "sigmoid": "sigmóid",
    "attention": "atênxon",
    "autoencoders": "áuto-encôuders",
    "autoencoder": "áuto-encôuder",
    "encoders": "encôuders",
    "encoder": "encôuder",
    "decoders": "decôuders",
    "decoder": "decôuder",
    "tokenizers": "tôukenáizers",
    "tokenizer": "tôukenáizer",
    "tokens": "tôukens",
    "token": "tôukem",
    "embeddings": "embédins",
    "embedding": "embédin",
    "datasets": "dêita-séts",
    "dataset": "dêita-sét",
    "dataframes": "dêita-frêims",
    "dataframe": "dêita-frêim",
    "batches": "bétches",
    "batch": "bétch",
    "epochs": "épocs",
    "epoch": "époc",
    "layers": "lêiers",
    "layer": "lêier",
    "bias": "báias",
    "loss": "lós",
    "checkpoints": "tchék-póints",
    "checkpoint": "tchék-póint",
    "baselines": "bêis-láins",
    "baseline": "bêis-láin",
    "benchmarks": "bêntch-márks",
    "benchmark": "bêntch-márk",
    "pipelines": "páip-láins",
    "pipeline": "páip-láin",
    "frameworks": "frêim-uôrks",
    "framework": "frêim-uôrk",
    "workflows": "uôrk-flôus",
    "workflow": "uôrk-flôu",
    "deployment": "deplóiment",
    "deploy": "deplói",
    "runtime": "rãn-táim",
    "backend": "bék-ênd",
    "frontend": "frônt-ênd",
    "fullstack": "fúl-sték",
    "hardware": "rárduér",
    "software": "sóftuér",
    "cloud": "cláud",
    "clusters": "clâsters",
    "cluster": "clâster",
    "serverless": "sârver-lés",
    "streaming": "strímin",
    "buffer": "bâfer",
    "cache": "quéche",
    "threads": "tréds",
    "thread": "tréd",
    "prompts": "prômpts",
    "prompt": "prômpt",
    "chatbots": "tchét-bóts",
    "chatbot": "tchét-bót",
    "chat": "tchét",
    "feedbacks": "fíd-béks",
    "feedback": "fíd-bék",
    "inputs": "ínputs",
    "input": "ínput",
    "outputs": "áutputs",
    "output": "áutput",
    "insights": "insáits",
    "insight": "insáit",
    "features": "fítchurs",
    "feature": "fítchur",
    "labels": "lêibols",
    "label": "lêibol",
    "outliers": "áut-láiers",
    "outlier": "áut-láier",
    "scripts": "scrípts",
    "script": "scrípt",
    "debug": "debâg",
    "bugs": "bâgs",
    "bug": "bâg",
    "arrays": "arrêis",
    "array": "arrêi",
    "strings": "stríngs",
    "string": "stríng",
    "design": "dezáin",
    "layout": "leiáut",
    "pixels": "píkseis",
    "pixel": "píksel",
}

TERMOS_INGLES_ES: dict[str, str] = {
    "deep learning": "díp lérnin",
    "machine learning": "machín lérnin",
    "reinforcement learning": "reinforcement lérnin",
    "forward pass": "fórward pas",
    "backward pass": "bákward pas",
    "fine-tuning": "fáin tiúnin",
    "fine tuning": "fáin tiúnin",
    "zero-shot": "zéro shot",
    "few-shot": "fíu shot",
    "random forest": "rándom fórest",
    "gradient boosting": "grêidient bústin",
    "data science": "deita sáiens",
    "big data": "big deita",
    "computer vision": "compiúter víshon",
    "natural language processing": "náchural lángüidj prosésin",
    "neural networks": "niúral nétuorks",
    "neural network": "niúral nétuork",
    "trade-off": "treid-of",
    "trade-offs": "treid-ofs",
    "backpropagation": "bék-propagüéishon",
    "overfitting": "óver-fítin",
    "underfitting": "ánder-fítin",
    "dropout": "drop-áut",
    "softmax": "soft-maks",
    "relu": "re-lú",
    "tokens": "tókens",
    "token": "tóken",
    "embeddings": "embédins",
    "embedding": "embédin",
    "datasets": "deitaséts",
    "dataset": "deitasét",
    "dataframes": "deitafréims",
    "dataframe": "deitafréim",
    "batches": "bátches",
    "batch": "bátch",
    "hardware": "járduer",
    "software": "sóftuer",
    "cloud": "cláud",
    "streaming": "strímin",
    "prompts": "prompts",
    "prompt": "prompt",
    "chatbot": "chátbot",
    "chatbots": "chátbots",
    "feedback": "fídbak",
    "feedbacks": "fídbaks",
    "insights": "ínsaits",
    "insight": "ínsait",
    "online": "on-láin",
    "offline": "of-láin",
    "pixels": "píxeles",
    "pixel": "píxel",
}


# ---------------------------------------------------------------------------
# 4. Siglas e Variáveis Maiúsculas (Case-sensitive)
# ---------------------------------------------------------------------------
SIGLAS_PTBR: dict[str, str] = {
    "IAs": "i-ás",
    "IA": "i-á",
    "AI": "êi-ái",
    "ML": "ême-éle",
    "DL": "dê-éle",
    "LLMs": "éle-éle-êmes",
    "LLM": "éle-éle-ême",
    "NLP": "êne-éle-pê",
    "PLN": "pê-éle-êne",
    "GPUs": "gê-pê-ús",
    "GPU": "gê-pê-ú",
    "CPUs": "cê-pê-ús",
    "CPU": "cê-pê-ú",
    "TPUs": "tê-pê-ús",
    "TPU": "tê-pê-ú",
    "NPUs": "êne-pê-ús",
    "NPU": "êne-pê-ú",
    "VRAM": "vê-rã",
    "RAM": "rã",
    "SSD": "ésse-ésse-dê",
    "APIs": "á-pê-ís",
    "API": "á-pê-í",
    "SDK": "ésse-dê-cá",
    "URLs": "ú-érre-éles",
    "URL": "ú-érre-éle",
    "HTTPS": "agá-tê-tê-pê-ésse",
    "HTTP": "agá-tê-tê-pê",
    "HTML": "agá-tê-ême-éle",
    "CSS": "cê-ésse-ésse",
    "NoSQL": "nôu-ésse-quê-éle",
    "SQL": "ésse-quê-éle",
    "JSON": "djêisson",
    "XML": "xis-ême-éle",
    "CSV": "cê-ésse-vê",
    "PDF": "pê-dê-éfe",
    "CNNs": "cê-êne-ênes",
    "CNN": "cê-êne-êne",
    "RNNs": "érre-êne-ênes",
    "RNN": "érre-êne-êne",
    "LSTMs": "éle-ésse-tê-êmes",
    "LSTM": "éle-ésse-tê-ême",
    "GANs": "gãns",
    "GAN": "gãn",
    "VAE": "vê-á-ê",
    "RAG": "rég",
    "GPT": "gê-pê-tê",
    "TI": "tê-í",
    "IoT": "i-ó-tê",
    "AWS": "á-dáblio-ésse",
    "GCP": "gê-cê-pê",
    "1D": "um dê",
    "2D": "dois dê",
    "3D": "três dê",
    "4D": "quatro dê",
    "X": "chís",
    "Y": "ípsilon",
    "Z": "zê",
    "W": "dáblio",
    "K": "cá",
}

SIGLAS_ES: dict[str, str] = {
    "IAs": "i-as",
    "IA": "i-a",
    "AI": "ei-ai",
    "ML": "eme-ele",
    "DL": "de-ele",
    "LLMs": "ele-ele-emes",
    "LLM": "ele-ele-eme",
    "NLP": "ene-ele-pe",
    "PLN": "pe-ele-ene",
    "GPUs": "je-pe-ús",
    "GPU": "je-pe-ú",
    "CPUs": "ce-pe-ús",
    "CPU": "ce-pe-ú",
    "TPUs": "te-pe-ús",
    "TPU": "te-pe-ú",
    "NPUs": "ene-pe-ús",
    "NPU": "ene-pe-ú",
    "RAM": "ram",
    "SSD": "ese-ese-de",
    "APIs": "a-pe-ís",
    "API": "a-pe-í",
    "SDK": "ese-de-ka",
    "URLs": "u-ere-eles",
    "URL": "u-ere-ele",
    "HTTPS": "hache-te-te-pe-ese",
    "HTTP": "hache-te-te-pe",
    "HTML": "hache-te-eme-ele",
    "CSS": "ce-ese-ese",
    "NoSQL": "no-ese-cu-ele",
    "SQL": "ese-cu-ele",
    "JSON": "yeison",
    "XML": "equis-eme-ele",
    "CSV": "ce-ese-uve",
    "PDF": "pe-de-efe",
    "CNNs": "ce-ene-enes",
    "CNN": "ce-ene-ene",
    "RNNs": "erre-ene-enes",
    "RNN": "erre-ene-ene",
    "LSTMs": "ele-ese-te-emes",
    "LSTM": "ele-ese-te-eme",
    "GANs": "gans",
    "GAN": "gan",
    "RAG": "rag",
    "GPT": "je-pe-te",
    "TI": "te-í",
    "IoT": "i-o-te",
    "1D": "un de",
    "2D": "dos de",
    "3D": "tres de",
    "4D": "cuatro de",
    "X": "equis",
    "Y": "ye",
    "Z": "zeta",
    "W": "doble ve",
    "K": "ka",
}

UNIDADES_PTBR: dict[str, tuple[str, str]] = {
    "ms": ("milissegundo", "milissegundos"),
    "s": ("segundo", "segundos"),
    "min": ("minuto", "minutos"),
    "h": ("hora", "horas"),
    "Hz": ("hertz", "hertz"),
    "kHz": ("quilohertz", "quilohertz"),
    "MHz": ("megahertz", "megahertz"),
    "GHz": ("gigahertz", "gigahertz"),
    "KB": ("quilobyte", "quilobytes"),
    "MB": ("megabyte", "megabytes"),
    "GB": ("gigabyte", "gigabytes"),
    "TB": ("terabyte", "terabytes"),
    "km": ("quilômetro", "quilômetros"),
    "cm": ("centímetro", "centímetros"),
    "mm": ("milímetro", "milímetros"),
}


# ---------------------------------------------------------------------------
# 5. Números por Extenso em Português e Espanhol
# ---------------------------------------------------------------------------
UNIDADES_ES: dict[str, tuple[str, str]] = {
    "ms": ("milisegundo", "milisegundos"),
    "s": ("segundo", "segundos"),
    "min": ("minuto", "minutos"),
    "h": ("hora", "horas"),
    "Hz": ("hercio", "hercios"),
    "kHz": ("kilohercio", "kilohercios"),
    "MHz": ("megahercio", "megahercios"),
    "GHz": ("gigahercio", "gigahercios"),
    "KB": ("kilobyte", "kilobytes"),
    "MB": ("megabyte", "megabytes"),
    "GB": ("gigabyte", "gigabytes"),
    "TB": ("terabyte", "terabytes"),
    "km": ("kilómetro", "kilómetros"),
    "cm": ("centímetro", "centímetros"),
    "mm": ("milímetro", "milímetros"),
}

# --- Português ---
_UNIDADES = [
    "zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove",
    "dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete",
    "dezoito", "dezenove",
]
_DEZENAS = [
    "", "", "vinte", "trinta", "quarenta", "cinquenta",
    "sessenta", "setenta", "oitenta", "noventa",
]
_CENTENAS = [
    "", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos",
    "seiscentos", "setecentos", "oitocentos", "novecentos",
]


def _ate_999(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "cem"
    partes = []
    c, resto = divmod(n, 100)
    if c:
        partes.append(_CENTENAS[c])
    if resto:
        if resto < 20:
            partes.append(_UNIDADES[resto])
        else:
            d, u = divmod(resto, 10)
            partes.append(_DEZENAS[d])
            if u:
                partes.append(_UNIDADES[u])
    return " e ".join(partes)


def numero_por_extenso(n: int) -> str:
    """Converte um inteiro não-negativo (até 999.999.999.999) para extenso em PT-BR."""
    if n == 0:
        return "zero"
    if n < 0:
        return "menos " + numero_por_extenso(-n)

    grupos = [
        (1_000_000_000, "bilhão", "bilhões"),
        (1_000_000, "milhão", "milhões"),
        (1_000, "mil", "mil"),
        (1, "", ""),
    ]
    partes: list[str] = []
    restante = n
    for divisor, sing, plur in grupos:
        if restante >= divisor:
            q, restante = divmod(restante, divisor)
            if divisor == 1_000 and q == 1:
                partes.append((q, "mil"))
            else:
                sufixo = sing if q == 1 else plur
                texto_q = _ate_999(q)
                partes.append((q, f"{texto_q} {sufixo}".strip()))

    if len(partes) == 1:
        return partes[0][1]

    resultado = ", ".join(p[1] for p in partes[:-1])
    ult_q, ult_txt = partes[-1]
    conector = " e " if (ult_q < 100 or ult_q % 100 == 0) else " "
    return f"{resultado}{conector}{ult_txt}"


def _converter_decimal(parte_int: str, parte_dec: str) -> str:
    inteiro = numero_por_extenso(int(parte_int))
    zeros = len(parte_dec) - len(parte_dec.lstrip("0"))
    resto_str = parte_dec.lstrip("0")
    if not resto_str:
        dec_txt = "zero"
    else:
        prefixo_zeros = " ".join(["zero"] * zeros)
        valor_dec = numero_por_extenso(int(resto_str)) if len(resto_str) <= 3 else " ".join(
            _UNIDADES[int(d)] for d in resto_str
        )
        dec_txt = f"{prefixo_zeros} {valor_dec}".strip()
    return f"{inteiro} vírgula {dec_txt}"


def normalizar_numeros_e_simbolos_pt(texto: str) -> str:
    """Converte porcentagens, unidades e números para extenso em português."""
    # Milhares com ponto (ex.: 1.000, 10.000, 1.500.000)
    texto = re.sub(r"\b(\d{1,3})(?:\.(\d{3}))+\b", lambda m: m.group(0).replace(".", ""), texto)

    # Porcentagens decimais e inteiras (ex.: 95%, 3,5%, 3.5%)
    def _sub_pct(m: re.Match) -> str:
        int_p, dec_p = m.group(1), m.group(2)
        num_txt = _converter_decimal(int_p, dec_p) if dec_p else numero_por_extenso(int(int_p))
        return f"{num_txt} por cento"

    texto = re.sub(r"\b(\d+)(?:[,.](\d+))?\s*%", _sub_pct, texto)

    # Números seguidos de unidades técnicas (ex.: 24kHz, 250ms, 16GB)
    unidades_regex = "|".join(sorted(UNIDADES_PTBR.keys(), key=len, reverse=True))

    def _sub_unidade(m: re.Match) -> str:
        int_p, dec_p, un = m.group(1), m.group(2), m.group(3)
        num_txt = _converter_decimal(int_p, dec_p) if dec_p else numero_por_extenso(int(int_p))
        sing, plur = UNIDADES_PTBR[un]
        nome_un = sing if (int_p == "1" and not dec_p) else plur
        return f"{num_txt} {nome_un}"

    texto = re.sub(rf"\b(\d+)(?:[,.](\d+))?\s*({unidades_regex})\b", _sub_unidade, texto)

    # Decimais restantes (ex.: 3,14 ou 0.01)
    texto = re.sub(
        r"\b(\d+)[,.](\d+)\b",
        lambda m: _converter_decimal(m.group(1), m.group(2)),
        texto,
    )

    # Inteiros restantes (até 12 dígitos)
    texto = re.sub(
        r"\b(\d{1,12})\b",
        lambda m: numero_por_extenso(int(m.group(1))),
        texto,
    )
    return texto


# --- Espanhol ---
_UNIDADES_ES = [
    "cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
    "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete",
    "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidós", "veintitrés",
    "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve",
]
_DEZENAS_ES = [
    "", "", "", "treinta", "cuarenta", "cincuenta",
    "sesenta", "setenta", "ochenta", "noventa",
]
_CENTENAS_ES = [
    "", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos",
    "seiscientos", "setecientos", "ochocientos", "novecientos",
]


def _ate_999_es(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "cien"
    partes = []
    c, resto = divmod(n, 100)
    if c:
        partes.append(_CENTENAS_ES[c])
    if resto:
        if resto < 30:
            partes.append(_UNIDADES_ES[resto])
        else:
            d, u = divmod(resto, 10)
            txt_d = _DEZENAS_ES[d]
            if u:
                partes.append(f"{txt_d} y {_UNIDADES_ES[u]}")
            else:
                partes.append(txt_d)
    return " ".join(partes)


def numero_por_extenso_es(n: int) -> str:
    """Converte um inteiro não-negativo (até 999.999.999.999) para extenso em Espanhol."""
    if n == 0:
        return "cero"
    if n < 0:
        return "menos " + numero_por_extenso_es(-n)

    def apocopar(t: str) -> str:
        if t.endswith("veintiuno"):
            return t[:-9] + "veintiún"
        if t.endswith("uno"):
            return t[:-3] + "un"
        return t

    partes = []
    restante = n
    for divisor, singular, plural in (
        (1_000_000_000_000, "billón", "billones"),
        (1_000_000, "millón", "millones"),
        (1_000, "mil", "mil"),
    ):
        q, restante = divmod(restante, divisor)
        if not q:
            continue
        if divisor == 1_000 and q == 1:
            partes.append("mil")
        else:
            cantidad = apocopar(numero_por_extenso_es(q))
            partes.append(f"{cantidad} {singular if q == 1 else plural}")
    if restante:
        partes.append(_ate_999_es(restante))
    return " ".join(partes)


def _converter_decimal_es(parte_int: str, parte_dec: str) -> str:
    inteiro = numero_por_extenso_es(int(parte_int))
    zeros = len(parte_dec) - len(parte_dec.lstrip("0"))
    resto_str = parte_dec.lstrip("0")
    if not resto_str:
        dec_txt = "cero"
    else:
        prefixo_zeros = " ".join(["cero"] * zeros)
        valor_dec = numero_por_extenso_es(int(resto_str)) if len(resto_str) <= 3 else " ".join(
            _UNIDADES_ES[int(d)] for d in resto_str
        )
        dec_txt = f"{prefixo_zeros} {valor_dec}".strip()
    return f"{inteiro} coma {dec_txt}"


def normalizar_numeros_e_simbolos_es(texto: str) -> str:
    """Converte porcentagens, unidades e números para extenso em espanhol."""
    # Milhares com ponto (ex.: 1.000, 10.000, 1.500.000)
    texto = re.sub(r"\b(\d{1,3})(?:\.(\d{3}))+\b", lambda m: m.group(0).replace(".", ""), texto)

    # Porcentagens decimais e inteiras (ex.: 95%, 3,5%, 3.5%)
    def _sub_pct(m: re.Match) -> str:
        int_p, dec_p = m.group(1), m.group(2)
        num_txt = _converter_decimal_es(int_p, dec_p) if dec_p else numero_por_extenso_es(int(int_p))
        return f"{num_txt} por ciento"

    texto = re.sub(r"\b(\d+)(?:[,.](\d+))?\s*%", _sub_pct, texto)

    # Números seguidos de unidades técnicas (ex.: 24kHz, 250ms, 16GB)
    unidades_regex = "|".join(sorted(UNIDADES_ES.keys(), key=len, reverse=True))

    def _sub_unidade(m: re.Match) -> str:
        int_p, dec_p, un = m.group(1), m.group(2), m.group(3)
        num_txt = _converter_decimal_es(int_p, dec_p) if dec_p else numero_por_extenso_es(int(int_p))
        sing, plur = UNIDADES_ES[un]
        nome_un = sing if (int_p == "1" and not dec_p) else plur
        return f"{num_txt} {nome_un}"

    texto = re.sub(rf"\b(\d+)(?:[,.](\d+))?\s*({unidades_regex})\b", _sub_unidade, texto)

    # Decimais restantes (ex.: 3,14 ou 0.01)
    texto = re.sub(
        r"\b(\d+)[,.](\d+)\b",
        lambda m: _converter_decimal_es(m.group(1), m.group(2)),
        texto,
    )

    # Inteiros restantes (até 12 dígitos)
    texto = re.sub(
        r"\b(\d{1,12})\b",
        lambda m: numero_por_extenso_es(int(m.group(1))),
        texto,
    )
    return texto


# ---------------------------------------------------------------------------
# 6. Pipelines de Normalização
# ---------------------------------------------------------------------------
def expandir_abreviacoes(texto: str, idioma: str = "pt") -> str:
    """Expande abreviações com ponto antes de dividir o texto em frases."""
    lista = ABREVIACOES_ES if idioma == "es" else ABREVIACOES_PT
    for padrao, subst in lista:
        texto = re.sub(padrao, subst, texto, flags=re.IGNORECASE)
    return texto


def normalizar_termos_tecnicos(
    texto: str,
    idioma: str = "pt",
    glossario_extra: dict[str, str] | None = None,
) -> str:
    """Aplica siglas (case-sensitive) e termos técnicos em inglês (case-insensitive)."""
    siglas = SIGLAS_ES if idioma == "es" else SIGLAS_PTBR
    termos_base = TERMOS_INGLES_ES if idioma == "es" else TERMOS_INGLES_PTBR

    # Uma única substituição impede que a pronúncia inserida seja processada de novo.
    termos = {k.lower(): v for k, v in termos_base.items()}
    if glossario_extra:
        termos.update({k.lower(): str(v) for k, v in glossario_extra.items()
                       if not isinstance(v, dict)})
        por_idioma = glossario_extra.get(idioma, {})
        if isinstance(por_idioma, dict):
            termos.update({k.lower(): str(v) for k, v in por_idioma.items()})

    chaves = sorted(set(termos) | set(siglas), key=lambda k: (-len(k), k))
    padrao = r"\b(?:" + "|".join(re.escape(k) for k in chaves) + r")\b"

    def substituir(m: re.Match) -> str:
        original = m.group(0)
        termo = original.lower()
        if termo in termos:
            pronuncia = termos[termo]
            return (pronuncia[0].upper() + pronuncia[1:]
                    if original[0].isupper() and pronuncia else pronuncia)
        return siglas.get(original, original)

    texto = re.sub(padrao, substituir, texto, flags=re.IGNORECASE)

    return texto


def carregar_glossario(
    caminho: str | Path | None,
    texto_path: str | Path | None = None,
) -> dict[str, str | dict[str, str]]:
    """Carrega glossários opcionais com suporte a:
    1. Arquivo explícito JSON ou TXT (chave=valor ou 'termo': 'pronúncia').
    2. Glossário automático por texto: se existir '<texto>.glossario.json' ou '<texto>.glossario.txt'.
    3. Glossário global do projeto: se existir 'glossario.json' no diretório de trabalho.
    """
    glossario: dict[str, str | dict[str, str]] = {}

    def _ler_arquivo(p: Path):
        conteudo = p.read_text(encoding="utf-8").strip()
        if not conteudo:
            return {}
        if p.suffix.lower() == ".json":
            dados = json.loads(conteudo)
            if not isinstance(dados, dict):
                raise ValueError(f"O glossário {p} deve conter um objeto JSON.")
            return dados
        else:  # formato texto simples: termo = pronúncia
            d = {}
            for linha in conteudo.splitlines():
                linha = linha.strip()
                if not linha or linha.startswith("#"):
                    continue
                if "=" in linha:
                    termo, pron = linha.split("=", 1)
                elif ":" in linha:
                    termo, pron = linha.split(":", 1)
                else:
                    continue
                d[termo.strip()] = pron.strip()
            return d

    def mesclar(dados):
        for chave, valor in dados.items():
            if isinstance(valor, dict) and isinstance(glossario.get(chave), dict):
                glossario[chave].update(valor)
            else:
                glossario[chave] = valor

    # Ordem de prioridade (o mais específico sobrescreve):
    # 1. glossario.json / glossario.txt na raiz do projeto
    for padrao in ("glossario.json", "glossario.txt"):
        g_proj = Path(padrao)
        if g_proj.is_file():
            mesclar(_ler_arquivo(g_proj))

    # 2. Glossário associado ao arquivo do texto (ex: teste1.glossario.json)
    if texto_path:
        tp = Path(texto_path)
        for ext in (".glossario.json", ".glossario.txt"):
            g_txt = tp.with_name(f"{tp.stem}{ext}")
            if g_txt.is_file():
                mesclar(_ler_arquivo(g_txt))

    # 3. Caminho explicitamente passado por parâmetro (--glossario)
    if caminho:
        cp = Path(caminho)
        if not cp.is_file():
            raise FileNotFoundError(f"Arquivo de glossário não encontrado: {caminho}")
        mesclar(_ler_arquivo(cp))

    return glossario


def normalizar_para_fala(
    texto: str,
    idioma: str = "auto",
    glossario_extra: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Pipeline completo de normalização para síntese no XTTS v2.

    Retorna:
        tuple[texto_normalizado, idioma_detectado_ou_usado]
    """
    lang = detectar_idioma(texto) if idioma == "auto" else idioma

    def _normalizar_trecho(trecho: str) -> str:
        t = expandir_abreviacoes(trecho, idioma=lang)
        t = normalizar_termos_tecnicos(t, idioma=lang, glossario_extra=glossario_extra)
        if lang == "pt":
            t = normalizar_numeros_e_simbolos_pt(t)
        elif lang == "es":
            t = normalizar_numeros_e_simbolos_es(t)
        return t

    # Tags de direção de voz ([pausa:1.5s], [enfase]...) não podem ser normalizadas:
    # normaliza só o texto entre elas e preserva as tags intactas.
    partes = re.split(r"(\[[^\]\n]+\])", texto)
    resultado = "".join(
        p if (p.startswith("[") and p.endswith("]")) else _normalizar_trecho(p)
        for p in partes
    )
    return resultado, lang
