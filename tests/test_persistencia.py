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

    def test_masterizacao_lufs_e_taxa_amostragem_com_ffmpeg_real(self):
        self.executar('--formatos', 'mp3,wav', '--lufs', '-16', '--taxa-amostragem', '44100')
        self.assertGreater((self.pasta / 'aula.v2.mp3').stat().st_size, 100)
        with wave.open(str(self.pasta / 'aula.v2.wav'), 'rb') as audio:
            self.assertEqual(audio.getframerate(), 44100)

    def test_multiplas_vozes_clonadas_por_personagem_e_cache_seletivo(self):
        voz_a = self.pasta / 'voz_a.wav'
        voz_b = self.pasta / 'voz_b.wav'
        with AudioSegment.silent(100).export(str(voz_a), format='wav'):
            pass
        with AudioSegment.silent(150).export(str(voz_b), format='wav'):
            pass
        self.entrada.write_text('[Luis]: Fala um.\n\n[voz_b.wav|es]: Habla dos.', encoding='utf-8')
        self.executar('--vozes-personagens', f'luis={voz_a}')
        self.assertEqual(self.modelo.tts.call_count, 2)
        chamadas = self.modelo.tts.call_args_list
        self.assertEqual(Path(chamadas[0].kwargs['speaker_wav']).resolve(), voz_a.resolve())
        self.assertEqual(Path(chamadas[1].kwargs['speaker_wav']).resolve(), voz_b.resolve())
        # Alterar apenas a voz_b deve invalidar apenas o segundo segmento
        self.modelo.tts.reset_mock()
        with AudioSegment.silent(250).export(str(voz_b), format='wav'):
            pass
        self.executar('--vozes-personagens', f'luis={voz_a}')
        self.assertEqual(self.modelo.tts.call_count, 1)
        self.assertEqual([s['reutilizado'] for s in self.manifesto()['segmentos']], [True, False])

    def test_auto_retry_contra_alucinacao_e_silencio(self):
        # 1ª chamada: alucinação (6 segundos para texto curto); 2ª chamada: áudio normal de 0.1s
        alucinacao = np.sin(np.arange(24000 * 6) * .1) * .1
        self.entrada.write_text('Olá.', encoding='utf-8')
        self.modelo.tts.side_effect = [alucinacao, self.sinal]
        self.executar('--sem-corte-silencio')
        self.assertEqual(self.modelo.tts.call_count, 2)
        self.assertAlmostEqual(self.manifesto()['segmentos'][0]['duracao_s'], 0.1)

    def test_higienizar_referencia_e_condicionamento_por_tom(self):
        voz_base = self.pasta / 'voz_ruidosa.wav'
        voz_enfase = self.pasta / 'voz_enfatica.wav'
        sinal_1 = (np.sin(np.arange(12000) * .1) * 4000).astype('<i2')
        sinal_2 = (np.sin(np.arange(16000) * .2) * 5000).astype('<i2')
        with AudioSegment(sinal_1.tobytes(), frame_rate=ap.SR, sample_width=2, channels=1).export(str(voz_base), format='wav'):
            pass
        with AudioSegment(sinal_2.tobytes(), frame_rate=ap.SR, sample_width=2, channels=1).export(str(voz_enfase), format='wav'):
            pass
        self.entrada.write_text('Fala normal. [tom:enfatico] Fala com ênfase real.', encoding='utf-8')
        self.executar('--voz', str(voz_base), '--vozes-tons', f'enfatico={voz_enfase}', '--limpar-referencia')
        self.assertEqual(self.modelo.tts.call_count, 2)
        chamadas = self.modelo.tts.call_args_list
        wav_usado_1 = Path(chamadas[0].kwargs['speaker_wav'])
        wav_usado_2 = Path(chamadas[1].kwargs['speaker_wav'])
        self.assertTrue(wav_usado_1.name.endswith('.limpo.wav'))
        self.assertTrue(wav_usado_2.name.endswith('.limpo.wav'))
        self.assertNotEqual(wav_usado_1, wav_usado_2)
        self.assertAlmostEqual(chamadas[1].kwargs['speed'], round(1.1 * 1.05, 4))

    def test_regeneracao_seletiva_de_segmento(self):
        self.entrada.write_text('Primeira fala. Segunda fala. Terceira fala.', encoding='utf-8')
        self.executar()
        self.assertEqual(self.modelo.tts.call_count, 3)
        self.modelo.tts.reset_mock()
        self.executar('--refazer-segmentos', '2')
        self.assertEqual(self.modelo.tts.call_count, 1)
        self.assertEqual(self.modelo.tts.call_args.kwargs['text'], 'Segunda fala')
        self.assertEqual([s['reutilizado'] for s in self.manifesto()['segmentos']], [True, False, True])

    def test_trilha_bgm_com_autoducking_ffmpeg_real(self):
        trilha = self.pasta / 'musica.wav'
        sinal_bg = (np.sin(np.arange(24000) * .05) * 3000).astype('<i2')
        with AudioSegment(sinal_bg.tobytes(), frame_rate=ap.SR, sample_width=2, channels=1).export(str(trilha), format='wav'):
            pass
        self.executar('--formatos', 'mp3,wav', '--trilha', str(trilha), '--volume-trilha', '-16')
        self.assertGreater((self.pasta / 'aula.v2.mp3').stat().st_size, 100)
        self.assertGreater((self.pasta / 'aula.v2.wav').stat().st_size, 100)


if __name__ == '__main__':
    unittest.main()
