"""Contrato do motor sem carregar pesos ou acessar a rede."""
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import wave
from motores import MotorXTTS, MotorSintese, _garantir_torchaudio_load
from audio_persistente import chave_segmento


class TestMotores(unittest.TestCase):
    def test_contrato_e_parametros_efetivos(self):
        modelo = MagicMock()
        motor = MotorXTTS(modelo)
        self.assertIsInstance(motor, MotorSintese)
        motor.sintetizar('Olá', 'pt', 'Luis', None, 1.1)
        modelo.tts.assert_called_once_with(text='Olá', speaker='Luis', language='pt', split_sentences=False, speed=1.1)
        modelo.reset_mock()
        motor.sintetizar('Hola', 'es', 'Luis', 'voz.wav', 1.0)
        modelo.tts.assert_called_once_with(text='Hola', speaker_wav='voz.wav', language='es', split_sentences=False, speed=1.0)
        with self.assertRaises(ValueError):
            motor.sintetizar('Hello', 'en', 'Luis', None, 1.0)

    def test_motor_altera_identidade_do_cache(self):
        a = {'motor': 'xtts_v2', 'texto': 'Olá'}
        b = {'motor': 'outro_motor', 'texto': 'Olá'}
        self.assertNotEqual(chave_segmento(a), chave_segmento(b))

    def test_fallback_soundfile_quando_torchcodec_falha(self):
        import sys
        import types
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            caminho = f'{tmp}/ref.wav'
            with wave.open(caminho, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes((np.zeros(2400, dtype=np.int16)).tobytes())
            falso_ta = types.SimpleNamespace(
                load=MagicMock(side_effect=RuntimeError('Could not load libtorchcodec'))
            )
            falso_sf = types.SimpleNamespace(
                read=lambda uri, start=0, frames=-1, dtype='float32', always_2d=True: (
                    np.zeros((2400, 1), dtype=np.float32), 24000
                )
            )
            falso_torch = types.SimpleNamespace(from_numpy=lambda arr: arr)
            with patch.dict(sys.modules, {'torchaudio': falso_ta, 'soundfile': falso_sf, 'torch': falso_torch}):
                _garantir_torchaudio_load()
                tensor, sr = falso_ta.load(caminho)
                self.assertEqual(sr, 24000)
                self.assertEqual(tensor.shape, (1, 2400))
