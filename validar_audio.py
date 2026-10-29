#!/usr/bin/env python3
"""Valida objetivamente o áudio gerado: transcreve com Whisper e compara com o texto original.

Uso:
    python validar_audio.py saida/narracao_pt.mp3 exemplos/narracao_pt.txt            # idioma detectado
    python validar_audio.py saida/narracao_es.mp3 exemplos/narracao_es.txt --idioma es
    python validar_audio.py saida/narracao_pt.mp3 exemplos/narracao_pt.txt --modelo openai/whisper-small

Mostra a taxa de erro de palavras (WER) e as divergências (palavras trocadas,
omitidas ou inseridas, ex.: "ponto"), apontando onde a pronúncia falhou.
"""
import argparse
import json
import math
import wave
from functools import lru_cache

from audio_persistente import salvar_json
from qualidade_audio import medir_segmento
import re
import sys
import unicodedata
from pathlib import Path

from normalizador import (
    detectar_idioma, normalizar_numeros_e_simbolos_pt,
    normalizar_numeros_e_simbolos_es,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def tokenizar(texto: str, idioma: str) -> list[str]:
    """Minúsculas, números por extenso PT/ES, sem tags [tag], sem rótulos [Personagem]:, sem pontuação nem acentos."""
    t = texto
    # Remove rótulos de personagem/diálogo no início da linha, ex: [Narrador]: ou [Alma]:
    t = re.sub(r"\[[a-zçãéíóú0-9_|\s-]+\]\s*:", " ", t, flags=re.IGNORECASE)
    # Remove tags de expressividade como [pausa:1s], [enfase], [respiro] para comparar apenas a fala real
    t = re.sub(r"\[[a-zçãéíóú0-9_.:\s-]+\]", " ", t, flags=re.IGNORECASE)
    if idioma == "pt":
        t = normalizar_numeros_e_simbolos_pt(t)
    elif idioma == "es":
        t = normalizar_numeros_e_simbolos_es(t)
    t = _sem_acento(t.lower())
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return t.split()


def alinhar(ref: list[str], hip: list[str]):
    """WER por distância mínima de edição, com rastreio das divergências."""
    anterior = list(range(len(hip) + 1))
    caminhos = [bytearray([2] * (len(hip) + 1))]
    for i, palavra in enumerate(ref, 1):
        atual = [i]
        ops = bytearray(len(hip) + 1)
        ops[0] = 1
        for j, ouvida in enumerate(hip, 1):
            custos = (anterior[j - 1] + (palavra != ouvida),
                      anterior[j] + 1, atual[j - 1] + 1)
            op = min(range(3), key=custos.__getitem__)
            atual.append(custos[op])
            ops[j] = op
        caminhos.append(ops)
        anterior = atual
    erros = anterior[-1]
    diffs = []
    i, j = len(ref), len(hip)
    while i or j:
        op = caminhos[i][j]
        if i and j and op == 0:
            if ref[i - 1] != hip[j - 1]:
                diffs.append(("replace", ref[i - 1], hip[j - 1],
                              " ".join(ref[max(0, i - 4):i - 1])))
            i, j = i - 1, j - 1
        elif i and (not j or op == 1):
            diffs.append(("delete", ref[i - 1], "", " ".join(ref[max(0, i - 4):i - 1])))
            i -= 1
        else:
            diffs.append(("insert", "", hip[j - 1], " ".join(ref[max(0, i - 3):i])))
            j -= 1
    return erros, list(reversed(diffs))


@lru_cache(maxsize=1)
def carregar_transcritor(modelo: str):
    import torch
    from transformers import pipeline
    return pipeline("automatic-speech-recognition", model=modelo,
                    device="cuda" if torch.cuda.is_available() else "cpu", chunk_length_s=30)


def transcrever(audio: str, idioma: str, modelo: str) -> str:
    import librosa
    asr = carregar_transcritor(modelo)
    sinal, _ = librosa.load(audio, sr=16000, mono=True)
    saida = asr({"raw": sinal, "sampling_rate": 16000},
                generate_kwargs={"language": idioma, "task": "transcribe"})
    return saida["text"]


def validar_manifesto(caminho, modelo="openai/whisper-small", limite=0.10, somente_metricas=False):
    caminho = Path(caminho).resolve()
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if dados.get("estado") != "concluido" or not dados.get("segmentos"):
        raise ValueError("O manifesto deve conter uma síntese concluída com segmentos.")
    arquivos = []
    for seg in dados["segmentos"]:
        if seg.get("idioma") not in ("pt", "es") or not isinstance(seg.get("texto"), str):
            raise ValueError("Segmento sem texto ou idioma PT/ES válido.")
        arquivo = Path(seg["arquivo"])
        if not arquivo.is_absolute():
            arquivo = caminho.parent / arquivo
        if not arquivo.is_file():
            raise ValueError(f"Segmento não encontrado: {arquivo}")
        arquivos.append(arquivo)
    resultados, totais = [], {}
    for seg, arquivo in zip(dados["segmentos"], arquivos):
        item = {"id": seg["id"], "idioma": seg["idioma"], "texto": seg["texto"],
                "arquivo": str(arquivo), "inicio_s": seg.get("inicio_s"),
                "fim_s": seg.get("fim_s"), "metricas": medir_segmento(arquivo)}
        if not somente_metricas:
            ouvido = transcrever(str(arquivo), seg["idioma"], modelo)
            ref, hip = tokenizar(seg["texto"], seg["idioma"]), tokenizar(ouvido, seg["idioma"])
            erros, diffs = alinhar(ref, hip)
            wer = erros / max(1, len(ref))
            item.update(transcricao=ouvido, palavras_referencia=len(ref), erros=erros,
                        wer=wer, aprovado=wer <= limite, divergencias=diffs)
            grupo = totais.setdefault(seg["idioma"], {"palavras": 0, "erros": 0})
            grupo["palavras"] += len(ref)
            grupo["erros"] += erros
        resultados.append(item)
    for grupo in totais.values():
        grupo["wer"] = grupo["erros"] / max(1, grupo["palavras"])
    palavras = sum(g["palavras"] for g in totais.values())
    erros = sum(g["erros"] for g in totais.values())
    return {"manifesto": str(caminho), "modelo_asr": None if somente_metricas else modelo,
            "limite_wer": limite, "somente_metricas": somente_metricas,
            "wer_global": erros / max(1, palavras) if not somente_metricas else None,
            "por_idioma": totais, "segmentos": resultados,
            "aprovado": all(s["aprovado"] for s in resultados) if not somente_metricas else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("audio", nargs="?", help="arquivo de áudio gerado (mp3/wav)")
    ap.add_argument("texto", nargs="?", help="texto original (.txt)")
    ap.add_argument("--idioma", default="auto", choices=["auto", "pt", "es"])
    ap.add_argument("--modelo", default="openai/whisper-small", help="modelo Whisper (HuggingFace)")
    ap.add_argument("--limite-wer", type=float, default=0.10, help="WER máximo aceitável (padrão: 0.10)")
    ap.add_argument("--manifesto", help="valida os WAVs de um .blocos.json, no idioma de cada trecho")
    ap.add_argument("--relatorio", help="caminho do relatório JSON")
    ap.add_argument("--somente-metricas", action="store_true", help="mede os segmentos sem carregar Whisper")
    args = ap.parse_args()
    if not math.isfinite(args.limite_wer) or args.limite_wer < 0:
        ap.error("--limite-wer deve ser finito e não negativo.")
    if args.manifesto:
        if args.audio or args.texto or args.idioma != "auto":
            ap.error("Use --manifesto sem áudio/texto posicionais ou --idioma; cada trecho tem seu idioma.")
        try:
            relatorio = validar_manifesto(args.manifesto, args.modelo, args.limite_wer, args.somente_metricas)
            origem = Path(args.manifesto)
            destino = Path(args.relatorio) if args.relatorio else origem.with_name(origem.stem + ".validacao.json")
            destino.parent.mkdir(parents=True, exist_ok=True)
            salvar_json(destino, relatorio)
        except (OSError, ValueError, KeyError, TypeError, wave.Error, EOFError) as exc:
            ap.error(str(exc))
        for item in relatorio["segmentos"]:
            medida = "métricas acústicas" if args.somente_metricas else f"WER {item['wer']:.1%}"
            tempo = f"{item['inicio_s']:.2f}s" if item['inicio_s'] is not None else "tempo indisponível"
            print(f"#{item['id']} [{item['idioma']}] {tempo}: {medida}")
        print(f"Relatório: {destino}")
        if args.somente_metricas:
            print("Métricas coletadas; qualidade da fala não aprovada automaticamente.")
        else:
            print(f"WER global: {relatorio['wer_global']:.1%} | "
                  + ("OK" if relatorio['aprovado'] else "REPROVADO"))
        sys.exit(1 if relatorio["aprovado"] is False else 0)
    if not args.audio or not args.texto:
        ap.error("Informe áudio e texto, ou use --manifesto.")
    if args.somente_metricas or args.relatorio:
        ap.error("--somente-metricas e --relatorio requerem --manifesto.")

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
    ponto = [h for op, r, h, _ in diffs if op in ("insert", "replace") and re.search(r"\b(?:ponto|punto)\b", h)]
    if ponto:
        print(f"\nAVISO: palavra 'ponto/punto' falada {len(ponto)}x (pontuação final lida em voz alta).")

    print("\nTranscrição completa:\n" + transcricao.strip())
    status = "OK" if wer <= args.limite_wer else "REPROVADO"
    print(f"\nResultado: {status} (limite {args.limite_wer:.0%})")
    sys.exit(0 if wer <= args.limite_wer else 1)


if __name__ == "__main__":
    main()
