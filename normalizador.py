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

from datetime import date
import json
from pathlib import Path
import re
import unicodedata

# Tabelas léxicas e dicionários desacoplados em módulo dedicado
from lexico import (
    ABREVIACOES_ES,
    ABREVIACOES_PT,
    DENOMINADORES_ES,
    DENOMINADORES_PTBR,
    LETRAS_ALFABETO_ES,
    LETRAS_ALFABETO_PTBR,
    ORDINAIS_ES,
    ORDINAIS_PTBR,
    POTENCIAS_ES,
    POTENCIAS_PTBR,
    SIGLAS_ES,
    SIGLAS_PTBR,
    TERMOS_INGLES_ES,
    TERMOS_INGLES_PTBR,
    UNIDADES_ES,
    UNIDADES_FEMININAS_ES,
    UNIDADES_FEMININAS_PTBR,
    UNIDADES_PTBR,
    _CENTENAS,
    _CENTENAS_ES,
    _DEZENAS,
    _DEZENAS_ES,
    _TOKENS_ES,
    _TOKENS_PT,
    _UNIDADES,
    _UNIDADES_ES,
)


# ---------------------------------------------------------------------------
# 1. Detecção Automática de Idioma
# ---------------------------------------------------------------------------
def detectar_idioma(texto: str) -> str:
    """Detecta automaticamente se o texto está em espanhol ('es') ou português ('pt')."""
    t = unicodedata.normalize("NFC", texto).lower()
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
# 2. Números por Extenso em Português
# ---------------------------------------------------------------------------
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
    partes: list[tuple[int, str]] = []
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

    resultado = " ".join(p[1] for p in partes[:-1])
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


