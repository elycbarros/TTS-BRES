#!/usr/bin/env python3
"""Segmentação de texto, extração de tags de expressividade e preparação de blocos."""
import math
import re
import unicodedata

from normalizador import (
    detectar_idioma,
    expandir_abreviacoes,
    normalizar_para_fala,
)
from vozes import TONS_PREDEFINIDOS, resolver_locutor

SAMPLE_RATE = 24000
MAX_CHARS = 200  # XTTS v2 avisa truncamento acima de ~200 caracteres
PALAVRAS_POR_MIN = 150  # 450 palavras ~ 3 minutos
LIMITE_LONGO = 450  # acima disso, divide em blocos
MAX_PALAVRAS_BLOCO = 150


def contar_palavras(texto: str) -> int:
    """Conta a quantidade de palavras no texto."""
    return len(texto.split())


def analise_previa(texto: str) -> dict:
    """Calcula estimativas de contagem de palavras, duração e necessidade de divisão em blocos."""
    palavras = contar_palavras(texto)
    return {
        "palavras_estimadas": palavras,
        "duracao_estimada_min": round(palavras / PALAVRAS_POR_MIN, 1),
        "precisa_dividir": palavras > LIMITE_LONGO,
    }


def extrair_tags_expressividade(texto: str) -> list[tuple[str, dict]]:
    """Extrai tags de direção de voz: [pausa:Xms], [pausa:Xs], [respiro], [enfase], [sussurro], [tom:X].

    Retorna uma lista ordenada de (texto, modificadores):
      - pausa/respiro viram um item próprio ("", {"pausa_extra_ms": N}) NA POSIÇÃO da tag;
      - enfase/sussurro/tom viram modificadores aplicados ao próximo trecho de texto.
    """
    if re.search(r"\[[^\]]*$|^[^\[]*\]", texto):
        raise ValueError("Tag com colchetes incompletos.")
    partes = re.split(r"(\[[^\[\]]*\])", texto)
    itens: list[tuple[str, dict]] = []
    volume_pendente: float | None = None
    tom_pendente: str | None = None

    for p in partes:
        p_strip = p.strip()
        if not p_strip:
            continue
        m_tag = re.fullmatch(r"\[([a-zA-Zçãéíóú0-9_.-]+)(?::([^\]]*))?\]", p_strip)
        if not m_tag:
            if "[" in p_strip or "]" in p_strip:
                raise ValueError(f"Tag inválida: {p_strip}")
            mods: dict = {}
            if tom_pendente is not None:
                preset = TONS_PREDEFINIDOS.get(tom_pendente.lower(), {})
                if "volume_offset_db" in preset:
                    mods["volume_offset_db"] = preset["volume_offset_db"]
                if "velocidade_fator" in preset:
                    mods["velocidade_fator"] = preset["velocidade_fator"]
                mods["tom"] = tom_pendente
            if volume_pendente is not None:
                mods["volume_offset_db"] = volume_pendente
            itens.append((p_strip, mods))
            volume_pendente = None
            tom_pendente = None
            continue

        tag_nome = m_tag.group(1).lower()
        tag_param_raw = (m_tag.group(2) or "").strip()
        tag_param = tag_param_raw.lower()

        if tag_nome in ("pausa", "silencio"):
            ms = 1000
            if m_tag.group(2) is not None:
                valor = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|s)?", tag_param)
                if not valor:
                    raise ValueError(f"Duração inválida na tag {p_strip}; use 800ms ou 1.5s.")
                duracao = float(valor.group(1)) * (1000 if valor.group(2) == "s" else 1)
                if not math.isfinite(duracao):
                    raise ValueError(f"Duração inválida na tag {p_strip}.")
                ms = int(duracao)
            itens.append(("", {"pausa_extra_ms": ms}))
        elif tag_nome in ("tom", "estilo"):
            if not tag_param_raw or not re.fullmatch(r"[a-zA-ZçãéíóúÁÉÍÓÚ0-9_./\\-]+", tag_param_raw):
                raise ValueError(f"Parâmetro inválido na tag {p_strip}; informe um estilo (ex.: calmo, enfatico) ou arquivo WAV.")
            tom_pendente = tag_param_raw
        elif m_tag.group(2) is not None:
            raise ValueError(f"A tag {tag_nome} não aceita parâmetros.")
        elif tag_nome in ("respiro", "respiracao"):
            itens.append(("", {"pausa_extra_ms": 400}))
        elif tag_nome in ("enfase", "destaque"):
            volume_pendente = 2.5
        elif tag_nome in ("sussurro", "baixo", "calmo"):
            volume_pendente = -4.0
        else:
            raise ValueError(f"Tag desconhecida: {p_strip}")

    return itens


def preparar_segmentos(
    texto: str,
    idioma: str,
    normalizar: bool = True,
    glossario_extra: dict | None = None,
) -> list[tuple[str, dict]]:
    """Interpreta tags inteiras antes de cortar apenas o texto para síntese."""
    # Valida antes da normalização para não transformar uma tag inválida em fala.
    extrair_tags_expressividade(texto)
    if normalizar:
        texto = normalizar_para_fala(texto, idioma=idioma, glossario_extra=glossario_extra)[0]
    segmentos = []
    for sub, mods in extrair_tags_expressividade(texto):
        if not sub:
            segmentos.append((sub, mods))
            continue
        for i, parte in enumerate(dividir_frases(sub)):
            segmentos.append((parte, mods if i == 0 else {}))
    return segmentos


