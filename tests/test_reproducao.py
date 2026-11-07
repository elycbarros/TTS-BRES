"""Transporte PCM e ciclo de vida do player sem emitir som no dispositivo real."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, MagicMock
import wave

from reproducao import TransportePCM, executar, calcular_envelope_wav
try:
    from test_biblioteca_vozes import criar_wav
except ImportError:
    from tests.test_biblioteca_vozes import criar_wav


class TestTransportePCM(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.wav = Path(self.tmp.name)/'teste.wav'; criar_wav(self.wav, duracao=1)
        self.transporte = TransportePCM(self.wav); self.addCleanup(self.transporte.fechar)

    def test_pausa_busca_e_parada_sem_alterar_audio(self):
        original = self.wav.read_bytes()
        self.assertNotEqual(self.transporte.ler(100), bytes(200))
        self.transporte.comando({'acao': 'pausar'})
        posicao = self.transporte.estado()['segundos']
        self.assertEqual(self.transporte.ler(100), bytes(200))
        self.assertEqual(self.transporte.estado()['segundos'], posicao)
        self.transporte.comando({'acao': 'buscar', 'segundos': .5})
        self.assertAlmostEqual(self.transporte.estado()['segundos'], .5)
        self.transporte.comando({'acao': 'reproduzir'})
        self.transporte.ler(100)
        self.assertGreater(self.transporte.estado()['segundos'], .5)
        self.transporte.comando({'acao': 'parar'})
        self.assertEqual(self.transporte.estado()['segundos'], 0)
        self.assertTrue(self.transporte.pausado)
        self.assertEqual(self.wav.read_bytes(), original)

    def test_fim_preenche_buffer_e_reinicia(self):
        self.transporte.comando({'acao': 'buscar', 'segundos': .999})
        dados = self.transporte.ler(100)
        self.assertEqual(len(dados), 200)
        self.assertEqual(dados[-100:], bytes(100))
        self.assertTrue(self.transporte.pausado)
        self.transporte.comando({'acao': 'reproduzir'})
        self.assertEqual(self.transporte.estado()['segundos'], 0)

    def test_busca_limita_posicao_e_rejeita_nao_finitos(self):
        for valor, esperado in ((-1, 0), (9, 1)):
            self.transporte.comando({'acao': 'buscar', 'segundos': valor})
            self.assertEqual(self.transporte.estado()['segundos'], esperado)
        for valor in (True, 'a', float('nan'), float('inf')):
            with self.assertRaises(ValueError): self.transporte.comando({'acao': 'buscar', 'segundos': valor})

    def test_rejeita_formato_inesperado(self):
        outro = self.wav.with_name('8bit.wav')
        with wave.open(str(outro), 'wb') as audio:
            audio.setparams((1, 1, 8000, 0, 'NONE', 'not compressed')); audio.writeframes(b'\x80'*10)
        with self.assertRaises(ValueError): TransportePCM(outro)

    def test_stream_json_callback_e_liberacao(self):
        saidas = []
        class Stream:
            def __init__(interno, **kwargs):
                self.assertEqual(kwargs['dtype'], 'int16')
                interno.callback = kwargs['callback']
            def __enter__(interno):
                buffer = bytearray(40); interno.callback(buffer, 20, None, None)
                saidas.append(bytes(buffer)); return interno
            def __exit__(interno, *_args): saidas.append('fechado')
        fake = types.SimpleNamespace(RawOutputStream=Stream)
        entrada = io.StringIO('{"acao":"pausar"}\n{"acao":"buscar","segundos":0.5}\n{"acao":"fechar"}\n')
        texto = io.StringIO()
        with patch.dict(sys.modules, {'sounddevice': fake}), patch('sys.stdin', entrada), contextlib.redirect_stdout(texto):
            executar(self.wav)
        self.assertEqual(saidas[-1], 'fechado')
        estados = [json.loads(linha) for linha in texto.getvalue().splitlines()]
        self.assertEqual(estados[-1]['segundos'], .5)
        self.assertTrue(estados[-1]['pausado'])

    def test_falha_dispositivo_libera_transporte(self):
        transporte = MagicMock()
        fake = types.SimpleNamespace(RawOutputStream=MagicMock(side_effect=OSError('dispositivo ausente')))
        with patch.dict(sys.modules, {'sounddevice': fake}), patch('reproducao.TransportePCM', return_value=transporte), \
                patch('sys.stdin', io.StringIO('')):
            with self.assertRaises(OSError): executar(self.wav)
        transporte.fechar.assert_called_once()

    def test_calcular_envelope_wav_sucesso_e_saturacao(self):
        env = calcular_envelope_wav(self.wav, colunas=50)
        self.assertEqual(len(env['colunas']), 50)
        self.assertAlmostEqual(env['duracao_s'], 1.0, places=1)
        self.assertGreater(env['pico_max'], 0.0)
        self.assertIn('tem_saturacao', env)
        for col in env['colunas']:
            self.assertGreaterEqual(col['pico'], 0.0)
            self.assertLessEqual(col['pico'], 1.0)
            self.assertGreaterEqual(col['rms'], 0.0)
            self.assertLessEqual(col['rms'], 1.0)

        # Arquivo com saturação explícita (amostra máxima 32767)
        sat_wav = self.wav.with_name('sat.wav')
        with wave.open(str(sat_wav), 'wb') as wf:
            wf.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
            # 24000 amostras com pico 32767
            wf.writeframes((b'\xff\x7f' * 12000) + (b'\x00\x00' * 12000))
        env_sat = calcular_envelope_wav(sat_wav, colunas=20)
        self.assertTrue(env_sat['tem_saturacao'])
        self.assertTrue(any(c['saturado'] for c in env_sat['colunas']))
        self.assertTrue(any(c['silencio'] for c in env_sat['colunas']))

    def test_calcular_envelope_wav_rejeita_invalido(self):
        vazio = self.wav.with_name('vazio.wav')
        with wave.open(str(vazio), 'wb') as wf:
            wf.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        with self.assertRaises(ValueError):
            calcular_envelope_wav(vazio)

        oito_bits = self.wav.with_name('oito.wav')
        with wave.open(str(oito_bits), 'wb') as wf:
            wf.setparams((1, 1, 8000, 0, 'NONE', 'not compressed'))
            wf.writeframes(b'\x80' * 10)
        with self.assertRaises(ValueError):
            calcular_envelope_wav(oito_bits)


if __name__ == '__main__': unittest.main()
