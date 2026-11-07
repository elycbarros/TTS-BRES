"""Teste isolado do protocolo experimental, sem pesos nem rede."""
from pathlib import Path
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch
import wave

from omnivoice_experimental import executar_worker


class TestOmniVoiceExperimental(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / 'modelo').mkdir()
        (root / 'voz.wav').write_bytes(b'referencia')
        self.pedido = {'modelo': str(root / 'modelo'), 'referencia': str(root / 'voz.wav'),
                       'saida': str(root / 'saida.wav'), 'texto': 'Olá mundo.',
                       'transcricao': 'Minha voz.', 'idioma': 'pt'}

    def test_requer_transcricao_antes_de_importar_modelo(self):
        self.pedido['transcricao'] = ''
        with self.assertRaisesRegex(ValueError, 'transcrição'):
            executar_worker(self.pedido)

    def test_protocolo_e_saida_pcm_sem_download(self):
        modelo = MagicMock()
        modelo.sampling_rate = 24000
        modelo.generate.return_value = [[0.0] * 2400]
        classe = MagicMock()
        classe.from_pretrained.return_value = modelo
        def gravar(caminho, _dados, taxa, subtype):
            self.assertEqual((taxa, subtype), (24000, 'PCM_16'))
            with wave.open(caminho, 'wb') as wav:
                wav.setparams((1, 2, taxa, 0, 'NONE', 'not compressed'))
                wav.writeframes(bytes(4800))
        modules = {'torch': types.SimpleNamespace(float32='float32'),
                   'soundfile': types.SimpleNamespace(write=gravar),
                   'omnivoice': types.SimpleNamespace(OmniVoice=classe)}
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {}, clear=False):
            resultado = executar_worker(self.pedido)
            self.assertEqual(os.environ['HF_HUB_OFFLINE'], '1')
            self.assertEqual(os.environ['TRANSFORMERS_OFFLINE'], '1')
        self.assertEqual(modelo.generate.call_count, 2)
        self.assertFalse(classe.from_pretrained.call_args.kwargs['load_asr'])
        self.assertEqual(modelo.generate.call_args.kwargs['ref_text'], 'Minha voz.')
        self.assertEqual(modelo.generate.call_args.kwargs['language'], 'pt')
        self.assertEqual(resultado['duracao_s'], .1)
        self.assertIsNone(resultado['semente'])

    def test_rejeita_idioma_antes_da_inferencia(self):
        self.pedido['idioma'] = 'en'
        with self.assertRaisesRegex(ValueError, 'Idioma'):
            executar_worker(self.pedido)

    def test_rejeita_taxa_nativa_sem_rotular_errado(self):
        modelo = MagicMock(); modelo.sampling_rate = 48000
        classe = MagicMock(); classe.from_pretrained.return_value = modelo
        modules = {'torch': types.SimpleNamespace(float32='float32'),
                   'soundfile': types.SimpleNamespace(),
                   'omnivoice': types.SimpleNamespace(OmniVoice=classe)}
        with patch.dict(sys.modules, modules), self.assertRaisesRegex(ValueError, 'Taxa nativa'):
            executar_worker(self.pedido)
