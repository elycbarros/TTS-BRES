"""Testes automatizados para o Worker Persistente (Quente) do TTSBR."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from audio_persistente import salvar_json
from gui_core import salvar_pedido
from tarefas import Fila, TERMINAIS
from worker_quente import WorkerQuente, carregar_modelo_tts, descarregar_modelo_tts


class TestWorkerQuente(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name).resolve()
        self.fila_raiz = self.raiz / "fila"
        self.fila = Fila(self.fila_raiz)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ciclo_vida_e_propriedade_esta_quente(self):
        worker = WorkerQuente(raiz_fila=self.fila_raiz, dispositivo="cpu")
        self.assertFalse(worker.esta_quente)

        modelo_mock = MagicMock()
        with patch("worker_quente.carregar_modelo_tts", return_value=(modelo_mock, "cpu")):
            modelo_obtido = worker.obter_modelo()
            self.assertIs(modelo_obtido, modelo_mock)
            self.assertTrue(worker.esta_quente)

            # Segunda chamada deve retornar exatamente a mesma instância sem recarregar
            segunda_chamada = worker.obter_modelo()
            self.assertIs(segunda_chamada, modelo_mock)

            # Descarregando deve limpar e voltar a esta_quente=False
            worker.descarregar()
            self.assertFalse(worker.esta_quente)
            self.assertIsNone(worker._modelo)

    def test_reutilizacao_de_modelo_entre_duas_tarefas_consecutivas(self):
        worker = WorkerQuente(raiz_fila=self.fila_raiz, dispositivo="cpu")
        modelo_fake = MagicMock(name="InstanciaModeloXTTS")
        worker._modelo = modelo_fake

        modelos_recebidos = []

        def fake_main(argv=None, on_event=None, should_stop=None, modelo_precarregado=None, **kwargs):
            modelos_recebidos.append(modelo_precarregado)
            if on_event:
                on_event({"tipo": "etapa", "etapa": "sintese", "mensagem": "síntese teste"})
                on_event({"tipo": "resultado", "manifesto": "teste.json", "arquivos": ["teste.mp3"]})
            return {"modelo": modelo_precarregado}

        cfg = {"saida": str(self.raiz / "audio1"), "formatos": "wav"}
        pedido1 = salvar_pedido("gerar", "Texto 1", cfg, pasta=self.raiz / "p1")
        cfg["saida"] = str(self.raiz / "audio2")
        pedido2 = salvar_pedido("gerar", "Texto 2", cfg, pasta=self.raiz / "p2")

        with patch("tts.main", side_effect=fake_main):
            worker.executar_pedido(pedido1)
            worker.executar_pedido(pedido2)

        self.assertEqual(len(modelos_recebidos), 2)
        # Confirma que a MESMA instância do modelo quente foi reutilizada
        self.assertIs(modelos_recebidos[0], modelo_fake)
        self.assertIs(modelos_recebidos[1], modelo_fake)
        self.assertIs(modelos_recebidos[0], modelos_recebidos[1])

    def test_execucao_com_recibo_na_fila(self):
        worker = WorkerQuente(raiz_fila=self.fila_raiz, dispositivo="cpu")
        modelo_fake = MagicMock()
        worker._modelo = modelo_fake

        cfg = {"saida": str(self.raiz / "saida_fila" / "audio"), "formatos": "wav"}
        pedido_path = salvar_pedido("gerar", "Frase para teste de fila.", cfg, pasta=self.raiz / "pedidos")

        tarefa_id = self.fila.enfileirar(sys.executable, pedido_path)
        tarefa = self.fila.preparar(tarefa_id)

        saida_base = Path(cfg["saida"])
        saida_base.parent.mkdir(parents=True, exist_ok=True)
        wav_arquivo = saida_base.parent / (saida_base.name + ".wav")
        wav_arquivo.write_bytes(b"RIFF44WAVEfmt ")
        manifesto_arquivo = saida_base.parent / (saida_base.name + ".blocos.json")
        salvar_json(manifesto_arquivo, {
            "estado": "concluido",
            "segmentos": [{"id": 1, "arquivo": str(wav_arquivo)}],
        })

        eventos_emitidos = []

        def fake_main(argv=None, on_event=None, should_stop=None, modelo_precarregado=None, **kwargs):
            if on_event:
                on_event({"tipo": "etapa", "etapa": "sintese", "mensagem": "gerando áudio"})
                on_event({
                    "tipo": "resultado",
                    "manifesto": str(manifesto_arquivo),
                    "arquivos": [str(wav_arquivo)],
                })
            return {"modelo": modelo_precarregado}

        with patch("tts.main", side_effect=fake_main):
            worker._executar_tarefa_fila(self.fila, tarefa)

        tarefa_atualizada = self.fila.obter(tarefa_id)
        self.assertEqual(tarefa_atualizada["estado"], "concluida")

        # Verifica se os eventos foram gravados na fila
        eventos = self.fila.eventos_desde(tarefa_id)
        tipos_eventos = [ev["tipo"] for _, ev in eventos]
        self.assertIn("etapa", tipos_eventos)
        self.assertIn("resultado", tipos_eventos)

    def test_servidor_api_reutiliza_modelo_quente(self):
        from servidor_api import MotorAPI

        motor = MotorAPI(pasta_cache=self.raiz / "api_cache", dispositivo="cpu", usar_fila=False)
        self.assertIsNone(motor.modelo_precarregado)

        modelo_fake = MagicMock(name="ModeloAPIQuente")
        with patch("worker_quente.carregar_modelo_tts", return_value=(modelo_fake, "cpu")):
            # Primeira chamada carrega
            m1 = motor.obter_modelo()
            self.assertIs(m1, modelo_fake)
            self.assertIs(motor.modelo_precarregado, modelo_fake)

            # Segunda chamada retorna sem recarregar
            m2 = motor.obter_modelo()
            self.assertIs(m2, modelo_fake)

            motor.descarregar_modelo()
            self.assertIsNone(motor.modelo_precarregado)

    def test_protocolo_ipc_ping_aquecer_descarregar(self):
        worker = WorkerQuente(raiz_fila=self.fila_raiz, dispositivo="cpu")
        modelo_fake = MagicMock()

        comandos = [
            json.dumps({"comando": "ping"}),
            json.dumps({"comando": "aquecer"}),
            json.dumps({"comando": "descarregar"}),
            json.dumps({"comando": "parar"}),
        ]
        entrada_simulada = "\n".join(comandos) + "\n"

        saida_capturada = io.StringIO()
        with patch("sys.stdin", io.StringIO(entrada_simulada)), \
             patch("sys.stdout", saida_capturada), \
             patch("worker_quente.carregar_modelo_tts", return_value=(modelo_fake, "cpu")):
            codigo = worker.rodar_ipc()
            self.assertEqual(codigo, 0)

        linhas = saida_capturada.getvalue().splitlines()
        eventos = [json.loads(l.replace("TTSBR_EVENT ", "")) for l in linhas if "TTSBR_EVENT " in l]
        tipos = [e.get("tipo") for e in eventos]

        self.assertIn("ipc_pronto", tipos)
        self.assertIn("ipc_pong", tipos)
        self.assertIn("ipc_aquecido", tipos)
        self.assertIn("ipc_descarregado", tipos)
        self.assertIn("ipc_parando", tipos)


if __name__ == "__main__":
    unittest.main()
