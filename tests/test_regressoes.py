"""Regressões de números, glossários e validação da fala."""
import json
import contextlib
import io
import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normalizador import carregar_glossario, normalizar_para_fala, numero_por_extenso_es
from validar_audio import alinhar, tokenizar


class TestRegressoes(unittest.TestCase):
    def test_tokenizacao_espanhol(self):
        self.assertEqual(tokenizar('[Alma|es]: Tengo 2 libros [pausa:1s].', 'es'),
                         ['tengo', 'dos', 'libros'])

    def test_numeros_grandes_espanhol(self):
        for numero, esperado in (
            (1_000_000_000, 'mil millones'),
            (21_000_000, 'veintiún millones'),
            (31_000, 'treinta y un mil'),
            (1_000_000_000_000, 'un billón'),
            (1_000_000_001, 'mil millones uno'),
        ):
            with self.subTest(numero=numero):
                self.assertEqual(numero_por_extenso_es(numero), esperado)
        self.assertTrue(numero_por_extenso_es(999_999_999_999))

    def test_glossario_geral_e_idioma(self):
        texto, _ = normalizar_para_fala('Kubernetes AWS GPU', idioma='es', glossario_extra={
            'Kubernetes': 'cubernetes', 'GPU': 'placa',
            'AWS': 'geral', 'es': {'AWS': 'nuvem'},
        })
        self.assertEqual(texto.lower(), 'cubernetes nuvem placa')

    def test_pronuncia_customizada_nao_e_reprocessada(self):
        texto, _ = normalizar_para_fala('GPU', idioma='pt', glossario_extra={'GPU': 'hardware'})
        self.assertEqual(texto.lower(), 'hardware')
        self.assertEqual(normalizar_para_fala('gpu GPU', idioma='pt')[0], 'gpu gê-pê-ú')

    def test_mescla_glossarios_por_idioma(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            (pasta / 'glossario.json').write_text(json.dumps({'es': {'A': 'a', 'B': 'b'}}))
            (pasta / 'texto.glossario.json').write_text(json.dumps({'es': {'B': 'novo'}}))
            with patch('normalizador.Path', wraps=Path) as paths:
                # Resolve apenas o glossário do projeto contra a pasta temporária.
                paths.side_effect = lambda value: pasta / value if value in ('glossario.json', 'glossario.txt') else Path(value)
                resultado = carregar_glossario(None, pasta / 'texto.txt')
            self.assertEqual(resultado['es'], {'A': 'a', 'B': 'novo'})

    def test_wer_minimo(self):
        self.assertEqual(alinhar(['a', 'a'], ['b', 'a'])[0], 1)
        self.assertEqual(alinhar('a b c'.split(), 'b c a'.split())[0], 2)
        self.assertEqual(alinhar('a b c d'.split(), 'c d a b'.split())[0], 4)
        for ref, hip, esperado in (([], [], 0), ([], ['a'], 1), (['a'], [], 1),
                                  (['a'], ['b'], 1), (['a'], ['a'], 0)):
            erros, diffs = alinhar(ref, hip)
            self.assertEqual(erros, esperado)
            self.assertEqual(len(diffs), esperado)

    def test_manifesto_corresponde_a_sintese(self):
        import numpy as np
        import tts
        from unittest.mock import MagicMock

        modelo = MagicMock()
        modelo.tts.return_value = np.sin(np.arange(2400) * 0.1) * 0.1
        api = types.ModuleType('TTS.api')
        api.TTS = MagicMock()
        api.TTS.return_value.to.return_value = modelo
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            entrada = pasta / 'texto.txt'
            entrada.write_text('[Alma|es]: Tengo 2 libros [pausa:800ms] y GPU.\n\n'
                               '[Luis]: [enfase] Olá mundo.', encoding='utf-8')
            args = ['tts.py', str(entrada), '--saida', str(pasta / 'audio'), '--formatos', 'wav']
            with patch.dict(sys.modules, {'TTS.api': api}), patch.object(sys, 'argv', args), \
                    patch.object(tts, 'escolher_dispositivo', return_value='cpu'), \
                    patch.object(tts, 'configurar_ffmpeg'), contextlib.redirect_stdout(io.StringIO()):
                tts.main()
            manifesto = json.loads((pasta / 'audio.blocos.json').read_text())
            falado = ' '.join(c.kwargs['text'] for c in modelo.tts.call_args_list)
            self.assertEqual(manifesto['blocos'][0]['texto_falado'], falado)
            self.assertNotIn('[', falado)
            self.assertTrue((pasta / 'audio.wav').is_file())


if __name__ == '__main__':
    unittest.main()
