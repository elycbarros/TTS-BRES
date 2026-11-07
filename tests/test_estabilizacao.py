"""Regressões de distribuição, caminhos instalados e contratos HTTP reais."""
import http.client
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import caminhos
import servidor_api
import gui_core
import sys


class TestCaminhos(unittest.TestCase):
    def test_home_explicito(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'TTSBR_HOME': tmp}):
            self.assertEqual(caminhos.pasta_dados(), Path(tmp).resolve())

    def test_instalado_nao_grava_nos_modulos(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(caminhos, 'CODIGO', Path(tmp) / 'biblioteca'), \
                patch.dict(os.environ, {'TTSBR_HOME': ''}):
            for plataforma in ('darwin', 'win32', 'linux'):
                with self.subTest(plataforma=plataforma), patch.object(caminhos.sys, 'platform', plataforma):
                    dados = caminhos.pasta_dados()
                    self.assertNotEqual(dados, caminhos.CODIGO)
                    self.assertTrue(dados.is_absolute())

    def test_gui_instalada_prefere_python_do_proprio_ambiente(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(gui_core, 'ROOT', Path(tmp)):
            self.assertEqual(gui_core.python_padrao(), sys.executable)

    def test_recursos_checkout(self):
        self.assertTrue(caminhos.recurso('docs/GUI.md').is_file())
        self.assertTrue(caminhos.recurso('exemplos/captacao_voz_pt.txt').is_file())
        self.assertTrue(caminhos.recurso('exemplos/captacao_voz_es.txt').is_file())

    def test_construcao_limpa_sem_appledouble_e_com_roteiros_captacao(self):
        import subprocess
        import tarfile
        import zipfile
        from scripts.construir import construir
        with tempfile.TemporaryDirectory(prefix='ttsbr dist espaço á-') as tmp:
            saida = Path(tmp) / 'dist'
            construir(saida)
            wheels = list(saida.glob('ttsbr-1.1.0-*.whl'))
            sdists = list(saida.glob('ttsbr-1.1.0.tar.gz'))
            self.assertEqual(len(wheels), 1)
            self.assertEqual(len(sdists), 1)
            with zipfile.ZipFile(wheels[0]) as zf:
                nomes = zf.namelist()
            self.assertFalse(any(Path(n).name.startswith('._') for n in nomes))
            self.assertFalse(any(n.startswith(('local/', 'work/', 'saida/')) for n in nomes))
            for esperado in ('exemplos/captacao_voz_pt.txt', 'exemplos/captacao_voz_es.txt',
                             'docs/MOTORES_E4.md', 'comparar_motores_e4.py'):
                self.assertTrue(any(n.endswith(esperado) for n in nomes), esperado)
            with tarfile.open(sdists[0], 'r:gz') as tf:
                nomes_tar = tf.getnames()
            self.assertFalse(any(Path(n).name.startswith('._') for n in nomes_tar))

            # Instala o wheel fora do checkout em caminho com espaço e acento e exercita 3 comandos
            alvo_site = Path(tmp) / 'instalação com espaço'
            alvo_site.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(wheels[0]) as zf:
                zf.extractall(alvo_site)
            dados_home = Path(tmp) / 'dados com acento á'
            env = {**os.environ, 'PYTHONPATH': str(alvo_site), 'TTSBR_HOME': str(dados_home)}
            for cmd in (
                [sys.executable, '-m', 'diagnostico'],
                [sys.executable, '-m', 'biblioteca_vozes', 'listar'],
                [sys.executable, '-m', 'tarefas', 'listar'],
            ):
                r = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((dados_home / 'local' / 'vozes').is_dir())
            self.assertTrue((dados_home / 'local' / 'fila').is_dir())
            self.assertFalse((alvo_site / 'local').exists())


class TestAPIHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = servidor_api.criar_servidor('127.0.0.1', 0, self.tmp.name, 'cpu', usar_fila=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.fechar)

    def fechar(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, payload=None, bruto=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            corpo = bruto if bruto is not None else json.dumps(payload).encode('utf-8') if payload is not None else None
            conn.request(method, path, body=corpo, headers={'Content-Type': 'application/json'})
            resposta = conn.getresponse()
            return resposta.status, resposta.getheader('Content-Type'), resposta.read()
        finally:
            conn.close()

    def test_rotas_de_consulta(self):
        for rota, campo in (('/health', 'status'), ('/v1/models', 'data'), ('/v1/voices', 'voices')):
            with self.subTest(rota=rota):
                status, _, corpo = self.request('GET', rota)
                self.assertEqual(status, 200)
                self.assertIn(campo, json.loads(corpo))
        self.assertEqual(self.request('GET', '/inexistente')[0], 404)

    def test_entradas_invalidas_retornam_400_sem_modelo(self):
        casos = [[], {}, {'input': ' '}, {'input': 123}, {'input': 'Olá', 'speed': None},
                 {'input': 'Olá', 'speed': []}, {'input': 'Olá', 'speed': True},
                 {'input': 'Olá', 'speed': float('nan')}, {'input': 'Olá', 'speed': 0},
                 {'input': 'Olá', 'language': 'fr'}, {'input': 'Olá', 'response_format': 'exe'},
                 {'input': 'Olá', 'limpar_referencia': 'false'}]
        with patch('servidor_api.tts.main') as motor:
            for payload in casos:
                with self.subTest(payload=payload):
                    status, _, corpo = self.request('POST', '/v1/audio/speech', payload)
                    self.assertEqual(status, 400, corpo)
            motor.assert_not_called()
        self.assertEqual(self.request('POST', '/v1/audio/speech', bruto=b'{invalido')[0], 400)
        self.assertEqual(self.request('POST', '/inexistente', {})[0], 404)

    def test_resposta_arquivo_e_isolamento_de_erros(self):
        def simular(argv):
            base = Path(argv[argv.index('--saida') + 1])
            formato = argv[argv.index('--formatos') + 1]
            (base.parent / (base.name + '.' + formato)).write_bytes(b'audio-de-teste')
        with patch('servidor_api.tts.main', side_effect=simular):
            for _ in range(2):
                status, mime, corpo = self.request('POST', '/v1/audio/speech', {'input': 'Olá', 'response_format': 'wav'})
                self.assertEqual((status, mime, corpo), (200, 'audio/wav', b'audio-de-teste'))
        with patch('servidor_api.tts.main', side_effect=RuntimeError('erro simulado')):
            self.assertEqual(self.request('POST', '/v1/audio/speech', {'input': 'Olá'})[0], 500)
        self.assertEqual(self.request('GET', '/health')[0], 200)

    def test_streaming_wav_e_pcm_com_pausa_e_desconexao(self):
        import wave
        with tempfile.TemporaryDirectory() as td:
            wav1 = Path(td) / "seg1.wav"
            wav2 = Path(td) / "seg2.wav"
            with wave.open(str(wav1), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                w.writeframes(b"\x10\x00" * 240)  # 10ms
            with wave.open(str(wav2), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                w.writeframes(b"\x20\x00" * 480)  # 20ms

            def simular_sintese_streaming(argv, on_event=None, should_stop=None, **kwargs):
                if on_event:
                    on_event({"tipo": "segmento", "segmento": {"arquivo": str(wav1)}})
                    if should_stop and should_stop():
                        return
                    on_event({"tipo": "pausa", "duracao_ms": 10})
                    if should_stop and should_stop():
                        return
                    on_event({"tipo": "segmento", "segmento": {"arquivo": str(wav2)}})

            with patch('servidor_api.tts.main', side_effect=simular_sintese_streaming):
                # 1) Stream WAV
                status, mime, corpo = self.request(
                    'POST', '/v1/audio/speech',
                    {'input': 'Primeira frase. Segunda frase.', 'stream': True, 'response_format': 'wav'}
                )
                self.assertEqual(status, 200)
                self.assertEqual(mime, 'audio/wav')
                self.assertGreater(len(corpo), 44)
                with wave.open(io.BytesIO(corpo), 'rb') as w:
                    self.assertEqual(w.getnchannels(), 1)
                    self.assertEqual(w.getsampwidth(), 2)
                    self.assertEqual(w.getframerate(), 24000)
                    frames = w.readframes(w.getnframes())
                    self.assertGreater(len(frames), 0)

                # 2) Stream PCM
                status, mime, corpo_pcm = self.request(
                    'POST', '/v1/audio/speech',
                    {'input': 'Primeira frase. Segunda frase.', 'stream': True, 'response_format': 'pcm'}
                )
                self.assertEqual(status, 200)
                self.assertEqual(mime, 'audio/pcm')
                # 240 amostras + 240 silêncio + 480 amostras = 960 amostras * 2 bytes = 1920 bytes
                self.assertEqual(len(corpo_pcm), 1920)

                # 3) Stream ativado via query param ?stream=1
                status, mime, corpo_query = self.request(
                    'POST', '/v1/audio/speech?stream=1',
                    {'input': 'Testando via query.'}
                )
                self.assertEqual(status, 200)
                self.assertEqual(mime, 'audio/wav')

                # 4) Rejeição de formato inválido para streaming
                status, _, corpo_invalido = self.request(
                    'POST', '/v1/audio/speech',
                    {'input': 'Teste', 'stream': True, 'response_format': 'mp3'}
                )
                self.assertEqual(status, 400)
                self.assertIn(b"Formato de streaming", corpo_invalido)

                # 5) Desconexão antecipada do cliente no socket
                conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
                try:
                    payload = json.dumps({'input': 'Texto longo.', 'stream': True}).encode('utf-8')
                    conn.request('POST', '/v1/audio/speech', body=payload, headers={'Content-Type': 'application/json'})
                    resp = conn.getresponse()
                    self.assertEqual(resp.status, 200)
                    _primeiro_bloco = resp.read(44)  # lê apenas o cabeçalho e fecha bruscamente
                    conn.close()
                finally:
                    pass

                # Requisição seguinte responde normalmente com 200
                status_depois, _, _ = self.request('GET', '/health')
                self.assertEqual(status_depois, 200)
                status_depois_post, _, corpo_pos = self.request(
                    'POST', '/v1/audio/speech',
                    {'input': 'Nova requisicao.', 'response_format': 'wav', 'stream': True}
                )
                self.assertEqual(status_depois_post, 200)
                self.assertGreater(len(corpo_pos), 44)


if __name__ == '__main__':
    unittest.main()