# ---------------------------------------------------------------------------
# 3. Contextos Numéricos (Datas, Horários, Moedas em PT e ES)
# ---------------------------------------------------------------------------
def normalizar_contextos_numericos(texto: str, idioma: str) -> str:
    """Datas D/M/AAAA, horários 24 h, moedas explícitas e negativos PT/ES."""
    es = idioma == "es"
    numero = numero_por_extenso_es if es else numero_por_extenso
    meses = ("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre"
             if es else "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro").split()

    def data_por_extenso(m):
        dia, mes, ano = map(int, (m[1], m[3], m[4]))
        try:
            date(ano, mes, dia)
        except ValueError as exc:
            raise ValueError(f"Data inválida: {m[0]}") from exc
        dia_txt = ("primero" if es else "primeiro") if dia == 1 else numero(dia)
        return f"{dia_txt} de {meses[mes - 1]} de {numero(ano)}"

    texto = re.sub(r"(?<![\w/\-])(\d{1,2})([/\-])(\d{1,2})\2(\d{4})(?![\w/\-])", data_por_extenso, texto)

    def feminino(n):
        t = numero(n)
        if es:
            if t.endswith("veintiuno"):
                return t[:-9] + "veintiuna"
            return t[:-3] + "una" if t.endswith("uno") else t
        if t.endswith("dois"):
            return t[:-4] + "duas"
        return t[:-2] + "uma" if t.endswith("um") else t

    def horario(m):
        h, minuto, segundo = int(m[1]), int(m[2]), int(m[3] or 0)
        if h > 23 or minuto > 59 or segundo > 59:
            raise ValueError(f"Horário inválido: {m[0]}")
        hora = "hora" if h == 1 else "horas"
        partes = [f"{feminino(h)} {hora}"]

        def masculino(n):
            t = numero(n)
            if es and t.endswith('veintiuno'):
                return t[:-9] + 'veintiún'
            return t[:-3] + 'un' if es and t.endswith('uno') else t

        if minuto:
            partes.append(f"{masculino(minuto)} {'minuto' if minuto == 1 else 'minutos'}")
        if segundo:
            nome = ("segundo" if segundo == 1 else "segundos")
            partes.append(f"{masculino(segundo)} {nome}")
        return (" y " if es else " e ").join(partes)

    texto = re.sub(r"(?<![\w:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\w:])", horario, texto)

    def horario_h(m):
        h, minuto = int(m[1]), int(m[2])
        if h > 23 or minuto > 59 or not (1 <= len(m[2]) <= 2):
            raise ValueError(f"Horário inválido: {m[0]}")
        partes = [f"{feminino(h)} {'hora' if h == 1 else 'horas'}"]
        if minuto:
            t = numero(minuto)
            if es and t.endswith("veintiuno"):
                t = t[:-9] + "veintiún"
            elif es and t.endswith("uno"):
                t = t[:-3] + "un"
            partes.append(f"{t} {'minuto' if minuto == 1 else 'minutos'}")
        return (" y " if es else " e ").join(partes)

    texto = re.sub(r"(?<![\w:])(\d{1,2})h(\d{2})(?:min)?\b", horario_h, texto)

    moedas = {
        "brl": (("real", "reais"), ("real brasileño", "reales brasileños")),
        "usd": (("dólar", "dólares"), ("dólar estadounidense", "dólares estadounidenses")),
        "eur": (("euro", "euros"), ("euro", "euros")),
    }

    def _formatar_dinheiro(simbolo, valor, original):
        moeda = {"r$": "brl", "us$": "usd", "$": "usd", "€": "eur"}.get(simbolo.lower(), simbolo.lower())
        negativo = valor.startswith('-')
        valor = valor.lstrip('-').replace('.', '')
        inteiro, _, fracao = valor.partition(',')
        n, centavos = int(inteiro), int(fracao.ljust(2, '0') or '0')
        if n > 999_999_999_999:
            raise ValueError(f"Valor monetário fora do limite: {original}")

        def quantidade(n):
            t = numero(n)
            if es and t.endswith('veintiuno'):
                return t[:-9] + 'veintiún'
            if es and t.endswith('uno'):
                return t[:-3] + 'un'
            return t

        singular, plural = moedas[moeda][1 if es else 0]
        conector = " de " if n >= 1_000_000 and n % 1_000_000 == 0 else " "
        partes = [f"{quantidade(n)}{conector}{singular if n == 1 else plural}"]
        if centavos:
            nome = ('céntimo' if moeda == 'eur' and es else 'centavo')
            partes.append(f"{quantidade(centavos)} {nome if centavos == 1 else nome + 's'}")
        return ("menos " if negativo else "") + (" y " if es else " e ").join(partes)

    padrao_valor = r"-?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?"
    texto = re.sub(
        rf"(?<!\w)(R\$|US\$|BRL\b|USD\b|EUR\b|€|\$)\s*({padrao_valor})(?!\d|,\d|\.\d)",
        lambda m: _formatar_dinheiro(m[1], m[2], m[0]), texto, flags=re.IGNORECASE,
    )
    texto = re.sub(
        rf"(?<![\w,\.])({padrao_valor})\s*(€|\bEUR\b)(?!\w)",
        lambda m: _formatar_dinheiro(m[2], m[1], m[0]), texto, flags=re.IGNORECASE,
    )
    # Sinal unário: não converte o hífen de intervalos como 5-10.
    texto = re.sub(r"(?<![\w])-(?=\d)", "menos ", texto)
    return texto


def _ordinal_por_extenso(n: int, genero: str, es: bool) -> str | None:
    if not 1 <= n <= 99:
        return None
    unidades, dezenas = ORDINAIS_ES if es else ORDINAIS_PTBR
    d, u = divmod(n, 10)
    partes = [p for p in (dezenas[d], unidades[u]) if p]
    if genero == "a":
        partes = [p[:-1] + "a" for p in partes]
    elif genero == "r" and es:
        partes = ["primer" if p == "primero" else ("tercer" if p == "tercero" else p) for p in partes]
    return " ".join(partes)


