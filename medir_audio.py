#!/usr/bin/env python3
"""Mede pausas (silêncios) e volume (dBFS) por trecho de fala de um áudio gerado.

Uso:
    python medir_audio.py saida/teste_expressividade.wav
    python medir_audio.py saida/x.wav --min-pausa-ms 250 --limiar-db -45

Imprime a linha do tempo: cada trecho de fala (início, duração, dBFS RMS)
e cada pausa entre trechos (duração em ms). Serve para conferir objetivamente
o efeito das tags [pausa:...], [enfase] e [sussurro].
"""
import argparse

import numpy as np
import soundfile as sf


def segmentar(arr: np.ndarray, sr: int, limiar_db: float, min_pausa_ms: int):
    """Retorna lista de (tipo, inicio_s, fim_s) alternando 'fala' e 'pausa'."""
    janela = max(1, sr // 100)  # 10 ms
    n = len(arr) // janela
    rms = np.sqrt(np.mean(arr[: n * janela].reshape(n, janela) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    ativo = db > limiar_db

    min_j = max(1, min_pausa_ms // 10)
    # Fecha buracos de silêncio curtos (< min_pausa) dentro da fala
    i = 0
    while i < n:
        if not ativo[i]:
            j = i
            while j < n and not ativo[j]:
                j += 1
            if (j - i) < min_j and i > 0 and j < n:
                ativo[i:j] = True
            i = j
        else:
            i += 1

    trechos, i = [], 0
    while i < n:
        j = i
        while j < n and ativo[j] == ativo[i]:
            j += 1
        trechos.append(("fala" if ativo[i] else "pausa", i * janela / sr, j * janela / sr))
        i = j
    return trechos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("audio")
    ap.add_argument("--limiar-db", type=float, default=-45.0)
    ap.add_argument("--min-pausa-ms", type=int, default=200)
    args = ap.parse_args()

    arr, sr = sf.read(args.audio, dtype="float32")
    if arr.ndim > 1:
        arr = arr.mean(axis=1)

    print(f"Duração total: {len(arr) / sr:.2f}s | sr={sr}\n")
    k = 0
    for tipo, a, b in segmentar(arr, sr, args.limiar_db, args.min_pausa_ms):
        if tipo == "fala":
            k += 1
            seg = arr[int(a * sr): int(b * sr)]
            nivel = 20 * np.log10(max(float(np.sqrt(np.mean(seg ** 2))), 1e-9))
            print(f"FALA  #{k:<2} {a:6.2f}s  dur={b - a:5.2f}s  rms={nivel:6.1f} dBFS")
        else:
            print(f"PAUSA     {a:6.2f}s  dur={int((b - a) * 1000):5d} ms")


if __name__ == "__main__":
    main()

