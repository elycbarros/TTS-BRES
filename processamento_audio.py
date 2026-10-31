#!/usr/bin/env python3
"""Processamento de áudio, corte de silêncios residuais, normalização e detecção de anomalias."""
import shutil
import warnings

import numpy as np

with warnings.catch_warnings():
    warnings.simplefilter("ignore", RuntimeWarning)
    from pydub import AudioSegment

SAMPLE_RATE = 24000
LIMIAR_ALUCINACAO_S_POR_CHAR = 0.35
DURACAO_MIN_ALUCINACAO_S = 3.5


def configurar_ffmpeg() -> None:
    """Usa o ffmpeg do sistema; se não houver, usa o embutido do imageio-ffmpeg."""
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg

        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        print("Aviso: ffmpeg não encontrado; a exportação MP3 pode falhar.")


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