def _normalizar_unidades_medidas_e_intervalos(texto: str, idioma: str) -> str:
    """Expande temperaturas, unidades com potência, razões, unidades simples, ordinais e intervalos."""
    es = idioma == "es"
    unidades = UNIDADES_ES if es else UNIDADES_PTBR
    femininas = UNIDADES_FEMININAS_ES if es else UNIDADES_FEMININAS_PTBR
    denominadores = DENOMINADORES_ES if es else DENOMINADORES_PTBR
    potencias = POTENCIAS_ES if es else POTENCIAS_PTBR
    converter_dec = _converter_decimal_es if es else _converter_decimal
    extenso = numero_por_extenso_es if es else numero_por_extenso

    def numero_unidade(int_p: str, dec_p: str | None, codigo: str) -> str:
        if dec_p:
            return converter_dec(int_p, dec_p)
        t = extenso(int(int_p))
        if codigo in femininas:
            if es:
                return t[:-9] + "veintiuna" if t.endswith("veintiuno") else (t[:-3] + "una" if t.endswith("uno") else t)
            return t[:-4] + "duas" if t.endswith("dois") else (t[:-2] + "uma" if t.endswith("um") else t)
        if es:
            return t[:-9] + "veintiún" if t.endswith("veintiuno") else (t[:-3] + "un" if t.endswith("uno") else t)
        return t

    # Temperaturas: 25 °C, -3,5°C, 70 °F
    escalas = {"C": "Celsius", "F": "Fahrenheit", "K": "Kelvin"}

    def _sub_temp(m: re.Match) -> str:
        int_p, dec_p, esc = m.group(1), m.group(2), m.group(3)
        um = int_p == "1" and not dec_p
        num_txt = numero_unidade(int_p, dec_p, esc)
        if esc == "K":
            un_txt = "kelvin"
        else:
            grau = ("grado" if um else "grados") if es else ("grau" if um else "graus")
            un_txt = f"{grau} {escalas[esc]}"
        return f"{num_txt} {un_txt}"

    texto = re.sub(r"\b(\d+)(?:[,.](\d+))?\s*°\s*([CFK])\b", _sub_temp, texto)

    unidades_regex = "|".join(sorted(unidades.keys(), key=len, reverse=True))
    denom_regex = "|".join(sorted(denominadores.keys(), key=len, reverse=True))

    # Unidades compostas: 80 km/h, 12,5 MB/s
    def _sub_composta(m: re.Match) -> str:
        int_p, dec_p, num_u, den_u = m.group(1), m.group(2), m.group(3), m.group(4)
        sing, plur = unidades[num_u]
        nome_num = sing if (int_p == "1" and not dec_p) else plur
        return f"{numero_unidade(int_p, dec_p, num_u)} {nome_num} por {denominadores[den_u]}"

    texto = re.sub(rf"\b(\d+)(?:[,.](\d+))?\s*({unidades_regex})/({denom_regex})\b", _sub_composta, texto)

    # Unidades com superíndice: 300 m², 2,5 km³
    def _sub_potencia(m: re.Match) -> str:
        int_p, dec_p, un, pot = m.group(1), m.group(2), m.group(3), m.group(4)
        um = int_p == "1" and not dec_p
        sing, plur = unidades[un]
        pot_sing, pot_plur = potencias[pot]
        return f"{numero_unidade(int_p, dec_p, un)} {sing if um else plur} {pot_sing if um else pot_plur}"

    texto = re.sub(rf"\b(\d+)(?:[,.](\d+))?\s*({unidades_regex})([²³])", _sub_potencia, texto)

    # Unidades simples: 24 kHz, 250ms, 5 kg, 2h
    def _sub_unidade(m: re.Match) -> str:
        int_p, dec_p, un = m.group(1), m.group(2), m.group(3)
        sing, plur = unidades[un]
        nome_un = sing if (int_p == "1" and not dec_p) else plur
        return f"{numero_unidade(int_p, dec_p, un)} {nome_un}"

    texto = re.sub(rf"\b(\d+)(?:[,.](\d+))?\s*({unidades_regex})\b", _sub_unidade, texto)

    # Ordinais: 1º, 1.º, 2ª, 2.ª e, em espanhol, 1er/3er
    def _sub_ordinal(m: re.Match) -> str:
        ind = m.group(2).lower()
        genero = "a" if ind in ("ª", "a") else ("r" if ind == "er" else "o")
        ext = _ordinal_por_extenso(int(m.group(1)), genero, es)
        return ext if ext is not None else m.group(0)

    padrao_ord = r"\b(\d{1,2})(?:\.\s*([ºªoa]|er)\b|([ºª])|(?<=1|3)(er)\b)" if es else r"\b(\d{1,2})(?:\.\s*([ºªoa])\b|([ºª]))"

    def _sub_ord_match(m: re.Match) -> str:
        ind = next(g for g in m.groups()[1:] if g is not None).lower()
        genero = "a" if ind in ("ª", "a") else ("r" if ind == "er" else "o")
        return _ordinal_por_extenso(int(m.group(1)), genero, es) or m.group(0)

    texto = re.sub(padrao_ord, _sub_ord_match, texto)

    # Intervalos numéricos (10-20, 1990–2000), após datas já terem sido convertidas
    conector = " a "
    texto = re.sub(
        r"(?<![\w/\-])(\d{1,4})\s*[–—-]\s*(\d{1,4})(?![\w/\-])",
        lambda m: f"{extenso(int(m[1]))}{conector}{extenso(int(m[2]))}",
        texto,
    )
    return texto


