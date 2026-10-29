#!/usr/bin/env python3
"""Converte um texto pronto (.txt) em áudio MP3 (e WAV opcional) usando XTTS v2.

Suporta Português Brasileiro ('pt') e Espanhol ('es') com detecção automática de idioma
e seleção da voz ideal para cada idioma.

Fluxo:
  1. Detecta o idioma automaticamente ('pt' ou 'es') e seleciona o locutor padrão ideal
     ('Luis Moray' para PT-BR, 'Alma María' para Espanhol).
  2. Análise prévia: estima palavras e duração (>450 palavras ~ 3 min = longo).
  3. Se longo, divide em blocos independentes de até 150 palavras, sempre
     terminando em fim de frase.
  4. Normaliza o texto adaptado ao idioma (termos técnicos, siglas e abreviações).
  5. Gera cada trecho, remove o silêncio residual do XTTS nas pontas, normaliza
     o volume (dBFS) e aplica a pausa exata da pontuação.

Uso:
    python tts.py texto.txt                       # detecta idioma e voz automaticamente
    python tts.py texto.txt --saida audio         # gera audio.mp3 e audio.blocos.json
    python tts.py texto.txt --idioma es           # força espanhol
    python tts.py texto.txt --locutor "Xavier Hayasaka" # especifica outro locutor
"""
import argparse
import math
import os
import re
import shutil
import sys
import unicodedata
import warnings
from importlib.metadata import version, PackageNotFoundError

from audio_persistente import CacheSegmentos, exportar, hash_arquivo, higienizar_referencia, salvar_json
from pathlib import Path

os.environ.setdefault("COQUI_TOS_AGREED", "1")  # aceita a licença do XTTS v2
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # Mac: cai para CPU em ops não suportadas

import numpy as np

with warnings.catch_warnings():
    warnings.simplefilter("ignore", RuntimeWarning)
    from pydub import AudioSegment

from normalizador import (
    carregar_glossario,
    detectar_idioma,
    expandir_abreviacoes,
    normalizar_para_fala,
)

# Evita UnicodeEncodeError no console do Windows (acentos, reticências).
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def configurar_ffmpeg() -> None:
    """Usa o ffmpeg do sistema; se não houver, usa o embutido do imageio-ffmpeg."""
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg

        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        print("Aviso: ffmpeg não encontrado; a exportação MP3 pode falhar.")


SAMPLE_RATE = 24000
MAX_CHARS = 200  # XTTS v2 avisa truncamento acima de ~200 caracteres
PALAVRAS_POR_MIN = 150  # 450 palavras ~ 3 minutos
LIMITE_LONGO = 450  # acima disso, divide em blocos
MAX_PALAVRAS_BLOCO = 150

VOZES_PADRAO = {
    "pt": "Luis Moray",
    "es": "Alma María",
}

# Mapeamento de apelidos de personagens para nomes oficiais de locutores do XTTS v2
PERSONAGENS_MAP = {
    "narrador": "Luis Moray",
    "luis": "Luis Moray",
    "moray": "Luis Moray",
    "alma": "Alma María",
    "maria": "Alma María",
    "marcos": "Marcos Rudaski",
    "rudaski": "Marcos Rudaski",
    "gilberto": "Gilberto Mathias",
    "mathias": "Gilberto Mathias",
    "ana": "Ana Florence",
    "florence": "Ana Florence",
    "sofia": "Sofia Hellen",
    "hellen": "Sofia Hellen",
    "xavier": "Xavier Hayasaka",
    "hayasaka": "Xavier Hayasaka",
    "claribel": "Claribel Dervla",
    "daisy": "Daisy Studious",
    "gracie": "Gracie Wise",
    "ferran": "Ferran Simen",
    "tammie": "Tammie Ema",
    "ema": "Tammie Ema",
}


def contar_palavras(texto: str) -> int:
    return len(texto.split())


def analise_previa(texto: str) -> dict:
    palavras = contar_palavras(texto)
    return {
        "palavras_estimadas": palavras,
        "duracao_estimada_min": round(palavras / PALAVRAS_POR_MIN, 1),
        "precisa_dividir": palavras > LIMITE_LONGO,
    }


