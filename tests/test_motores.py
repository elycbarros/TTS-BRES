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

    def test_cache_latentes_em_memoria_e_disco(self):
        from pathlib import Path
        import torch
        import numpy as np

        class FakeXTTSModel:
            def __init__(self):
                self.device = torch.device('cpu')
                self.config = None
                self.chamadas_latentes = 0
                self.chamadas_inferencia = 0

            def get_conditioning_latents(self, audio_path, **_kwargs):
                self.chamadas_latentes += 1
                return torch.ones((1, 32, 1024)), torch.ones((1, 512, 1))

            def inference(self, text, language, gpt_cond_latent, speaker_embedding, speed=1.0, enable_text_splitting=False):
                self.chamadas_inferencia += 1
                return {'wav': np.zeros(2400, dtype=np.float32)}

        class FakeSynthesizer:
            def __init__(self, tts_model):
                self.tts_model = tts_model

        class FakeCoquiTTS:
            def __init__(self, tts_model):
                self.synthesizer = FakeSynthesizer(tts_model)
                self.tts = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            ref_wav = pasta / 'voz_ref.wav'
            ref_wav.write_bytes(b'RIFF-fake-wav-bytes')
            pasta_lat = pasta / 'latentes'

            xtts_interno = FakeXTTSModel()
            coqui = FakeCoquiTTS(xtts_interno)
            motor = MotorXTTS(coqui, pasta_cache_latentes=pasta_lat)

            # 1ª síntese: calcula latentes, salva em .latents.pt e chama inference()
            out1 = motor.sintetizar('Primeira frase', 'pt', None, str(ref_wav), 1.1)
            self.assertEqual(len(out1), 2400)
            self.assertEqual(xtts_interno.chamadas_latentes, 1)
            self.assertEqual(xtts_interno.chamadas_inferencia, 1)
            coqui.tts.assert_not_called()
            arquivos_pt = list(pasta_lat.glob('*.latents.pt'))
            self.assertEqual(len(arquivos_pt), 1)

            # 2ª síntese na mesma instância de modelo: reutiliza latentes em memória
            motor2 = MotorXTTS(coqui, pasta_cache_latentes=pasta_lat)
            motor2.sintetizar('Segunda frase', 'pt', None, str(ref_wav), 1.0)
            self.assertEqual(xtts_interno.chamadas_latentes, 1)
            self.assertEqual(xtts_interno.chamadas_inferencia, 2)

            # 3ª síntese em nova instância de modelo (simulando novo processo): carrega .latents.pt do disco sem recalcular WAV
            xtts_novo = FakeXTTSModel()
            coqui_novo = FakeCoquiTTS(xtts_novo)
            motor_novo = MotorXTTS(coqui_novo, pasta_cache_latentes=pasta_lat)
            motor_novo.sintetizar('Terceira frase', 'es', None, str(ref_wav), 1.0)
            self.assertEqual(xtts_novo.chamadas_latentes, 0)
            self.assertEqual(xtts_novo.chamadas_inferencia, 1)

