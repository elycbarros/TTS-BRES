"""Validação antecipada da CLI e integridade das tags no pipeline."""
import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import tts


class TestPreparacao(unittest.TestCase):
    def test_tag_na_fronteira_nao_e_cortada(self):
        for normalizar in (True, False):
            with self.subTest(normalizar=normalizar):
                itens = tts.preparar_segmentos('a' * 190 + ' [pausa: 1500ms] fim.', 'pt', normalizar)
                self.assertEqual([mods['pausa_extra_ms'] for _, mods in itens
                                  if 'pausa_extra_ms' in mods], [1500])
                falas = [texto for texto, _ in itens if texto]
                self.assertTrue(all(len(t) <= tts.MAX_CHARS for t in falas))
                self.assertEqual(' '.join(falas), 'a' * 190 + ' fim.')

    def test_volume_aplicado_apenas_ao_primeiro_segmento(self):
        itens = tts.preparar_segmentos('[enfase] ' + 'fala ' * 100, 'pt', False)
        self.assertGreater(len(itens), 1)
        self.assertEqual(itens[0][1], {'volume_offset_db': 2.5})
        self.assertTrue(all(not mods for _, mods in itens[1:]))

    def test_tags_invalidas(self):
        for tag in ('[enfaze]', '[pausa:-1s]', '[pausa:nan]', '[pausa:]',
                    '[pausa:abc]', '[respiro:1s]', '[pausa:1s', '[[]]', '[]', '[pausa:1s]]',
                    '[tom:]', '[tom:invalido com espaco]'):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                tts.preparar_segmentos('antes ' + tag + ' depois', 'pt')

    def test_tag_tom_predefinido_e_customizado(self):
        itens = tts.preparar_segmentos('[tom:calmo] Fala tranquila. Segunda frase.', 'pt', False)
        self.assertEqual(itens[0][1]['tom'], 'calmo')
        self.assertEqual(itens[0][1]['volume_offset_db'], -2.0)
        self.assertEqual(itens[0][1]['velocidade_fator'], 0.92)
        self.assertEqual(itens[1][1], {})

    def test_aliases_e_pausas(self):
        for tag, ms in (('[pausa]', 1000), ('[silencio:1.5s]', 1500),
                        ('[pausa: 800 ms]', 800), ('[respiro]', 400), ('[pausa:0s]', 0)):
            with self.subTest(tag=tag):
                self.assertEqual(tts.preparar_segmentos(tag, 'pt'), [('', {'pausa_extra_ms': ms})])


