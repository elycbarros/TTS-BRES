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
import warnings
from importlib.metadata import version, PackageNotFoundError

from audio_persistente import CacheSegmentos, exportar, hash_arquivo, salvar_json
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


def extrair_tags_expressividade(texto: str) -> list[tuple[str, dict]]:
    """Extrai tags de direção de voz: [pausa:Xms], [pausa:Xs], [respiro], [enfase], [sussurro].

    Retorna uma lista ordenada de (texto, modificadores):
      - pausa/respiro viram um item próprio ("", {"pausa_extra_ms": N}) NA POSIÇÃO da tag;
      - enfase/sussurro viram {"volume_offset_db": X} aplicado ao próximo trecho de texto.
    """
    if re.search(r"\[[^\]]*$|^[^\[]*\]", texto):
        raise ValueError("Tag com colchetes incompletos.")
    partes = re.split(r"(\[[^\[\]]*\])", texto)
    itens: list[tuple[str, dict]] = []
    volume_pendente: float | None = None

    for p in partes:
        p_strip = p.strip()
        if not p_strip:
            continue
        m_tag = re.fullmatch(r"\[([a-zA-Zçãéíóú0-9_.-]+)(?::([^\]]*))?\]", p_strip)
        if not m_tag:
            if "[" in p_strip or "]" in p_strip:
                raise ValueError(f"Tag inválida: {p_strip}")
            mods = {"volume_offset_db": volume_pendente} if volume_pendente is not None else {}
            itens.append((p_strip, mods))
            volume_pendente = None
            continue

        tag_nome = m_tag.group(1).lower()
        tag_param = (m_tag.group(2) or "").strip().lower()

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

        m_char = re.match(r"^\[([a-zA-ZçãéíóúÁÉÍÓÚ0-9_|\s-]+)\]\s*:\s*(.*)$", par)
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
    """Texto enviado ao XTTS: sem pontuação final (evita leitura literal da palavra 'ponto'
    ou 'punto') e sem ; e :. É aplicado depois de pausa_ms, que usa a pontuação original."""
    t = re.sub(r"\s*[;:]\s*", ", ", trecho)
    t = re.sub(r"[\s.,;:…]+$", "", t)
    t = re.sub(r"\.{2,}", ",", t)
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


def cortar_silencio_pontas(
    wav: np.ndarray,
    sr: int = SAMPLE_RATE,
    limiar_db: float = -42.0,
    margem_ini_ms: int = 30,
    margem_fim_ms: int = 90,
) -> np.ndarray:
    """Remove o excesso de silêncio residual do XTTS v2 nas pontas,
    preservando margens naturais (30 ms início, 90 ms fim)."""
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
    return arr[ini_amostra:fim_amostra]


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


