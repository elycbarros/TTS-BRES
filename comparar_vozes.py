"""Gera uma frase curta com várias vozes embutidas do XTTS para comparação por idioma."""
import argparse
import os
from pathlib import Path

os.environ.setdefault("COQUI_TOS_AGREED", "1")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np
import soundfile as sf
from TTS.api import TTS

FRASES = {
    "pt": (
        "No aprendizado supervisionado, o modelo treina com dados rotulados, "
        "ou seja, pares de entrada e resposta correta, e ajusta seus parâmetros "
        "para minimizar o erro"
    ),
    "es": (
        "En el aprendizaje supervisado, el modelo entrena con datos etiquetados, "
        "es decir, pares de entrada y respuesta correcta, y ajusta sus parâmetros "
        "y algoritmos de inteligencia artificial para minimizar el error"
    ).replace("parâmetros", "parámetros"),
}

VOZES_PADRAO = [
    "Alma María",
    "Ana Florence",
    "Sofia Hellen",
    "Claribel Dervla",
    "Daisy Studious",
    "Gracie Wise",
    "Tammie Ema",
    "Luis Moray",
    "Marcos Rudaski",
    "Gilberto Mathias",
    "Ferran Simen",
    "Xavier Hayasaka",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--idioma", default="es", choices=["pt", "es"], help="Idioma do teste (pt ou es)")
    ap.add_argument("--saida", default=None, help="Pasta de saída (padrão: saida/vozes_<idioma>)")
    ap.add_argument("--listar", action="store_true", help="Lista todas as vozes disponíveis no XTTS v2")
    args = ap.parse_args()

    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
    disponiveis = list(getattr(tts, "speakers", []) or [])
    if args.listar:
        print(f"Total de vozes ({len(disponiveis)}):", ", ".join(disponiveis))

    pasta = Path(args.saida) if args.saida else Path(f"saida/vozes_{args.idioma}" if args.idioma != "pt" else "saida/vozes")
    pasta.mkdir(parents=True, exist_ok=True)
    frase = FRASES[args.idioma]

    for v in VOZES_PADRAO:
        if disponiveis and v not in disponiveis:
            print(f"Pulando voz inexistente: {v}", flush=True)
            continue
        wav = tts.tts(text=frase, speaker=v, language=args.idioma, split_sentences=False)
        destino = pasta / f"{v.replace(' ', '_')}.wav"
        sf.write(str(destino), np.asarray(wav, dtype=np.float32), 24000)
        print("Gerado:", destino, flush=True)


if __name__ == "__main__":
    main()
