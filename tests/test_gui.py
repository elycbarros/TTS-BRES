"""Contratos da GUI e dos workers; sem dependência de display gráfico."""
import contextlib
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import tts
from gui_core import ProcessoTrabalho, argumentos_sintese, interpretar_linha, salvar_pedido, ROOT


class TestProtocolo(unittest.TestCase):
    def test_eventos_e_logs_malformados(self):
        self.assertEqual(interpretar_linha('TTSBR_EVENT {"tipo":"plano","total":2}\n'), {'tipo': 'plano', 'total': 2})
        self.assertEqual(interpretar_linha('mensagem\n'), {'tipo': 'log', 'texto': 'mensagem'})
        self.assertEqual(interpretar_linha('TTSBR_EVENT []')['tipo'], 'log')
        self.assertEqual(interpretar_linha('TTSBR_EVENT {erro')['tipo'], 'log')

    def test_snapshot_e_argumentos_preservam_espacos(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'saida': str(Path(tmp) / 'áudio final'), 'idioma': 'pt',
                   'locutor': 'Luis Moray', 'refazer': True, 'sem_normalizar': True}
            pedido = salvar_pedido('analisar', 'Olá mundo.', cfg, origem=Path(tmp) / 'roteiro com espaço.txt', pasta=tmp)
            dados = json.loads(pedido.read_text())
            self.assertEqual(Path(dados['entrada']).read_text(), 'Olá mundo.')
            cfg['idioma'] = 'es'
            args = argumentos_sintese(dados)
            self.assertEqual(args[args.index('--locutor') + 1], 'Luis Moray')
            self.assertEqual(args[args.index('--idioma') + 1], 'pt')
            self.assertIn('--analisar', args)
            self.assertIn('--refazer', args)
            self.assertEqual(args[args.index('--saida') + 1], str(Path(tmp) / 'áudio final'))

    def test_worker_real_analisa_sem_gravar_saida(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            origem = p / 'roteiro.txt'
            origem.write_text('Banco Acme.', encoding='utf-8')
            origem.with_name('roteiro.glossario.txt').write_text('Acme = empresa exemplo', encoding='utf-8')
            pedido = salvar_pedido('analisar', '[Luis|pt]: Banco Acme [pausa:800ms] continua.',
                                   {'saida': str(p / 'saidas' / 'narracao'), 'formatos': 'wav'}, origem=origem, pasta=p)
            r = subprocess.run([sys.executable, '-B', str(ROOT / 'gui_worker.py'), str(pedido)],
                               cwd=tmp, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            eventos = [interpretar_linha(l) for l in r.stdout.splitlines()]
            plano = next(e for e in eventos if e['tipo'] == 'plano')
            self.assertIn('empresa exemplo', plano['segmentos'][0]['texto'].lower())
            self.assertEqual(plano['total'], 2)
            self.assertFalse((p / 'saidas').exists())

    def test_worker_real_erro_reportado(self):
        with tempfile.TemporaryDirectory() as tmp:
            pedido = salvar_pedido('analisar', 'Olá [enfaze].', {'saida': str(Path(tmp) / 'audio')}, pasta=tmp)
            r = subprocess.run([sys.executable, '-B', str(ROOT / 'gui_worker.py'), str(pedido)],
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 2)
            eventos = [interpretar_linha(l) for l in r.stdout.splitlines()]
            self.assertTrue(any(e['tipo'] == 'erro' for e in eventos))

    def test_worker_metricas_e_progresso(self):
        from pydub import AudioSegment
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            wav = p / 'segmento.wav'
            with AudioSegment.silent(100, frame_rate=24000).export(str(wav), format='wav'):
                pass
            manifesto = p / 'audio.blocos.json'
            manifesto.write_text(json.dumps({'estado': 'concluido', 'segmentos': [
                {'id': 1, 'idioma': 'pt', 'texto': 'Olá', 'arquivo': str(wav)}]}), encoding='utf-8')
            pedido = salvar_pedido('metricas', '', {}, manifesto=manifesto, pasta=p)
            r = subprocess.run([sys.executable, '-B', str(ROOT / 'gui_worker.py'), str(pedido)],
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            eventos = [interpretar_linha(l) for l in r.stdout.splitlines()]
            self.assertTrue(any(e['tipo'] == 'validacao_segmento' for e in eventos))
            resultado = next(e for e in eventos if e['tipo'] == 'resultado_validacao')
            self.assertIsNone(resultado['aprovado'])
            self.assertEqual(Path(resultado['relatorio']).name, 'audio.blocos.metricas.json')
            self.assertTrue(Path(resultado['relatorio']).exists())

    def test_processo_fila_e_encerramento(self):
        with tempfile.TemporaryDirectory() as tmp:
            pedido = salvar_pedido('analisar', 'Olá mundo.', {'saida': str(Path(tmp) / 'audio')}, pasta=tmp)
            proc = ProcessoTrabalho()
            proc.iniciar(sys.executable, pedido)
            vistos = []
            limite = time.monotonic() + 30
            try:
                while time.monotonic() < limite:
                    e = proc.eventos.get(timeout=5)
                    vistos.append(e)
                    if e['tipo'] == 'processo_encerrado': break
                self.assertEqual(vistos[-1], {'tipo': 'processo_encerrado', 'codigo': 0})
                self.assertTrue(any(e['tipo'] == 'plano' for e in vistos))
                self.assertFalse(proc.ativo)
            finally:
                proc.encerrar()


class TestEventosPipeline(unittest.TestCase):
    def test_interrupcao_persistida_e_retomada(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            origem = p / 'texto.txt'
            origem.write_text('Primeira fala. Segunda fala.', encoding='utf-8')
            api = types.ModuleType('TTS.api')
            api.TTS = MagicMock()
            modelo = api.TTS.return_value.to.return_value
            modelo.tts.return_value = np.sin(np.arange(2400) * .1) * .1
            eventos = []
            def receber(e): eventos.append(e)
            argv = [str(origem), '--saida', str(p / 'audio'), '--formatos', 'wav']
            with patch.dict(sys.modules, {'TTS.api': api}), patch.object(tts, 'escolher_dispositivo', return_value='cpu'), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(tts.SinteseInterrompida):
                    tts.main(argv, on_event=receber, should_stop=lambda: any(e['tipo'] == 'segmento' for e in eventos))
                dados = json.loads((p / 'audio.blocos.json').read_text())
                self.assertEqual(dados['estado'], 'interrompido')
                self.assertEqual(len(dados['segmentos']), 1)
                self.assertTrue(Path(dados['segmentos'][0]['arquivo']).is_file())
                self.assertFalse((p / 'audio.wav').exists())
                modelo.tts.reset_mock()
                retomada = []
                tts.main(argv, on_event=retomada.append)
                self.assertEqual(modelo.tts.call_count, 1)
            self.assertEqual(eventos[0]['tipo'], 'plano')
            self.assertEqual(eventos[0]['total'], 2)
            self.assertEqual(eventos[-1]['tipo'], 'interrompido')
            self.assertEqual(retomada[-1]['tipo'], 'resultado')
            self.assertTrue((p / 'audio.wav').exists())

    def test_analisar_cli_sem_modelo_ou_manifesto(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            entrada = p / 'texto.txt'
            entrada.write_text('A reunião será às 10:30.', encoding='utf-8')
            eventos = []
            with contextlib.redirect_stdout(io.StringIO()), patch.object(tts, 'CacheSegmentos') as cache:
                tts.main([str(entrada), '--saida', str(p / 'saida' / 'audio'), '--analisar'], on_event=eventos.append)
            cache.assert_not_called()
            self.assertFalse((p / 'saida').exists())
            self.assertIn('dez horas e trinta minutos', eventos[0]['segmentos'][0]['texto'])

    def test_servidor_api_openai_compat(self):
        import servidor_api
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            api = types.ModuleType('TTS.api')
            api.TTS = MagicMock()
            modelo = api.TTS.return_value.to.return_value
            modelo.tts.return_value = np.sin(np.arange(2400) * .1) * .1
            motor = servidor_api.MotorAPI(pasta_cache=p / 'cache_api', dispositivo='cpu')
            with patch.dict(sys.modules, {'TTS.api': api}), \
                    patch.object(tts, 'escolher_dispositivo', return_value='cpu'), \
                    patch.object(tts, 'configurar_ffmpeg'):
                wav_bytes, ctype = motor.sintetizar({
                    'model': 'tts-1',
                    'input': 'Olá mundo.',
                    'voice': 'nova',
                    'response_format': 'wav',
                    'speed': 1.0,
                })
                self.assertEqual(ctype, 'audio/wav')
                self.assertTrue(wav_bytes.startswith(b'RIFF'))
                self.assertEqual(modelo.tts.call_count, 1)
                self.assertEqual(modelo.tts.call_args.kwargs['speaker'], 'Alma María')

                # Segunda chamada idêntica reutiliza o cache sem nova inferência
                modelo.tts.reset_mock()
                wav_bytes_2, _ = motor.sintetizar({
                    'model': 'tts-1',
                    'input': 'Olá mundo.',
                    'voice': 'nova',
                    'response_format': 'wav',
                    'speed': 1.0,
                })
                self.assertEqual(modelo.tts.call_count, 0)
                self.assertEqual(wav_bytes, wav_bytes_2)

                with self.assertRaises(ValueError):
                    motor.sintetizar({'input': ''})


if __name__ == '__main__':
    unittest.main()
