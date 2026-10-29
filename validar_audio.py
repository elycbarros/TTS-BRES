#!/usr/bin/env python3
"""Valida objetivamente o áudio gerado: transcreve com Whisper e compara com o texto original.

Uso:
    python validar_audio.py saida/teste1.mp3 teste1.txt            # idioma detectado
    python validar_audio.py saida/teste_es.mp3 teste_es.txt --idioma es
    python validar_audio.py saida/teste1.mp3 teste1.txt --modelo openai/whisper-small

Mostra a taxa de erro de palavras (WER) e as divergências (palavras trocadas,
omitidas ou inseridas, ex.: "ponto"), apontando onde a pronúncia falhou.
"""
import argparse
import difflib
import re
import sys
import unicodedata
from pathlib import Path

from normalizador import detectar_idioma, normalizar_numeros_e_simbolos_pt

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def tokenizar(texto: str, idioma: str) -> list[str]:
    """Minúsculas, números por extenso (pt), sem tags [tag], sem rótulos [Personagem]:, sem pontuação nem acentos."""
    t = texto.lower()
    # Remove rótulos de personagem/diálogo no início da linha, ex: [Narrador]: ou [Alma]:
    t = re.sub(r"\[[a-za-zçãéíóú0-9_|\s-]+\]\s*:", " ", t)
    # Remove tags de expressividade como [pausa:1s], [enfase], [respiro] para comparar apenas a fala real
    t = re.sub(r"\[[a-za-zçãéíóú0-9_.:\s-]+\]", " ", t)
    if idioma == "pt":
        t = normalizar_numeros_e_simbolos_pt(t)
    elif idioma == "es":
        t = normalizar_numeros_e_simbolos_es(t)
    t = _sem_acento(t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return t.split()


def alinhar(ref: list[str], hip: list[str]):
    """Retorna (erros, lista de divergências) usando alinhamento por difflib."""
    sm = difflib.SequenceMatcher(a=ref, b=hip, autojunk=False)
    erros, diffs = 0, []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        r, h = ref[i1:i2], hip[j1:j2]
        erros += max(len(r), len(h))
        diffs.append((op, " ".join(r), " ".join(h), " ".join(ref[max(0, i1 - 3):i1])))
    return erros, diffs


def transcrever(audio: str, idioma: str, modelo: str) -> str:
    import librosa
    import torch
    from transformers import pipeline

    dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
    asr = pipeline(
        "automatic-speech-recognition",
        model=modelo,
        device=dispositivo,
        chunk_length_s=30,
    )
    sinal, _ = librosa.load(audio, sr=16000, mono=True)
    saida = asr(
        {"raw": sinal, "sampling_rate": 16000},
        generate_kwargs={"language": idioma, "task": "transcribe"},
    )
    return saida["text"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("audio", help="arquivo de áudio gerado (mp3/wav)")
    ap.add_argument("texto", help="texto original (.txt)")
    ap.add_argument("--idioma", default="auto", choices=["auto", "pt", "es"])
    ap.add_argument("--modelo", default="openai/whisper-small", help="modelo Whisper (HuggingFace)")
    ap.add_argument("--limite-wer", type=float, default=0.10, help="WER máximo aceitável (padrão: 0.10)")
    args = ap.parse_args()

    original = Path(args.texto).read_text(encoding="utf-8-sig")
    idioma = detectar_idioma(original) if args.idioma == "auto" else args.idioma

    transcricao = transcrever(args.audio, idioma, args.modelo)
    ref, hip = tokenizar(original, idioma), tokenizar(transcricao, idioma)
    erros, diffs = alinhar(ref, hip)
    wer = erros / max(1, len(ref))

    print(f"Idioma: {idioma} | Modelo: {args.modelo}")
    print(f"Palavras ref: {len(ref)} | transcritas: {len(hip)} | WER: {wer:.1%}")
    print("\nDivergências (esperado -> ouvido pelo Whisper):")
    for op, r, h, ctx in diffs:
        rotulo = {"replace": "TROCA", "delete": "OMITIDA", "insert": "INSERIDA"}[op]
        print(f"  [{rotulo}] ...{ctx} | '{r}' -> '{h}'")
    ponto = [h for op, r, h, _ in diffs if op in ("insert", "replace") and re.search(r"\bpunto?\b", h)]
    if ponto:
        print(f"\nAVISO: palavra 'ponto/punto' falada {len(ponto)}x (pontuação final lida em voz alta).")

    print("\nTranscrição completa:\n" + transcricao.strip())
    status = "OK" if wer <= args.limite_wer else "REPROVADO"
    print(f"\nResultado: {status} (limite {args.limite_wer:.0%})")
    sys.exit(0 if wer <= args.limite_wer else 1)


if __name__ == "__main__":
    main()