class TestCLI(unittest.TestCase):
    def test_rejeita_antes_de_carregar_modelo_ou_gravar(self):
        casos = [
            ('Olá.', ['--velocidade', '0']),
            ('Olá.', ['--velocidade', '-1']),
            ('Olá.', ['--velocidade', 'nan']),
            ('Olá.', ['--velocidade', 'inf']),
            ('Olá.', ['--volume-alvo', 'nan']),
            ('Olá.', ['--volume-alvo', '1']),
            ('Olá.', ['--formatos', 'ogg']),
            ('Olá.', ['--formatos', '']),
            ('Olá.', ['--formatos', 'mp3,']),
            ('Olá.', ['--lufs', '0']),
            ('Olá.', ['--lufs', '-80']),
            ('Olá.', ['--lufs', 'nan']),
            ('Olá.', ['--taxa-amostragem', '16000']),
            ('Olá.', ['--voz', '/arquivo-inexistente.wav']),
            ('Olá.', ['--vozes-personagens', 'invalido']),
            ('Olá.', ['--vozes-personagens', 'luis=/inexistente.wav']),
            ('Olá.', ['--vozes-tons', 'calmo=/inexistente.wav']),
            ('Olá.', ['--max-tentativas', '0']),
            ('Olá.', ['--refazer-segmentos', '0']),
            ('Olá.', ['--refazer-segmentos', 'abc']),
            ('Olá.', ['--refazer-segmentos', '5']),
            ('Olá.', ['--trilha', '/trilha-inexistente.mp3']),
            ('Olá.', ['--volume-trilha', '5']),
            ('[inexistente.wav]: Olá.', []),
            ('[tom:inexistente.wav] Olá.', []),
            ('[tom:tom_nao_mapeado] Olá.', []),
            ('', []), (' \n ', []), ('[pausa:1s]', []), ('[enfase]', []),
            ('[Luis|fr]: Bonjour.', []), ('[en]: Hello.', []),
            ('[Luis|]: Olá.', []), ('[|es]: Hola.', []),
            ('Olá.', ['--locutor', ' ']), ('Olá [enfaze].', []),
            ('Olá [pausa:-1s].', []), ('Olá.', ['--saida', '']),
        ]
        casos.extend(('Olá.', ['--' + nome, '-1']) for nome in (
            'pausa-frase', 'pausa-reticencias', 'pausa-ponto-virgula',
            'pausa-virgula', 'pausa-paragrafo', 'pausa-bloco'))
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            entrada = pasta / 'texto.txt'
            base = pasta / 'saida' / 'audio'
            api = types.ModuleType('TTS.api')
            api.TTS = MagicMock()
            for texto, opcoes in casos:
                with self.subTest(texto=texto, opcoes=opcoes):
                    entrada.write_text(texto, encoding='utf-8')
                    args = ['tts.py', str(entrada), '--saida', str(base), *opcoes]
                    with patch.dict(sys.modules, {'TTS.api': api}), patch.object(sys, 'argv', args), \
                            contextlib.redirect_stderr(io.StringIO()) as erro, \
                            contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exc:
                        tts.main()
                    self.assertEqual(exc.exception.code, 2)
                    self.assertIn('error:', erro.getvalue())
                    self.assertNotIn('Traceback', erro.getvalue())
                    api.TTS.assert_not_called()
                    self.assertFalse(base.parent.exists())

    def test_arquivo_inexistente(self):
        with patch.object(sys, 'argv', ['tts.py', '/texto-inexistente.txt']), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            tts.main()
        self.assertEqual(exc.exception.code, 2)

    def test_integracao_nome_com_ponto_e_pausa(self):
        api = types.ModuleType('TTS.api')
        api.TTS = MagicMock()
        modelo = api.TTS.return_value.to.return_value
        modelo.tts.return_value = np.sin(np.arange(2400) * .1) * .1
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            entrada = pasta / 'texto.txt'
            entrada.write_text('a' * 190 + ' [pausa: 1500ms] fim.', encoding='utf-8')
            base = pasta / 'aula.v2'
            args = ['tts.py', str(entrada), '--saida', str(base), '--formatos', ' WAV,wav ',
                    '--pausa-paragrafo', '0', '--sem-normalizar']
            pausas = []
            import audio_persistente
            silent = audio_persistente.escrever_silencio

            def registrar(audio, ms):
                pausas.append(ms)
                return silent(audio, ms)

            with patch.dict(sys.modules, {'TTS.api': api}), patch.object(sys, 'argv', args), \
                    patch.object(tts, 'escolher_dispositivo', return_value='cpu'), \
                    patch.object(tts, 'configurar_ffmpeg'), \
                    patch.object(audio_persistente, 'escrever_silencio', side_effect=registrar), \
                    contextlib.redirect_stdout(io.StringIO()):
                tts.main()
            self.assertEqual(pausas, [200, 1500])
            self.assertTrue((pasta / 'aula.v2.wav').is_file())
            self.assertFalse((pasta / 'aula.wav').exists())
            manifesto = json.loads((pasta / 'aula.v2.blocos.json').read_text())
            falas = [c.kwargs['text'] for c in modelo.tts.call_args_list]
            self.assertEqual(falas, ['a' * 190, 'fim'])
            self.assertEqual(manifesto['blocos'][0]['texto_falado'], ' '.join(falas))
            self.assertAlmostEqual(manifesto['segmentos'][0]['inicio_s'], .2)
            self.assertAlmostEqual(manifesto['segmentos'][1]['inicio_s'], 1.8)
            self.assertAlmostEqual(manifesto['segmentos'][1]['fim_s'], 1.9)

    def test_exportacao_legendas_srt_e_vtt(self):
        api = types.ModuleType('TTS.api')
        api.TTS = MagicMock()
        modelo = api.TTS.return_value.to.return_value
        modelo.tts.return_value = np.sin(np.arange(2400) * .1) * .1
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            entrada = pasta / 'texto.txt'
            entrada.write_text('Primeira frase. Segunda frase.', encoding='utf-8')
            base = pasta / 'video'
            args = ['tts.py', str(entrada), '--saida', str(base), '--formatos', 'wav',
                    '--srt', '--vtt', '--sem-corte-silencio']
            with patch.dict(sys.modules, {'TTS.api': api}), patch.object(sys, 'argv', args), \
                    patch.object(tts, 'escolher_dispositivo', return_value='cpu'), \
                    patch.object(tts, 'configurar_ffmpeg'), \
                    contextlib.redirect_stdout(io.StringIO()):
                tts.main()
            srt = (pasta / 'video.srt').read_text(encoding='utf-8')
            vtt = (pasta / 'video.vtt').read_text(encoding='utf-8')
            self.assertIn('1\n00:00:00,200 --> 00:00:00,300\nPrimeira frase', srt)
            self.assertIn('2\n00:00:00,900 --> 00:00:01,000\nSegunda frase', srt)
            self.assertTrue(vtt.startswith('WEBVTT\n\n'))
            self.assertIn('00:00:00.200 --> 00:00:00.300\nPrimeira frase', vtt)

    def test_alias_locutor_iapetus_em_espanhol(self):
        for locutor_arg in ('Iapetus', 'Iapetus (Xavier Hayasaka)'):
            with self.subTest(locutor_arg=locutor_arg), tempfile.TemporaryDirectory() as tmp:
                pasta = Path(tmp)
                entrada = pasta / 'texto_es.txt'
                entrada.write_text('[Iapetus|es]: Hola mundo.\n\nSegunda frase en español.', encoding='utf-8')
                eventos = []
                with contextlib.redirect_stdout(io.StringIO()):
                    tts.main([str(entrada), '--idioma', 'es', '--locutor', locutor_arg,
                              '--saida', str(pasta / 'audio'), '--analisar'], on_event=eventos.append)
                segs = eventos[0]['segmentos']
                self.assertEqual(len(segs), 2)
                self.assertEqual(segs[0]['locutor'], 'Xavier Hayasaka')
                self.assertEqual(segs[0]['idioma'], 'es')
                self.assertEqual(segs[1]['locutor'], 'Xavier Hayasaka')
                self.assertEqual(segs[1]['idioma'], 'es')

    def test_presets_precedencia_e_restauracao(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            entrada = pasta / 'texto.txt'
            entrada.write_text('Olá mundo.', encoding='utf-8')
            api = types.ModuleType('TTS.api')
            api.TTS = MagicMock()
            modelo = api.TTS.return_value.to.return_value
            modelo.tts.return_value = np.sin(np.arange(2400) * .1) * .1
            base = pasta / 'revisao_out'
            with patch.dict(sys.modules, {'TTS.api': api}), \
                    patch.object(tts, 'escolher_dispositivo', return_value='cpu'), \
                    patch.object(tts, 'configurar_ffmpeg'), \
                    contextlib.redirect_stdout(io.StringIO()):
                tts.main([str(entrada), '--preset', 'revisao', '--saida', str(base)])
            manifesto = json.loads((pasta / 'revisao_out.blocos.json').read_text())
            self.assertEqual(manifesto['configuracao']['preset'], 'revisao')
            self.assertEqual(manifesto['configuracao']['velocidade'], 1.0)
            self.assertTrue((pasta / 'revisao_out.wav').is_file())
            self.assertTrue((pasta / 'revisao_out.srt').is_file())

            # Flag explícita sobrepõe o preset
            base2 = pasta / 'revisao_custom'
            with patch.dict(sys.modules, {'TTS.api': api}), \
                    patch.object(tts, 'escolher_dispositivo', return_value='cpu'), \
                    patch.object(tts, 'configurar_ffmpeg'), \
                    contextlib.redirect_stdout(io.StringIO()):
                tts.main([str(entrada), '--preset', 'revisao', '--velocidade', '1.25',
                          '--formatos', 'wav', '--saida', str(base2)])
            m2 = json.loads((pasta / 'revisao_custom.blocos.json').read_text())
            self.assertEqual(m2['configuracao']['velocidade'], 1.25)

        cfg = {'velocidade': '1.1', 'formatos': 'mp3,wav', 'lufs': ''}
        cfg_n = tts.aplicar_preset_dict(cfg, 'narracao')
        self.assertEqual(cfg_n['lufs'], '-16.0')
        cfg_r = tts.aplicar_preset_dict(cfg_n, '')
        self.assertEqual(cfg_r['velocidade'], '1.1')
        self.assertEqual(cfg_r['lufs'], '')

    def test_exportacao_por_capitulo_e_loudness_final(self):
        api = types.ModuleType('TTS.api')
        api.TTS = MagicMock()
        modelo = api.TTS.return_value.to.return_value
        modelo.tts.return_value = np.sin(np.arange(12000) * .1) * .2
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            entrada = pasta / 'livro.txt'
            entrada.write_text('# Capítulo Um\n\nPrimeira frase.\n\n# Capítulo Dois\n\nSegunda frase.', encoding='utf-8')
            base = pasta / 'audiolivro'
            with patch.dict(sys.modules, {'TTS.api': api}), \
                    patch.object(tts, 'escolher_dispositivo', return_value='cpu'), \
                    contextlib.redirect_stdout(io.StringIO()):
                tts.main([str(entrada), '--saida', str(base), '--formatos', 'wav,srt',
                          '--por-capitulo', '--titulo', 'Obra Teste', '--autor', 'Autor Teste'])
            manifesto = json.loads((pasta / 'audiolivro.blocos.json').read_text())
            self.assertIn('metricas_finais', manifesto)
            self.assertIn('wav', manifesto['metricas_finais'])
            self.assertGreater(manifesto['metricas_finais']['wav']['duracao_s'], 0)
            self.assertEqual(len(manifesto['capitulos']), 2)
            self.assertEqual(manifesto['capitulos'][0]['titulo'], 'Capítulo Um')
            self.assertEqual(manifesto['capitulos'][1]['titulo'], 'Capítulo Dois')
            self.assertTrue((pasta / 'audiolivro.cap01.wav').is_file())
            self.assertTrue((pasta / 'audiolivro.cap02.wav').is_file())
            self.assertTrue((pasta / 'audiolivro.cap02.srt').is_file())
            srt_cap2 = (pasta / 'audiolivro.cap02.srt').read_text(encoding='utf-8')
            self.assertIn('00:00:00,200 -->', srt_cap2)

    def test_exportacao_audiolivro_m4b_com_capitulos(self):
        api = types.ModuleType('TTS.api')
        api.TTS = MagicMock()
        modelo = api.TTS.return_value.to.return_value
        modelo.tts.return_value = np.sin(np.arange(12000) * .1) * .2
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            entrada = pasta / 'obra.txt'
            entrada.write_text('# Prólogo\n\nTexto do prólogo.\n\n# Desenvolvimento\n\nTexto do desenvolvimento.', encoding='utf-8')
            base = pasta / 'audiolivro_m4b'
            with patch.dict(sys.modules, {'TTS.api': api}), \
                    patch.object(tts, 'escolher_dispositivo', return_value='cpu'), \
                    contextlib.redirect_stdout(io.StringIO()):
                tts.main([str(entrada), '--saida', str(base), '--m4b', '--formatos', 'wav,m4b',
                          '--titulo', 'Obra M4B', '--autor', 'Autor M4B'])
            manifesto = json.loads((pasta / 'audiolivro_m4b.blocos.json').read_text())
            self.assertIn('capitulos_embutidos', manifesto)
            self.assertEqual(len(manifesto['capitulos_embutidos']), 2)
            self.assertEqual(manifesto['capitulos_embutidos'][0]['titulo'], 'Prólogo')
            self.assertEqual(manifesto['capitulos_embutidos'][1]['titulo'], 'Desenvolvimento')
            self.assertTrue((pasta / 'audiolivro_m4b.m4b').is_file())
            self.assertGreater((pasta / 'audiolivro_m4b.m4b').stat().st_size, 100)
            self.assertIn('m4b', manifesto.get('metricas_finais', {}))

    def test_corpus_publico_12_casos_por_idioma_sem_tags_pronunciadas(self):
        corpus = Path(__file__).resolve().parent.parent / 'avaliacao' / 'corpus_pt_es.txt'
        eventos = []
        with contextlib.redirect_stdout(io.StringIO()):
            tts.main([str(corpus), '--saida', 'ignorado', '--analisar'], on_event=eventos.append)
        segs = eventos[0]['segmentos']
        pt = [s for s in segs if s['idioma'] == 'pt']
        es = [s for s in segs if s['idioma'] == 'es']
        self.assertGreaterEqual(len(pt), 12)
        self.assertGreaterEqual(len(es), 12)
        for s in segs:
            self.assertNotIn('[', s['texto'])
            self.assertNotIn(']', s['texto'])
            self.assertNotIn('km/h', s['texto'])
            self.assertNotIn('MB/s', s['texto'])
            self.assertNotIn('°C', s['texto'])
            self.assertNotIn('m²', s['texto'])


if __name__ == '__main__':
    unittest.main()
