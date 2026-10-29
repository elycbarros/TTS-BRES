"""Normalização contextual, localização temporal e validação bilíngue."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from pydub import AudioSegment
from normalizador import normalizar_para_fala
from qualidade_audio import medir_segmento
import validar_audio as va


class TestNumerosContextuais(unittest.TestCase):
    def test_datas_pt_es(self):
        for lang, texto in (('pt', 'vinte e nove de outubro de dois mil e vinte e seis'),
                            ('es', 'veintinueve de octubre de dos mil veintiséis')):
            for entrada in ('29/10/2026', '29-10-2026'):
                self.assertEqual(normalizar_para_fala(entrada, idioma=lang)[0], texto)
        self.assertEqual(normalizar_para_fala('01/02/2024', idioma='pt')[0], 'primeiro de fevereiro de dois mil e vinte e quatro')
        for data in ('31/02/2026', '29/02/2025', '01/13/2026'):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, 'Data inválida'):
                normalizar_para_fala(data, idioma='pt')

    def test_horarios(self):
        casos = [('pt', '10:30', 'dez horas e trinta minutos'),
                 ('pt', '02:01:05', 'duas horas e um minuto e cinco segundos'),
                 ('es', '21:00', 'veintiuna horas'),
                 ('es', '01:01', 'una hora y un minuto'),
                 ('pt', '00:00', 'zero horas')]
        for lang, entrada, esperado in casos:
            self.assertEqual(normalizar_para_fala(entrada, idioma=lang)[0], esperado)
        for entrada in ('24:00', '10:60', '10:30:99'):
            with self.assertRaisesRegex(ValueError, 'Horário inválido'):
                normalizar_para_fala(entrada, idioma='es')

    def test_moedas_negativos_e_pontuacao(self):
        casos = [('pt', 'R$ 12,50.', 'doze reais e cinquenta centavos.'),
                 ('es', 'EUR 21,50.', 'veintiún euros y cincuenta céntimos.'),
                 ('es', 'USD 1,01', 'un dólar estadounidense y un centavo'),
                 ('pt', 'R$ -1.234,05', 'menos mil duzentos e trinta e quatro reais e cinco centavos'),
                 ('pt', '-5 e -0,5%', 'menos cinco e menos zero vírgula cinco por cento')]
        for lang, entrada, esperado in casos:
            with self.subTest(entrada=entrada):
                self.assertEqual(normalizar_para_fala(entrada, idioma=lang)[0], esperado)

    def test_tags_preservadas_e_tokenizacao(self):
        texto, _ = normalizar_para_fala('Em 29/10/2026 [pausa:1.5s] às 10:30.', idioma='pt')
        self.assertIn('[pausa:1.5s]', texto)
        self.assertEqual(va.tokenizar('[Luis|pt]: R$ 12,50 [ENFASE]', 'pt'),
                         va.tokenizar('doze reais e cinquenta centavos', 'pt'))


class TestValidacaoSegmentada(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pasta = Path(self.tmp.name)
        self.wav = self.pasta / 'voz.wav'
        pcm = (np.sin(np.arange(2400) * .1) * 3000).astype('<i2')
        with AudioSegment(pcm.tobytes(), frame_rate=24000, sample_width=2, channels=1).export(str(self.wav), format='wav'):
            pass
        self.manifesto = self.pasta / 'teste.blocos.json'
        self.dados = {'estado': 'concluido', 'segmentos': [
            {'id': 1, 'texto': 'Olá mundo', 'idioma': 'pt', 'arquivo': 'voz.wav', 'inicio_s': .2, 'fim_s': .3},
            {'id': 2, 'texto': 'Hola mundo', 'idioma': 'es', 'arquivo': str(self.wav), 'inicio_s': 1., 'fim_s': 1.1}]}
        self.salvar()

    def salvar(self):
        self.manifesto.write_text(json.dumps(self.dados), encoding='utf-8')

    def test_idiomas_wer_e_tempos(self):
        with patch.object(va, 'transcrever', side_effect=['Olá mundo', 'Hola amigo']) as asr:
            resultado = va.validar_manifesto(self.manifesto)
        self.assertEqual([c.args[1] for c in asr.call_args_list], ['pt', 'es'])
        self.assertEqual(resultado['wer_global'], .25)
        self.assertEqual(resultado['por_idioma']['es']['wer'], .5)
        self.assertFalse(resultado['aprovado'])
        self.assertEqual(resultado['segmentos'][1]['inicio_s'], 1.)

    def test_metricas_sem_transcricao(self):
        with patch.object(va, 'transcrever') as asr:
            resultado = va.validar_manifesto(self.manifesto, somente_metricas=True)
        asr.assert_not_called()
        self.assertIsNone(resultado['aprovado'])
        self.assertIsNone(resultado['wer_global'])
        self.assertAlmostEqual(resultado['segmentos'][0]['metricas']['duracao_s'], .1)

    def test_incompleto_ou_arquivo_ausente_rejeitados_antes_asr(self):
        with patch.object(va, 'transcrever') as asr:
            self.dados['estado'] = 'sintetizando'
            self.salvar()
            with self.assertRaises(ValueError):
                va.validar_manifesto(self.manifesto)
            self.dados['estado'] = 'concluido'
            self.dados['segmentos'][1]['arquivo'] = 'faltando.wav'
            self.salvar()
            with self.assertRaises(ValueError):
                va.validar_manifesto(self.manifesto)
        asr.assert_not_called()

    def test_cli_relatorio_e_codigo_saida(self):
        for somente, saidas, codigo in ((False, ['Olá mundo', 'Hola amigo'], 1), (True, [], 0)):
            argv = ['validar_audio.py', '--manifesto', str(self.manifesto)]
            if somente:
                argv.append('--somente-metricas')
            with patch.object(sys, 'argv', argv), patch.object(va, 'transcrever', side_effect=saidas), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exc:
                va.main()
            self.assertEqual(exc.exception.code, codigo)
            relatorio = json.loads((self.pasta / 'teste.blocos.validacao.json').read_text())
            self.assertEqual(relatorio['somente_metricas'], somente)

    def test_silencio_sem_infinito_no_json(self):
        with AudioSegment.silent(100, frame_rate=24000).export(str(self.wav), format='wav'):
            pass
        resultado = medir_segmento(self.wav)
        self.assertIsNone(resultado['rms_dbfs'])
        self.assertIn('silencio_ou_nivel_muito_baixo', resultado['avisos'])
        json.dumps(resultado, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