def main():
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
    ap.add_argument("--wav", action="store_true", help="gera também o arquivo .wav além do .mp3")
    ap.add_argument("--formatos", default="mp3", help="formatos de saída (padrão: mp3; ex.: mp3,wav)")
    ap.add_argument(
        "--dispositivo", default="auto", choices=["auto", "cpu", "cuda", "mps"],
        help="auto = CUDA se houver, senão CPU (mps é experimental no Mac)",
    )
    args = ap.parse_args()

    for nome in ("pausa_frase", "pausa_reticencias", "pausa_ponto_virgula",
                 "pausa_virgula", "pausa_paragrafo", "pausa_bloco"):
        if getattr(args, nome) < 0:
            ap.error(f"--{nome.replace('_', '-')} deve ser maior ou igual a zero.")
    if not math.isfinite(args.velocidade) or args.velocidade <= 0:
        ap.error("--velocidade deve ser um número finito maior que zero.")
    if not math.isfinite(args.volume_alvo) or args.volume_alvo > 0:
        ap.error("--volume-alvo deve ser um número finito menor ou igual a zero dBFS.")
    formatos = list(dict.fromkeys(f.strip().lower() for f in args.formatos.split(",")))
    if not formatos or any(f not in ("mp3", "wav") for f in formatos):
        ap.error("--formatos aceita mp3, wav ou mp3,wav.")
    if args.wav and "wav" not in formatos:
        formatos.append("wav")
    if not args.saida.strip() or Path(args.saida).is_dir():
        ap.error("--saida deve indicar um nome base de arquivo.")
    if args.locutor is not None:
        args.locutor = args.locutor.strip()
        if not args.locutor:
            ap.error("--locutor não pode ser vazio.")
    if args.voz and not Path(args.voz).is_file():
        ap.error(f"Áudio de referência não encontrado: {args.voz}")
    normalizar = not args.sem_normalizar
    try:
        texto = Path(args.texto).read_text(encoding="utf-8-sig")
        glossario_extra = carregar_glossario(args.glossario, texto_path=args.texto)
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
    modelo = None
    versoes = {}
    for pacote in ("coqui-tts", "torch", "numpy", "pydub"):
        try:
            versoes[pacote] = version(pacote)
        except PackageNotFoundError:
            versoes[pacote] = "indisponível"
    referencia = hash_arquivo(args.voz) if args.voz else None
    manifesto["configuracao"] = {
        "python": sys.version.split()[0], "versoes": versoes,
        "dispositivo_solicitado": args.dispositivo, "velocidade": args.velocidade,
        "volume_alvo": args.volume_alvo, "cortar_silencio": not args.sem_corte_silencio,
        "referencia_sha256": referencia,
        "fontes_sha256": {nome: hash_arquivo(Path(__file__).parent / nome)
                          for nome in ("tts.py", "normalizador.py", "audio_persistente.py")},
    }
    salvar_json(json_path, manifesto)

    def sintetizar(texto_voz, locutor, lang, volume):
        nonlocal modelo
        if modelo is None:
            from TTS.api import TTS
            dispositivo = escolher_dispositivo(args.dispositivo)
            print(f"Dispositivo: {dispositivo}")
            modelo = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(dispositivo)
        voz = {"speaker_wav": args.voz} if args.voz else {"speaker": locutor}
        wav = modelo.tts(text=texto_voz, **voz, language=lang,
                         split_sentences=False, speed=args.velocidade)
        return para_segmento(wav, cortar_silencio=not args.sem_corte_silencio,
                             volume_alvo_dbfs=volume)

    for i, bloco in enumerate(plano, 1):
        print(f"--- Bloco {i}/{len(plano)} ---")
        for segmentos_tags, fim_par, lang_trecho, locutor_char in bloco:
            locutor_trecho = locutor_char or args.locutor or VOZES_PADRAO.get(lang_trecho, locutor_global)
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
                    tag_info = ""
                    if "volume_offset_db" in mods:
                        tag_info += f"|vol:{mods['volume_offset_db']:+.1f}dB"
                    if "pausa_extra_ms" in mods:
                        tag_info += f"|pausa:{mods['pausa_extra_ms']}ms"

                    print(f"  [{lang_trecho}|{locutor_trecho}{tag_info}] {texto_voz[:55]}")
                    vol_alvo = args.volume_alvo + mods.get("volume_offset_db", 0.0)
                    parametros = {
                        "pipeline": 1, "modelo": "tts_models/multilingual/multi-dataset/xtts_v2",
                        "versoes": versoes, "texto": texto_voz, "idioma": lang_trecho,
                        "locutor": None if args.voz else locutor_trecho,
                        "referencia_sha256": referencia, "velocidade": args.velocidade,
                        "volume_alvo": vol_alvo, "cortar_silencio": not args.sem_corte_silencio,
                        "dispositivo_solicitado": args.dispositivo,
                    }
                    caminho, frames, reutilizado = cache.obter(
                        parametros,
                        lambda: sintetizar(texto_voz, locutor_trecho, lang_trecho, vol_alvo),
                        refazer=args.refazer,
                    )
                    eventos.append(caminho)
                    manifesto["segmentos"].append({
                        "id": len(manifesto["segmentos"]) + 1, "bloco": i,
                        "texto": texto_voz, "idioma": lang_trecho, "locutor": parametros["locutor"],
                        "arquivo": str(caminho.resolve()), "chave": caminho.stem,
                        "inicio_s": cursor_frames / SAMPLE_RATE,
                        "fim_s": (cursor_frames + frames) / SAMPLE_RATE,
                        "duracao_s": frames / SAMPLE_RATE, "reutilizado": reutilizado,
                    })
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

    manifesto["estado"] = "montando"
    salvar_json(json_path, manifesto)
    exportar(eventos, base, formatos, AudioSegment.converter)
    manifesto["estado"] = "concluido"
    salvar_json(json_path, manifesto)


if __name__ == "__main__":
    main()