def normalizar_numeros_e_simbolos_pt(texto: str) -> str:
    """Converte porcentagens, unidades e números para extenso em português."""
    texto = normalizar_contextos_numericos(texto, "pt")
    # Milhares com ponto (ex.: 1.000, 10.000, 1.500.000)
    texto = re.sub(r"\b(\d{1,3})(?:\.(\d{3}))+\b", lambda m: m.group(0).replace(".", ""), texto)

    # Porcentagens decimais e inteiras (ex.: 95%, 3,5%, 3.5%)
    def _sub_pct(m: re.Match) -> str:
        int_p, dec_p = m.group(1), m.group(2)
        num_txt = _converter_decimal(int_p, dec_p) if dec_p else numero_por_extenso(int(int_p))
        return f"{num_txt} por cento"

    texto = re.sub(r"\b(\d+)(?:[,.](\d+))?\s*%", _sub_pct, texto)
    texto = _normalizar_unidades_medidas_e_intervalos(texto, "pt")

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


# ---------------------------------------------------------------------------
# 4. Números por Extenso em Espanhol
# ---------------------------------------------------------------------------
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
    texto = normalizar_contextos_numericos(texto, "es")
    # Milhares com ponto (ex.: 1.000, 10.000, 1.500.000)
    texto = re.sub(r"\b(\d{1,3})(?:\.(\d{3}))+\b", lambda m: m.group(0).replace(".", ""), texto)

    # Porcentagens decimais e inteiras (ex.: 95%, 3,5%, 3.5%)
    def _sub_pct(m: re.Match) -> str:
        int_p, dec_p = m.group(1), m.group(2)
        num_txt = _converter_decimal_es(int_p, dec_p) if dec_p else numero_por_extenso_es(int(int_p))
        return f"{num_txt} por ciento"

    texto = re.sub(r"\b(\d+)(?:[,.](\d+))?\s*%", _sub_pct, texto)
    texto = _normalizar_unidades_medidas_e_intervalos(texto, "es")

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
# 5. Pipelines de Normalização e Expansão
# ---------------------------------------------------------------------------
def expandir_abreviacoes(texto: str, idioma: str = "pt") -> str:
    """Expande abreviações com ponto antes de dividir o texto em frases."""
    texto = unicodedata.normalize("NFC", texto)
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
    texto = unicodedata.normalize("NFC", texto)
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


