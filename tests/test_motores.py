"""Contrato do motor sem carregar pesos ou acessar a rede."""
import unittest
from unittest.mock import MagicMock
from motores import MotorXTTS, MotorSintese
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
