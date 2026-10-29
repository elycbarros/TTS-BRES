"""Métricas acústicas por segmento PCM; não medem naturalidade ou sotaque."""
import math
import wave
import numpy as np


def medir_segmento(caminho):
    total = saturadas = 0
    energia = pico = 0.0
    with wave.open(str(caminho), 'rb') as audio:
        if audio.getsampwidth() != 2 or audio.getnchannels() != 1:
            raise ValueError('As métricas requerem WAV PCM mono de 16 bits.')
        sr = audio.getframerate()
        for dados in iter(lambda: audio.readframes(32768), b''):
            sinal = np.frombuffer(dados, dtype='<i2').astype(np.float64) / 32768
            total += len(sinal)
            energia += float(np.dot(sinal, sinal))
            pico = max(pico, float(np.max(np.abs(sinal))))
            saturadas += int(np.count_nonzero(np.abs(sinal) >= 0.999))
    if total == 0:
        raise ValueError(f'Áudio vazio: {caminho}')
    rms = math.sqrt(energia / total)
    return {'duracao_s': total / sr,
            'rms_dbfs': 20 * math.log10(rms) if rms else None,
            'pico_dbfs': 20 * math.log10(pico) if pico else None,
            'fracao_amostras_saturadas': saturadas / total,
            'avisos': (['silencio_ou_nivel_muito_baixo'] if rms < 0.001 else [])
                      + (['amostras_proximas_da_saturacao'] if saturadas else [])}