TONS_PREDEFINIDOS: dict[str, dict] = {
    "enfatico": {"volume_offset_db": 2.5, "velocidade_fator": 1.05},
    "enfase": {"volume_offset_db": 2.5, "velocidade_fator": 1.05},
    "animado": {"volume_offset_db": 2.0, "velocidade_fator": 1.08},
    "calmo": {"volume_offset_db": -2.0, "velocidade_fator": 0.92},
    "suave": {"volume_offset_db": -2.5, "velocidade_fator": 0.94},
    "sussurro": {"volume_offset_db": -4.0, "velocidade_fator": 0.90},
    "serio": {"volume_offset_db": 0.0, "velocidade_fator": 0.95},
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


def preparar_segmentos(texto: str, idioma: str, normalizar: bool = True,
                       glossario_extra: dict | None = None) -> list[tuple[str, dict]]:
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


EXTENSOES_AUDIO = (".wav", ".mp3", ".flac", ".m4a", ".ogg")


def eh_caminho_audio(nome: str | None) -> bool:
    return bool(nome and nome.strip().lower().endswith(EXTENSOES_AUDIO))


def resolver_caminho_voz(caminho_str: str, base_texto: Path | None = None) -> str:
    candidato = Path(caminho_str.strip()).expanduser()
    if candidato.is_file():
        return str(candidato.resolve())
    if base_texto is not None and not candidato.is_absolute():
        relativo = (base_texto.parent / candidato).expanduser()
        if relativo.is_file():
            return str(relativo.resolve())
    raise ValueError(f"Áudio de referência não encontrado: {caminho_str}")


def carregar_vozes_personagens(especificacao: str | None, base_texto: Path | None = None) -> dict[str, str]:
    if not especificacao or not especificacao.strip():
        return {}
    mapa: dict[str, str] = {}
    for item in especificacao.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"Mapeamento de voz inválido ({item!r}); use personagem=arquivo.wav.")
        chave, caminho = item.split("=", 1)
        chave = chave.strip().lower()
        caminho = caminho.strip()
        if not chave or not caminho:
            raise ValueError(f"Mapeamento de voz inválido ({item!r}); use personagem=arquivo.wav.")
        resolvido = resolver_caminho_voz(caminho, base_texto)
        mapa[chave] = resolvido
        oficial = PERSONAGENS_MAP.get(chave)
        if oficial:
            mapa[oficial.lower()] = resolvido
    return mapa


def resolver_voz_segmento(
    locutor_char: str | None,
    vozes_personagens: dict[str, str],
    base_texto: Path | None = None,
) -> str | None:
    if not locutor_char:
        return None
    chave = locutor_char.strip().lower()
    if chave in vozes_personagens:
        return vozes_personagens[chave]
    if eh_caminho_audio(locutor_char):
        return resolver_caminho_voz(locutor_char, base_texto)
    return None


def resolver_voz_tom(
    mods: dict,
    vozes_tons: dict[str, str],
    base_texto: Path | None = None,
) -> str | None:
    tom = mods.get("tom")
    if tom:
        chave = tom.strip().lower()
        if chave in vozes_tons:
            return vozes_tons[chave]
        if eh_caminho_audio(tom):
            return resolver_caminho_voz(tom, base_texto)
        if chave not in TONS_PREDEFINIDOS:
            raise ValueError(f"Tom desconhecido ({tom!r}); use {', '.join(sorted(TONS_PREDEFINIDOS))} ou mapeie em --vozes-tons.")
        return None
    offset = mods.get("volume_offset_db")
    if offset == 2.5 and ("enfase" in vozes_tons or "enfatico" in vozes_tons):
        return vozes_tons.get("enfase") or vozes_tons.get("enfatico")
    if offset == -4.0 and "sussurro" in vozes_tons:
        return vozes_tons["sussurro"]
    return None


def resolver_locutor(nome_ou_tag: str | None, idioma_trecho: str, locutor_fallback: str) -> str:
    """Resolve o locutor a partir de um nome de personagem, nome oficial ou idioma."""
    if not nome_ou_tag:
        return VOZES_PADRAO.get(idioma_trecho, locutor_fallback)
    alvo = nome_ou_tag.strip().lower()
    return PERSONAGENS_MAP.get(alvo, nome_ou_tag.strip())


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


def escolher_dispositivo(pedido: str = "auto") -> str:
    """auto => CUDA (NVIDIA), MPS (Apple Silicon GPU) ou CPU como fallback seguro."""
    import torch

    if pedido == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    if pedido == "cuda" and not torch.cuda.is_available():
        print("CUDA indisponível; usando CPU.")
        return "cpu"
    if pedido == "mps" and not torch.backends.mps.is_available():
        print("MPS indisponível; usando CPU.")
        return "cpu"
    return pedido