def soletrar_siglas_e_letras(texto: str, idioma: str = "pt") -> str:
    """Expande referências explícitas a letras do alfabeto e siglas consonantais não cadastradas."""
    letras_map = LETRAS_ALFABETO_ES if idioma == "es" else LETRAS_ALFABETO_PTBR
    palavra_barra = "barra"

    # 1. Padrões de pares com barra como A/B, X/Y (apenas letras individuais isoladas)
    def _sub_barra(m: re.Match) -> str:
        l1 = m.group(1).upper()
        l2 = m.group(2).upper()
        p1 = letras_map.get(l1, l1)
        p2 = letras_map.get(l2, l2)
        return f"{p1} {palavra_barra} {p2}"

    texto = re.sub(r"(?<![A-Za-z0-9])([A-Za-z])/([A-Za-z])(?![A-Za-z0-9])", _sub_barra, texto)

    # 2. Letras isoladas entre aspas: "A", 'B', «C»
    def _sub_aspas(m: re.Match) -> str:
        l = m.group(2).upper()
        return f"{m.group(1)}{letras_map.get(l, l)}{m.group(3)}"

    texto = re.sub(r'([“"\'«])([A-Za-z])([”"\'»])', _sub_aspas, texto)

    # 3. Intervalos e alternâncias explícitas de letras: "de A a Z", "de A até B", "A ou B", "A e B"
    if idioma == "pt":
        def _sub_intervalo(m: re.Match) -> str:
            l1 = m.group(1).upper()
            prep = m.group(2)
            l2 = m.group(3).upper()
            return f"{letras_map.get(l1, l1)} {prep} {letras_map.get(l2, l2)}"

        texto = re.sub(r"\b([A-Za-z])\s+(a|até|ou|e)\s+([A-Za-z])\b", _sub_intervalo, texto)
    else:
        def _sub_intervalo_es(m: re.Match) -> str:
            l1 = m.group(1).upper()
            prep = m.group(2)
            l2 = m.group(3).upper()
            return f"{letras_map.get(l1, l1)} {prep} {letras_map.get(l2, l2)}"

        texto = re.sub(r"\b([A-Za-z])\s+(a|hasta|o)\s+([A-Za-z])\b", _sub_intervalo_es, texto)

    # 4. Letras isoladas acompanhadas de qualificador contextual (letra A, vitamina C, ponto B, tipo D...)
    if idioma == "pt":
        padrao_prefixo = (
            r"\b(letra|letras|vitamina|vitaminas|tipo|tipos|ponto|pontos|faixa|faixas|"
            r"classe|classes|grupo|grupos|categoria|categorias|modo|modos|grau|graus|"
            r"nível|níveis|caso|casos|opção|opções|item|itens|anexo|anexos|apêndice|apêndices|"
            r"eixo|eixos|plano|planos|modelo|modelos|teste|testes|fase|fases|bloco|blocos|canal|canais)\s+([A-Za-z])\b"
        )
    else:
        padrao_prefixo = (
            r"\b(letra|letras|vitamina|vitaminas|tipo|tipos|punto|puntos|faja|fajas|"
            r"clase|clases|grupo|grupos|categoría|categorías|modo|modos|grado|grados|"
            r"nivel|niveles|caso|casos|opción|opciones|ítem|ítems|anexo|anexos|apéndice|apéndices|"
            r"eje|ejes|plan|planes|modelo|modelos|test|tests|fase|fases|bloque|bloques|canal|canales)\s+([A-Za-z])\b"
        )

    def _sub_letra(m: re.Match) -> str:
        prefixo = m.group(1)
        letra = m.group(2).upper()
        return f"{prefixo} {letras_map.get(letra, letra)}"

    texto = re.sub(padrao_prefixo, _sub_letra, texto, flags=re.IGNORECASE)

    # 5. Siglas puramente consonantais de 2 a 6 letras não cadastradas (ex.: SP, RJ, DF, CPFL, CNPJ...)
    def _soletrar_consoantes(m: re.Match) -> str:
        sigla = m.group(0)
        return "-".join(letras_map.get(c, c) for c in sigla)

    texto = re.sub(r"\b[BCDFGHJKLMNPQRSTVWXYZ]{2,6}\b", _soletrar_consoantes, texto)

    # 6. Consoantes maiúsculas individuais isoladas (B, C, D, F, G, H, J, K, L, M, N, P, Q, R, S, T, V, W, X, Y, Z)
    if idioma == "pt":
        def _sub_consoante_isolada(m: re.Match) -> str:
            c = m.group(0)
            return letras_map.get(c, c)

        texto = re.sub(r"\b[BCDFGHJKLMNPQRSTVWXYZ]\b", _sub_consoante_isolada, texto)
    else:
        def _sub_consoante_isolada_es(m: re.Match) -> str:
            c = m.group(0)
            return letras_map.get(c, c)

        texto = re.sub(r"\b[BCDFGHJKLMNPQRSTVWXZ]\b", _sub_consoante_isolada_es, texto)

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
    texto = unicodedata.normalize("NFC", texto)
    lang = detectar_idioma(texto) if idioma == "auto" else idioma

    def _normalizar_trecho(trecho: str) -> str:
        t = expandir_abreviacoes(trecho, idioma=lang)
        if lang == "pt":
            t = normalizar_numeros_e_simbolos_pt(t)
        elif lang == "es":
            t = normalizar_numeros_e_simbolos_es(t)
        t = soletrar_siglas_e_letras(t, idioma=lang)
        t = normalizar_termos_tecnicos(t, idioma=lang, glossario_extra=glossario_extra)
        if lang == "pt":
            # Guia fonético para paroxítonas suscetíveis a deslocamento tônico no XTTS v2
            from lexico import GUIA_TONICIDADE_PTBR
            for padrao, subst in GUIA_TONICIDADE_PTBR:
                t = re.sub(padrao, subst, t)
        return t

    # Tags de direção de voz ([pausa:1.5s], [enfase]...) não podem ser normalizadas:
    # normaliza só o texto entre elas e preserva as tags intactas.
    partes = re.split(r"(\[[^\]\n]+\])", texto)
    resultado = "".join(
        p if (p.startswith("[") and p.endswith("]")) else _normalizar_trecho(p)
        for p in partes
    )
    return resultado, lang
