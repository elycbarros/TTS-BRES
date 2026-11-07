"""Experimento local e isolado do OmniVoice; não integra a GUI nem a fila."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import wave


def executar_worker(pedido):
    """Somente modelo local e transcrição explícita; não solicita ASR automático."""
    modelo = Path(pedido['modelo']).expanduser().resolve()
    referencia = Path(pedido['referencia']).expanduser().resolve()
    saida = Path(pedido['saida']).resolve()
    if not modelo.is_dir() or not referencia.is_file():
        raise ValueError('Modelo local ou referência ausente.')
    if not isinstance(pedido.get('transcricao'), str) or not pedido['transcricao'].strip():
        raise ValueError('Informe a transcrição correspondente à referência; ASR automático está desativado.')
    if not isinstance(pedido.get('texto'), str) or not pedido['texto'].strip():
        raise ValueError('Informe o texto a sintetizar.')
    if pedido.get('idioma') not in ('pt', 'es'):
        raise ValueError('Idioma deve ser pt ou es.')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import torch
    import soundfile as sf
    from omnivoice import OmniVoice
    inicio = time.perf_counter()
    dispositivo = pedido.get('dispositivo', 'cpu')
    if dispositivo not in ('cpu', 'mps', 'cuda'):
        raise ValueError('Dispositivo inválido.')
    modelo_tts = OmniVoice.from_pretrained(str(modelo), device_map=dispositivo, dtype=torch.float32, load_asr=False)
    if modelo_tts.sampling_rate != 24000:
        raise ValueError('Taxa nativa diferente de 24 kHz; conversão para este modelo ainda não está implementada.')
    def sincronizar():
        if dispositivo == 'cuda': torch.cuda.synchronize()
        elif dispositivo == 'mps': torch.mps.synchronize()
    sincronizar()
    carga_s = time.perf_counter() - inicio
    tempos = []
    audio = None
    for _ in range(2):
        inicio = time.perf_counter()
        resultado = modelo_tts.generate(text=pedido['texto'], language=pedido['idioma'],
                                        ref_audio=str(referencia), ref_text=pedido['transcricao'])
        sincronizar()
        tempos.append(time.perf_counter() - inicio)
        if not isinstance(resultado, (list, tuple)) or len(resultado) != 1:
            raise ValueError('O motor não retornou uma única amostra.')
        import numpy as np
        audio = np.asarray(resultado[0])
        if audio.ndim != 1 or audio.size == 0 or not np.isfinite(audio).all():
            raise ValueError('A amostra retornada é vazia, não mono ou contém valores inválidos.')
    sf.write(str(saida), audio, 24000, subtype='PCM_16')
    with wave.open(str(saida), 'rb') as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 24000 or not wav.getnframes():
            raise ValueError('A saída não é WAV PCM mono de 16 bits a 24 kHz.')
        duracao = wav.getnframes() / wav.getframerate()
    memoria = None
    try:
        import resource
        memoria = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform.startswith('linux'): memoria *= 1024
    except (ImportError, AttributeError):
        pass
    return {'motor': 'omnivoice_experimental', 'taxa_hz': 24000, 'duracao_s': duracao,
            'carga_s': carga_s, 'primeira_sintese_s': tempos[0], 'sintese_quente_s': tempos[1],
            'rtf_quente': tempos[1] / duracao, 'semente': None, 'dispositivo': dispositivo,
            'memoria_pico_processo_bytes': memoria}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.worker:
        parser.error('Use este módulo como worker experimental; consulte docs/MOTORES_E4.md.')
    try:
        pedido = json.load(sys.stdin)
        gate = os.environ.get('TTSBR_EXPERIMENTO_GATE')
        if gate:
            limite = time.monotonic() + 30
            while not Path(gate).exists():
                if time.monotonic() > limite:
                    raise RuntimeError('O supervisor não liberou a execução.')
                time.sleep(.02)
        resultado = executar_worker(pedido)
        print(json.dumps({'resultado': resultado}, ensure_ascii=False, allow_nan=False), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({'erro': str(exc)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