def compactar_silencios_internos(
    arr: np.ndarray,
    sr: int = SAMPLE_RATE,
    limiar: float = 0.008,
    max_pausa_ms: int = 150,
    alvo_ms: int = 90,
) -> np.ndarray:
    """Encurta pausas internas excessivas geradas pelo XTTS (ex.: antes de 'vírgula' em decimais)."""
    janela = max(1, sr // 100)
    n_janelas = len(arr) // janela
    max_j = max(1, max_pausa_ms // 10)
    alvo_j = max(1, min(max_j, alvo_ms // 10))
    if n_janelas <= max_j + 2:
        return arr

    recorte = arr[: n_janelas * janela].reshape(n_janelas, janela)
    rms = np.sqrt(np.mean(recorte * recorte, axis=1))

    partes: list[np.ndarray] = []
    i = 0
    alterado = False
    while i < n_janelas:
        if rms[i] <= limiar:
            j = i
            while j < n_janelas and rms[j] <= limiar:
                j += 1
            if i > 0 and j < n_janelas and (j - i) > max_j:
                metade = alvo_j // 2
                resto = alvo_j - metade
                partes.append(arr[i * janela : (i + metade) * janela])
                partes.append(arr[(j - resto) * janela : j * janela])
                alterado = True
            else:
                partes.append(arr[i * janela : j * janela])
            i = j
        else:
            j = i
            while j < n_janelas and rms[j] > limiar:
                j += 1
            partes.append(arr[i * janela : j * janela])
            i = j

    if not alterado:
        return arr
    if n_janelas * janela < len(arr):
        partes.append(arr[n_janelas * janela :])
    return np.concatenate(partes) if partes else arr


def cortar_silencio_pontas(
    wav: np.ndarray,
    sr: int = SAMPLE_RATE,
    limiar_db: float = -42.0,
    margem_ini_ms: int = 30,
    margem_fim_ms: int = 90,
    max_pausa_interna_ms: int = 150,
    pausa_interna_alvo_ms: int = 90,
) -> np.ndarray:
    """Remove o excesso de silêncio residual do XTTS v2 nas pontas e compacta pausas
    internas excessivas, preservando margens naturais (30 ms início, 90 ms fim)."""
    arr = np.asarray(wav, dtype=np.float32)
    if arr.size == 0:
        return arr
    arr = arr - float(np.mean(arr))

    janela = max(1, sr // 100)
    n_janelas = len(arr) // janela
    if n_janelas < 3:
        return arr

    recorte = arr[: n_janelas * janela].reshape(n_janelas, janela)
    rms = np.sqrt(np.mean(recorte * recorte, axis=1))
    ref = float(np.percentile(rms, 95))
    if ref <= 1e-5:
        return arr

    limiar = max(ref * (10.0 ** (limiar_db / 20.0)), 0.003)
    ativos = np.flatnonzero(rms > limiar)
    if ativos.size == 0:
        return arr

    ini_amostra = max(0, int(ativos[0]) * janela - (sr * margem_ini_ms) // 1000)
    fim_amostra = min(len(arr), int(ativos[-1] + 1) * janela + (sr * margem_fim_ms) // 1000)
    recortado = arr[ini_amostra:fim_amostra]
    if max_pausa_interna_ms > 0:
        limiar_interno = max(ref * (10.0 ** (-38.0 / 20.0)), 0.005)
        recortado = compactar_silencios_internos(
            recortado,
            sr=sr,
            limiar=limiar_interno,
            max_pausa_ms=max_pausa_interna_ms,
            alvo_ms=pausa_interna_alvo_ms,
        )
    return recortado


def para_segmento(
    wav,
    cortar_silencio: bool = True,
    volume_alvo_dbfs: float = -20.0,
) -> AudioSegment:
    """Converte array float para AudioSegment com corte de silêncio residual,
    normalização de volume por frase e fade suave nas bordas."""
    arr = np.asarray(wav, dtype=np.float32)
    if cortar_silencio:
        arr = cortar_silencio_pontas(arr)
    else:
        arr = arr - float(np.mean(arr)) if arr.size else arr

    pcm = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16)
    seg = AudioSegment(pcm.tobytes(), frame_rate=SAMPLE_RATE, sample_width=2, channels=1)

    if seg.dBFS != float("-inf"):
        ganho_desejado = volume_alvo_dbfs - seg.dBFS
        ganho_max_sem_clip = -1.0 - seg.max_dBFS
        ganho = max(-12.0, min(ganho_desejado, ganho_max_sem_clip, 12.0))
        seg = seg.apply_gain(ganho)

    return seg.fade_in(10).fade_out(25)


LIMIAR_ALUCINACAO_S_POR_CHAR = 0.35
DURACAO_MIN_ALUCINACAO_S = 3.5


def avaliar_anomalia_sintese(
    segmento: AudioSegment,
    texto_voz: str,
    velocidade: float = 1.0,
) -> str | None:
    """Detecta anomalias graves de síntese no XTTS v2 (silêncio total ou loop/alucinação)."""
    duracao_s = len(segmento) / 1000.0
    if duracao_s <= 0.01 or segmento.dBFS == float("-inf"):
        return "silencio_total"
    n_chars = max(1, len(texto_voz.strip()))
    fator_vel = max(0.5, float(velocidade))
    limite_s = max(DURACAO_MIN_ALUCINACAO_S, (n_chars * LIMIAR_ALUCINACAO_S_POR_CHAR) / fator_vel)
    if duracao_s > limite_s:
        return f"duracao_excessiva ({duracao_s:.1f}s para {n_chars} caracteres; limite {limite_s:.1f}s)"
    return None


class SinteseInterrompida(Exception):
    """Interrupção solicitada entre segmentos, com cache preservado."""


def main(argv=None, on_event=None, should_stop=None, modelo_precarregado=None):
    def emitir(tipo, **dados):
        if on_event is not None:
            on_event({"tipo": tipo, **dados})

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("texto", help="arquivo .txt com o texto pronto")
    ap.add_argument("--voz", default=None, help="áudio de referência (wav, 6-30 s) para clonar a voz")
    ap.add_argument(
        "--locutor", default=None,
        help="voz embutida do XTTS (padrão: automático pelo idioma: 'Luis Moray' para PT, 'Alma María' para ES)",
    )
    ap.add_argument("--saida", default="audio", help="nome base (sem extensão)")
    ap.add_argument(
        "--idioma", default="auto", choices=["auto", "pt", "es"],
        help="idioma (auto, pt ou es; padrão: auto com detecção no texto)",
    )
    ap.add_argument("--pausa-frase", type=int, default=600, help="ms após ponto/!/? (padrão: 600)")
    ap.add_argument("--pausa-reticencias", type=int, default=850, help="ms após reticências (padrão: 850)")
    ap.add_argument("--pausa-ponto-virgula", type=int, default=420, help="ms após ; ou : (padrão: 420)")
    ap.add_argument("--pausa-virgula", type=int, default=250, help="ms em corte de frase longa (padrão: 250)")
    ap.add_argument("--pausa-paragrafo", type=int, default=1150, help="ms entre parágrafos (padrão: 1150)")
    ap.add_argument("--pausa-bloco", type=int, default=500, help="ms extra entre blocos (padrão: 500)")
    ap.add_argument("--velocidade", type=float, default=1.1, help="velocidade da fala (1.0 = original; padrão: 1.1; faixa útil 0.8 a 1.3)")
    ap.add_argument("--volume-alvo", type=float, default=-20.0, help="volume alvo em dBFS (padrão: -20.0; deixa folga para [enfase])")
    ap.add_argument("--glossario", default=None, help="arquivo .json opcional com pronúncias extras")
    ap.add_argument("--sem-normalizar", action="store_true", help="desativa a normalização fonética")
    ap.add_argument("--sem-corte-silencio", action="store_true", help="não remove silêncio residual do XTTS")
    ap.add_argument("--refazer", action="store_true", help="regenera os segmentos, ignorando o cache existente")
    ap.add_argument(
        "--refazer-segmentos", default=None,
        help="regenera apenas os IDs de segmentos informados, preservando os demais do cache (ex.: '2' ou '1,4')",
    )
    ap.add_argument("--wav", action="store_true", help="gera também o arquivo .wav além do .mp3")
    ap.add_argument("--srt", action="store_true", help="gera também o arquivo de legendas .srt")
    ap.add_argument("--vtt", action="store_true", help="gera também o arquivo de legendas .vtt (WebVTT)")
    ap.add_argument("--formatos", default="mp3", help="formatos de saída (padrão: mp3; aceita mp3,wav,srt,vtt)")
    ap.add_argument(
        "--lufs", type=float, default=None,
        help="normaliza o loudness final integrado em LUFS via FFmpeg (ex.: -16 para podcasts, -14 para web)",
    )
    ap.add_argument(
        "--taxa-amostragem", type=int, default=SAMPLE_RATE, choices=[24000, 44100, 48000],
        help="taxa de amostragem de saída em Hz (padrão: 24000; opções: 24000, 44100, 48000)",
    )
    ap.add_argument(
        "--trilha", default=None,
        help="arquivo de áudio para trilha sonora de fundo (BGM) com auto-ducking automático na fala",
    )
    ap.add_argument(
        "--volume-trilha", type=float, default=-18.0,
        help="volume base da trilha de fundo em dB antes do auto-ducking (padrão: -18.0; faixa: -60 a 0)",
    )
    ap.add_argument(
        "--vozes-personagens", default=None,
        help="mapeia personagens do roteiro para arquivos WAV de referência (ex.: 'narrador=luis.wav,alma=alma.wav')",
    )
    ap.add_argument(
        "--vozes-tons", default=None,
        help="mapeia tons de expressão ([tom:X]) para arquivos WAV de referência (ex.: 'enfatico=enfase.wav,calmo=calmo.wav')",
    )
    ap.add_argument(
        "--limpar-referencia", action="store_true",
        help="higieniza áudios de referência (remove ruído e padroniza volume via FFmpeg antes da clonagem)",
    )
    ap.add_argument(
        "--max-tentativas", type=int, default=2,
        help="máximo de tentativas por segmento caso seja detectada alucinação/silêncio (padrão: 2)",
    )
    ap.add_argument(
        "--dispositivo", default="auto", choices=["auto", "cpu", "cuda", "mps"],
        help="auto = CUDA se houver, senão CPU (mps é experimental no Mac)",
    )
    ap.add_argument("--analisar", action="store_true", help="confere e mostra o plano sem carregar o XTTS ou gravar saídas")
    args = ap.parse_args(argv)

    for nome in ("pausa_frase", "pausa_reticencias", "pausa_ponto_virgula",
                 "pausa_virgula", "pausa_paragrafo", "pausa_bloco"):
        if getattr(args, nome) < 0:
            ap.error(f"--{nome.replace('_', '-')} deve ser maior ou igual a zero.")
    if not math.isfinite(args.velocidade) or args.velocidade <= 0:
        ap.error("--velocidade deve ser um número finito maior que zero.")
    if not math.isfinite(args.volume_alvo) or args.volume_alvo > 0:
        ap.error("--volume-alvo deve ser um número finito menor ou igual a zero dBFS.")
    if args.lufs is not None and (not math.isfinite(args.lufs) or not (-70.0 <= args.lufs <= -5.0)):
        ap.error("--lufs deve ser um número entre -70 e -5 LUFS (ex.: -16).")
    if not math.isfinite(args.volume_trilha) or not (-60.0 <= args.volume_trilha <= 0.0):
        ap.error("--volume-trilha deve estar entre -60 e 0 dB.")
    if args.max_tentativas < 1:
        ap.error("--max-tentativas deve ser maior ou igual a 1.")
    refazer_ids: set[int] = set()
    if args.refazer_segmentos is not None:
        partes_ids = [p.strip() for p in args.refazer_segmentos.split(",") if p.strip()]
        if not partes_ids or any(not p.isdigit() or int(p) < 1 for p in partes_ids):
            ap.error("--refazer-segmentos deve conter IDs inteiros positivos separados por vírgula (ex.: 2 ou 1,4).")
        refazer_ids = {int(p) for p in partes_ids}
    formatos = list(dict.fromkeys(f.strip().lower() for f in args.formatos.split(",")))
    if not formatos or any(f not in ("mp3", "wav", "srt", "vtt") for f in formatos):
        ap.error("--formatos aceita mp3, wav, srt, vtt ou combinações separadas por vírgula.")
    for flag, fmt in ((args.wav, "wav"), (args.srt, "srt"), (args.vtt, "vtt")):
        if flag and fmt not in formatos:
            formatos.append(fmt)
    if not args.saida.strip() or Path(args.saida).is_dir():
        ap.error("--saida deve indicar um nome base de arquivo.")
    if args.locutor is not None:
        args.locutor = args.locutor.strip()
        if not args.locutor:
            ap.error("--locutor não pode ser vazio.")
    if args.voz and not Path(args.voz).is_file():
        ap.error(f"Áudio de referência não encontrado: {args.voz}")
    if args.trilha and not Path(args.trilha).is_file():
        ap.error(f"Arquivo de trilha sonora não encontrado: {args.trilha}")
    normalizar = not args.sem_normalizar
    caminho_texto = Path(args.texto)
    try:
        texto = caminho_texto.read_text(encoding="utf-8-sig")
        glossario_extra = carregar_glossario(args.glossario, texto_path=args.texto)
        vozes_personagens = carregar_vozes_personagens(args.vozes_personagens, base_texto=caminho_texto)
        vozes_tons = carregar_vozes_personagens(args.vozes_tons, base_texto=caminho_texto)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    if not texto.strip():
        ap.error("O arquivo de texto está vazio.")

    # 1) Detecção de idioma e seleção de locutor
    modo_auto = args.idioma == "auto"
    idioma_global = detectar_idioma(texto) if modo_auto else args.idioma
    locutor_global = args.locutor or VOZES_PADRAO.get(idioma_global, "Luis Moray")
    nome_idioma = "Espanhol (es)" if idioma_global == "es" else "Português Brasileiro (pt)"
    origem_idioma = " [detecção automática]" if modo_auto else ""
    origem_locutor = " [seleção automática ideal]" if not args.locutor else ""
    print(f"Idioma dominante: {nome_idioma}{origem_idioma}")
    print(f"Locutor padrão: {locutor_global}{origem_locutor}")

    # 2) Análise prévia
    analise = analise_previa(texto)
    analise["idioma"] = idioma_global
    analise["locutor"] = locutor_global
    print(
        f"Análise prévia: {analise['palavras_estimadas']} palavras, "
        f"~{analise['duracao_estimada_min']} min -> "
        + ("LONGO (divide em blocos de até 150 palavras)" if analise["precisa_dividir"] else "curto (bloco único)")
    )

    # 3) Divisão em blocos (com detecção por parágrafo quando idioma='auto')
    try:
        blocos = dividir_em_blocos(
            montar_itens(texto, normalizar=normalizar, idioma_padrao=idioma_global,
                         detectar_por_paragrafo=modo_auto),
            analise["precisa_dividir"],
        )
        plano = [
            [(preparar_segmentos(t, lang, normalizar, glossario_extra), fim, lang, locutor)
             for t, fim, lang, locutor in bloco]
            for bloco in blocos
        ]
        for bloco in plano:
            for segmentos_tags, _, _, locutor in bloco:
                resolver_voz_segmento(locutor, vozes_personagens, base_texto=caminho_texto)
                for _, mods in segmentos_tags:
                    resolver_voz_tom(mods, vozes_tons, base_texto=caminho_texto)
    except ValueError as exc:
        ap.error(str(exc))
    if not any(limpar_para_voz(t) for bloco in plano for segmentos, _, _, _ in bloco
               for t, _ in segmentos):
        ap.error("O arquivo não contém texto para sintetizar.")

    manifesto = {
        "analise_previa": analise,
        "blocos": [
            {
                "id": i,
                "palavras": sum(contar_palavras(t) for t, _, _, _ in b),
                "texto": " ".join(t for t, _, _, _ in b),
                "texto_falado": " ".join(
                    limpar_para_voz(sub)
                    for segmentos, _, _, _ in plano[i - 1]
                    for sub, _ in segmentos
                    if limpar_para_voz(sub)
                ),
            }
            for i, b in enumerate(blocos, 1)
        ],
    }
    resumo_segmentos = [
        {"id": n, "bloco": bloco, "texto": limpar_para_voz(sub), "idioma": lang,
         "locutor": locutor or args.locutor or VOZES_PADRAO[lang]}
        for n, (bloco, sub, lang, locutor) in enumerate(
            ((i, sub, lang, locutor)
             for i, b in enumerate(plano, 1)
             for segmentos, _, lang, locutor in b
             for sub, _ in segmentos if limpar_para_voz(sub)), 1)
    ]
    if refazer_ids and any(idx > len(resumo_segmentos) for idx in refazer_ids):
        ap.error(f"--refazer-segmentos contém ID fora do total de segmentos ({len(resumo_segmentos)}).")
    emitir("plano", total=len(resumo_segmentos), segmentos=resumo_segmentos)
    if args.analisar:
        for seg in resumo_segmentos:
            print(f"  #{seg['id']} [{seg['idioma']}|{seg['locutor']}] {seg['texto']}")
        return

    base = Path(args.saida)
    json_path = base.parent / f"{base.name}.blocos.json"
    try:
        base.parent.mkdir(parents=True, exist_ok=True)
        salvar_json(json_path, manifesto)
    except OSError as exc:
        ap.error(f"Não foi possível gravar o manifesto: {exc}")
    print(f"{len(blocos)} bloco(s). Lista salva em {json_path}")

    # O modelo só é carregado quando algum segmento precisa de síntese.
    configurar_ffmpeg()
    cache = CacheSegmentos(base.parent / f"{base.name}.segmentos")
    eventos = [200]
    cursor_frames = SAMPLE_RATE // 5
    manifesto["segmentos"] = []
    manifesto["estado"] = "sintetizando"
    salvar_json(json_path, manifesto)
    modelo = modelo_precarregado
    versoes = {}
    for pacote in ("coqui-tts", "torch", "numpy", "pydub"):
        try:
            versoes[pacote] = version(pacote)
        except PackageNotFoundError:
            versoes[pacote] = "indisponível"
    hashes_ref: dict[str, str] = {}
    refs_limpas: dict[str, str] = {}

    def obter_hash_ref(caminho_ref: str | None) -> str | None:
        if not caminho_ref:
            return None
        chave = str(Path(caminho_ref).resolve())
        if chave not in hashes_ref:
            hashes_ref[chave] = hash_arquivo(chave)
        return hashes_ref[chave]

    def obter_voz_condicionada(caminho_ref: str | None) -> str | None:
        if not caminho_ref:
            return None
        if not args.limpar_referencia:
            return caminho_ref
        chave = str(Path(caminho_ref).resolve())
        if chave not in refs_limpas:
            refs_limpas[chave] = higienizar_referencia(chave, cache.pasta, AudioSegment.converter)
        return refs_limpas[chave]

    referencia = obter_hash_ref(args.voz)
    manifesto["configuracao"] = {
        "python": sys.version.split()[0], "versoes": versoes,
        "dispositivo_solicitado": args.dispositivo, "velocidade": args.velocidade,
        "volume_alvo": args.volume_alvo, "cortar_silencio": not args.sem_corte_silencio,
        "lufs": args.lufs, "taxa_amostragem": args.taxa_amostragem,
        "limpar_referencia": args.limpar_referencia, "max_tentativas": args.max_tentativas,
        "referencia_sha256": referencia,
        "fontes_sha256": {nome: hash_arquivo(Path(__file__).parent / nome)
                          for nome in ("tts.py", "normalizador.py", "audio_persistente.py")},
    }
    salvar_json(json_path, manifesto)

    def verificar_interrupcao():
        if should_stop is not None and should_stop():
            manifesto["estado"] = "interrompido"
            salvar_json(json_path, manifesto)
            emitir("interrompido", concluidos=len(manifesto["segmentos"]),
                   total=len(resumo_segmentos))
            raise SinteseInterrompida("Interrompido entre segmentos; repita a geração para retomar.")

    def sintetizar(texto_voz, locutor, lang, volume, voz_ref=None, velocidade=None):
        nonlocal modelo
        if modelo is None:
            emitir("etapa", etapa="modelo", mensagem="Carregando o modelo de voz…")
            from TTS.api import TTS
            dispositivo = escolher_dispositivo(args.dispositivo)
            print(f"Dispositivo: {dispositivo}")
            modelo = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(dispositivo)
        voz_preparada = obter_voz_condicionada(voz_ref)
        voz = {"speaker_wav": voz_preparada} if voz_preparada else {"speaker": locutor}
        vel = args.velocidade if velocidade is None else velocidade
        melhor_seg = None
        for tentativa in range(1, args.max_tentativas + 1):
            wav = modelo.tts(text=texto_voz, **voz, language=lang,
                             split_sentences=False, speed=vel)
            seg = para_segmento(wav, cortar_silencio=not args.sem_corte_silencio,
                                volume_alvo_dbfs=volume)
            anomalia = avaliar_anomalia_sintese(seg, texto_voz, vel)
            if anomalia is None:
                return seg
            if melhor_seg is None or (seg.dBFS != float("-inf") and len(seg) < len(melhor_seg)):
                melhor_seg = seg
            if tentativa < args.max_tentativas:
                print(f"    Aviso: anomalia na síntese ({anomalia}); repetindo ({tentativa + 1}/{args.max_tentativas})…")
            else:
                print(f"    Aviso: anomalia persistiu após {args.max_tentativas} tentativa(s) ({anomalia}).")
        return melhor_seg

    for i, bloco in enumerate(plano, 1):
        print(f"--- Bloco {i}/{len(plano)} ---")
        for segmentos_tags, fim_par, lang_trecho, locutor_char in bloco:
            locutor_trecho = locutor_char or args.locutor or VOZES_PADRAO.get(lang_trecho, locutor_global)
            voz_personagem = resolver_voz_segmento(locutor_char, vozes_personagens, base_texto=caminho_texto)
            for idx_seg, (sub_trecho, mods) in enumerate(segmentos_tags):
                ultimo_sub = idx_seg == len(segmentos_tags) - 1
                texto_voz = limpar_para_voz(sub_trecho)
                if sub_trecho:
                    # Texto sem pontuação final seguido de tag de pausa: a tag já define a pausa.
                    seguido_de_pausa = (
                        idx_seg + 1 < len(segmentos_tags)
                        and "pausa_extra_ms" in segmentos_tags[idx_seg + 1][1]
                        and not ultimo_sub
                    )
                    sem_pontuacao = not sub_trecho.rstrip().endswith((".", "!", "?", "…", ";", ":", ","))
                    if seguido_de_pausa and sem_pontuacao:
                        pausa_base = 0
                    else:
                        pausa_base = pausa_ms(sub_trecho, fim_par and ultimo_sub, args)
                else:
                    # Item de tag pura: só carrega a pausa pedida (+ pausa de parágrafo se for o último).
                    pausa_base = args.pausa_paragrafo if (fim_par and ultimo_sub) else 0
                pausa_total = pausa_base + mods.get("pausa_extra_ms", 0)

                if texto_voz:
                    voz_tom = resolver_voz_tom(mods, vozes_tons, base_texto=caminho_texto)
                    voz_efetiva = voz_tom or voz_personagem or args.voz
                    ref_efetiva = obter_hash_ref(voz_efetiva)
                    vel_efetiva = (
                        round(args.velocidade * mods["velocidade_fator"], 4)
                        if "velocidade_fator" in mods
                        else args.velocidade
                    )
                    tag_info = ""
                    if "tom" in mods:
                        tag_info += f"|tom:{mods['tom']}"
                    if "volume_offset_db" in mods:
                        tag_info += f"|vol:{mods['volume_offset_db']:+.1f}dB"
                    if "pausa_extra_ms" in mods:
                        tag_info += f"|pausa:{mods['pausa_extra_ms']}ms"

                    print(f"  [{lang_trecho}|{locutor_trecho}{tag_info}] {texto_voz[:55]}")
                    vol_alvo = args.volume_alvo + mods.get("volume_offset_db", 0.0)
                    parametros = {
                        "pipeline": 1, "modelo": "tts_models/multilingual/multi-dataset/xtts_v2",
                        "versoes": versoes, "texto": texto_voz, "idioma": lang_trecho,
                        "locutor": None if voz_efetiva else locutor_trecho,
                        "referencia_sha256": ref_efetiva, "velocidade": vel_efetiva,
                        "volume_alvo": vol_alvo, "cortar_silencio": not args.sem_corte_silencio,
                        "dispositivo_solicitado": args.dispositivo,
                    }
                    if args.limpar_referencia and voz_efetiva:
                        parametros["limpar_referencia"] = True
                    verificar_interrupcao()
                    seg_id = len(manifesto["segmentos"]) + 1
                    emitir("etapa", etapa="sintese", mensagem=f"Processando segmento {seg_id}…")
                    caminho, frames, reutilizado = cache.obter(
                        parametros,
                        lambda v=voz_efetiva, vel=vel_efetiva: sintetizar(
                            texto_voz, locutor_trecho, lang_trecho, vol_alvo, v, vel
                        ),
                        refazer=args.refazer or (seg_id in refazer_ids),
                    )
                    eventos.append(caminho)
                    manifesto["segmentos"].append({
                        "id": seg_id, "bloco": i,
                        "texto": texto_voz, "idioma": lang_trecho, "locutor": parametros["locutor"],
                        "arquivo": str(caminho.resolve()), "chave": caminho.stem,
                        "inicio_s": cursor_frames / SAMPLE_RATE,
                        "fim_s": (cursor_frames + frames) / SAMPLE_RATE,
                        "duracao_s": frames / SAMPLE_RATE, "reutilizado": reutilizado,
                    })
                    emitir("segmento", segmento=manifesto["segmentos"][-1],
                           concluidos=len(manifesto["segmentos"]), total=len(resumo_segmentos))
                    cursor_frames += frames
                    salvar_json(json_path, manifesto)
                    if reutilizado:
                        print("    Segmento recuperado do cache.")

                if pausa_total > 0:
                    eventos.append(pausa_total)
                    cursor_frames += SAMPLE_RATE * pausa_total // 1000
        if i < len(blocos):
            eventos.append(args.pausa_bloco)
            cursor_frames += SAMPLE_RATE * args.pausa_bloco // 1000

    verificar_interrupcao()
    emitir("etapa", etapa="montagem", mensagem="Montando e exportando o áudio…")
    manifesto["estado"] = "montando"
    salvar_json(json_path, manifesto)
    exportar(eventos, base, formatos, AudioSegment.converter,
             segmentos=manifesto["segmentos"], lufs=args.lufs, taxa_amostragem=args.taxa_amostragem,
             trilha=args.trilha, volume_trilha=args.volume_trilha)
    manifesto["estado"] = "concluido"
    salvar_json(json_path, manifesto)
    emitir("resultado", manifesto=str(json_path.resolve()),
           arquivos=[str((base.parent / f"{base.name}.{fmt}").resolve()) for fmt in formatos])


if __name__ == "__main__":
    main()
