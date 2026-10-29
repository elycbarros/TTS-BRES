"""Retomada após falha, integridade do cache e montagem em disco."""
import contextlib
import io
import json
import sys
import tempfile
import tracemalloc
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from pydub import AudioSegment
import audio_persistente as ap
import tts


class TestPersistencia(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pasta = Path(self.tmp.name)
        self.entrada = self.pasta / 'texto.txt'
        self.entrada.write_text('Primeira fala. Segunda fala.', encoding='utf-8')
        self.base = self.pasta / 'aula.v2'
        self.api = types.ModuleType('TTS.api')
        self.api.TTS = MagicMock()
        self.modelo = self.api.TTS.return_value.to.return_value
        self.sinal = np.sin(np.arange(2400) * .1) * .1
        self.modelo.tts.return_value = self.sinal

    def executar(self, *opcoes):
        argv = ['tts.py', str(self.entrada), '--saida', str(self.base), '--formatos', 'wav', *opcoes]
        with patch.dict(sys.modules, {'TTS.api': self.api}), patch.object(sys, 'argv', argv), \
                patch.object(tts, 'escolher_dispositivo', return_value='cpu'), \
                contextlib.redirect_stdout(io.StringIO()):
            tts.main()

    def manifesto(self):
        return json.loads((self.pasta / 'aula.v2.blocos.json').read_text())

    def test_retoma_apos_interrupcao(self):
        self.modelo.tts.side_effect = [self.sinal, KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            self.executar()
        self.assertFalse((self.pasta / 'aula.v2.wav').exists())
        self.assertEqual(len(self.manifesto()['segmentos']), 1)
        self.modelo.tts.reset_mock(side_effect=True)
        self.modelo.tts.return_value = self.sinal
        self.executar()
        self.assertEqual(self.modelo.tts.call_count, 1)
        self.assertEqual(self.modelo.tts.call_args.kwargs['text'], 'Segunda fala')
        self.assertEqual([s['reutilizado'] for s in self.manifesto()['segmentos']], [True, False])
        self.assertEqual(self.manifesto()['estado'], 'concluido')

    def test_cache_completo_nao_carrega_modelo(self):
        self.executar()
        esperado = (self.pasta / 'aula.v2.wav').read_bytes()
        self.api.TTS.reset_mock()
        self.executar()
        self.api.TTS.assert_not_called()
        self.assertEqual((self.pasta / 'aula.v2.wav').read_bytes(), esperado)

    def test_cache_corrompido_regenera_apenas_afetado(self):
        self.executar()
        arquivo = Path(self.manifesto()['segmentos'][0]['arquivo'])
        dados = bytearray(arquivo.read_bytes())
        dados[-1] ^= 1
        arquivo.write_bytes(dados)
        self.modelo.tts.reset_mock()
        self.executar()
        self.assertEqual(self.modelo.tts.call_count, 1)
        self.assertEqual([s['reutilizado'] for s in self.manifesto()['segmentos']], [False, True])

    def test_parametros_invalidam_e_pausas_reutilizam(self):
        self.executar()
        self.modelo.tts.reset_mock()
        self.executar('--pausa-frase', '100')
        self.modelo.tts.assert_not_called()
        self.executar('--velocidade', '1.2')
        self.assertEqual(self.modelo.tts.call_count, 2)
        self.modelo.tts.reset_mock()
        self.executar('--velocidade', '1.2', '--refazer')
        self.assertEqual(self.modelo.tts.call_count, 2)

    def test_conteudo_referencia_invalida_cache(self):
        referencia = self.pasta / 'referencia.wav'
        with AudioSegment.silent(100).export(str(referencia), format='wav'):
            pass
        self.executar('--voz', str(referencia))
        self.modelo.tts.reset_mock()
        with AudioSegment.silent(200).export(str(referencia), format='wav'):
            pass
        self.executar('--voz', str(referencia))
        self.assertEqual(self.modelo.tts.call_count, 2)

    def test_montagem_preserva_pcm_pausas_e_limita_memoria(self):
        cache = ap.CacheSegmentos(self.pasta / 'cache')
        sinal = AudioSegment(b'\x01\x00' * ap.SR, frame_rate=ap.SR, sample_width=2, channels=1)
        caminho, _, _ = cache.obter({'teste': 1}, lambda: sinal)
        destino = self.pasta / 'montado.wav'
        ap.montar_wav([200, caminho, 1500, caminho], destino)
        with wave.open(str(destino)) as audio:
            pcm = audio.readframes(audio.getnframes())
        self.assertEqual(pcm, bytes(ap.SR * 2 // 5) + sinal.raw_data
                         + bytes(ap.SR * 3) + sinal.raw_data)
        # Saída de 14,4 MB: a montagem deve manter apenas buffers pequenos em memória.
        tracemalloc.start()
        try:
            ap.montar_wav([caminho] * 300, destino)
            _, pico = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(pico, 2_000_000)
        with wave.open(str(destino)) as audio:
            self.assertEqual(audio.getnframes(), 300 * ap.SR)

    def test_falha_exportacao_preserva_saida_e_permite_retomar(self):
        self.executar()
        destino = self.pasta / 'aula.v2.mp3'
        destino.write_bytes(b'anterior')
        with patch('audio_persistente.subprocess.run', return_value=types.SimpleNamespace(
                returncode=1, stderr='erro simulado')), self.assertRaises(RuntimeError):
            self.executar('--formatos', 'mp3')
        self.assertEqual(destino.read_bytes(), b'anterior')
        self.assertEqual(self.manifesto()['estado'], 'montando')
        self.api.TTS.reset_mock()
        self.executar()
        self.api.TTS.assert_not_called()

    def test_metadados_incompletos_nao_impedem_retomada(self):
        self.executar()
        arquivo = Path(self.manifesto()['segmentos'][0]['arquivo'])
        arquivo.with_suffix('.json').write_text('{', encoding='utf-8')
        self.modelo.tts.reset_mock()
        self.executar()
        self.assertEqual(self.modelo.tts.call_count, 1)

    def test_texto_voz_idioma_volume_e_corte_invalidam(self):
        self.executar()
        for opcoes in (('--locutor', 'Ana Florence'), ('--idioma', 'es'),
                       ('--volume-alvo', '-25'), ('--sem-corte-silencio',)):
            with self.subTest(opcoes=opcoes):
                self.modelo.tts.reset_mock()
                self.executar(*opcoes)
                self.assertEqual(self.modelo.tts.call_count, 2)
        self.entrada.write_text('Primeira fala. Fala alterada.', encoding='utf-8')
        self.modelo.tts.reset_mock()
        self.executar()
        self.assertEqual(self.modelo.tts.call_count, 1)

    def test_limite_riff_rejeitado_antes_de_gravar(self):
        destino = self.pasta / 'grande.wav'
        with self.assertRaisesRegex(ValueError, '4 GB'):
            ap.montar_wav([100_000_000], destino)
        self.assertFalse(destino.exists())

    def test_mp3_com_ffmpeg_real(self):
        self.executar('--formatos', 'mp3,wav')
        self.assertGreater((self.pasta / 'aula.v2.mp3').stat().st_size, 100)
        self.assertEqual(self.manifesto()['estado'], 'concluido')


if __name__ == '__main__':
    unittest.main()