def dividir_frases(paragrafo: str) -> list[str]:
    """Divide por frase e também em ponto e vírgula (;) ou dois-pontos (:);
    frases ainda longas (> MAX_CHARS) viram partes de tamanho parecido,
    cortando de preferência em vírgula."""
    frases = re.split(r"(?<=[.!?…;:])\s+", paragrafo.strip())
    saida = []
    for frase in frases:
        partes = -(-len(frase) // MAX_CHARS)  # teto da divisão
        while len(frase) > MAX_CHARS:
            alvo = len(frase) // partes
            pontuados = [m.end() for m in re.finditer(r"[,;:]\s", frase[:MAX_CHARS])]
            espacos = [m.end() for m in re.finditer(r"\s", frase[:MAX_CHARS])]
            candidatos = pontuados or espacos or [MAX_CHARS]
            corte = min(candidatos, key=lambda p: abs(p - alvo))
            saida.append(frase[:corte].strip())
            frase = frase[corte:].strip()
            partes -= 1
        if frase:
            saida.append(frase)
    return saida


def montar_itens(
    texto: str,
    normalizar: bool = True,
    idioma_padrao: str = "pt",
    detectar_por_paragrafo: bool = True,
) -> list[tuple[str, bool, str, str | None]]:
    """Retorna [(frase, fim_de_paragrafo, idioma_trecho, locutor_especifico)] sem nunca cortar uma frase."""
    itens = []
    for par in re.split(r"\n\s*\n", texto.strip()):
        par = " ".join(par.split())
        if not par:
            continue
        # 1) Verifica se o parágrafo define idioma ou personagem no início:
        # Ex: [Luis]: fala... OU [Alma]: fala... OU [pt]: fala... OU [es]: fala... OU [Alma|es]: fala...
        locutor_par = None
        lang_par = None

        m_char = re.match(r"^\[([a-zA-ZçãéíóúÁÉÍÓÚ0-9_|./\\\s-]+)\]\s*:\s*(.*)$", par)
        if m_char:
            tag_corpo = m_char.group(1).strip()
            par = m_char.group(2).strip()

            # Se contiver pipe, ex: [Alma|es]
            if "|" in tag_corpo:
                p_nome, p_lang = tag_corpo.split("|", 1)
                if not p_nome.strip():
                    raise ValueError("Informe o personagem antes de |, ou use [es]: / [pt]:.")
                locutor_par = resolver_locutor(p_nome, idioma_padrao, idioma_padrao)
                lang_par = p_lang.strip().lower()
            elif tag_corpo.lower() in ("pt", "es", "en"):
                lang_par = tag_corpo.lower()
            else:
                locutor_par = resolver_locutor(tag_corpo, idioma_padrao, idioma_padrao)

        if lang_par is not None and lang_par not in ("pt", "es"):
            raise ValueError(f"Idioma de parágrafo inválido: {lang_par!r}; use pt ou es.")
        lang = lang_par or (detectar_idioma(par) if detectar_por_paragrafo else idioma_padrao)
        if normalizar:
            par = expandir_abreviacoes(par, idioma=lang)
        frases = re.split(r"(?<=[.!?…])\s+", par)
        for i, f in enumerate(frases):
            itens.append((f, i == len(frases) - 1, lang, locutor_par))
    return itens


def dividir_em_blocos(itens: list[tuple[str, bool, str, str | None]], dividir: bool) -> list[list]:
    """Agrupa frases em blocos de até 150 palavras; cada bloco termina em fim de frase."""
    if not dividir:
        return [itens]
    blocos, atual, n = [], [], 0
    for item in itens:
        p = contar_palavras(item[0])
        if atual and n + p > MAX_PALAVRAS_BLOCO:
            blocos.append(atual)
            atual, n = [], 0
        atual.append(item)
        n += p
    if atual:
        blocos.append(atual)
    return blocos


def limpar_para_voz(trecho: str) -> str:
    """Texto enviado ao XTTS: sem pontuação de encerramento de frase (evita leitura literal
    da palavra 'ponto' ou 'punto') e sem ; e :, mas preservando vírgula ao final de cláusulas
    para manter a cadência e prosódia naturais."""
    t = unicodedata.normalize("NFC", trecho)
    teve_virgula = bool(re.search(r",\s*$", t))
    t = re.sub(r"\s*[;:]\s*", ", ", t)
    t = re.sub(r"[\s.,;:…]+$", "", t)
    t = re.sub(r"\.{2,}", ",", t)
    if teve_virgula:
        t = t + ","
    return t.strip()


def pausa_ms(trecho: str, fim_par: bool, args) -> int:
    """Pausa conforme a pontuação final: parágrafo > reticências > ponto > ;/: > vírgula."""
    if fim_par:
        return args.pausa_paragrafo
    fim = trecho.rstrip()
    if fim.endswith(("…", "...")):
        return args.pausa_reticencias
    if fim.endswith((".", "!", "?")):
        return args.pausa_frase
    if fim.endswith((";", ":")):
        return args.pausa_ponto_virgula
    return args.pausa_virgula
