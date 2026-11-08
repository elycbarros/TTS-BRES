"""Worker persistente (quente) para XTTS v2 no TTSBR.

Mantém o modelo de voz instanciado na memória (MPS, CUDA ou CPU) entre
múltiplas gerações consecutivas, eliminando os ~35s de recarga fria do PyTorch/Coqui.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback
from typing import Any, Callable

from caminhos import pasta_dados
from exclusao import Trava, RecursoOcupado
from gui_core import PREFIXO_EVENTO, argumentos_sintese


def carregar_modelo_tts(dispositivo_pedido: str = "auto"):
    """Instancia o modelo XTTS v2 no dispositivo solicitado (mps, cuda ou cpu)."""
    from TTS.api import TTS
    from processamento_audio import escolher_dispositivo

    disp = escolher_dispositivo(dispositivo_pedido)
    inicio = time.monotonic()
    print(f"[WorkerQuente] Carregando modelo XTTS v2 em '{disp}'…", flush=True)
    modelo = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(disp)
    tempo = time.monotonic() - inicio
    print(f"[WorkerQuente] Modelo carregado com sucesso em {tempo:.2f}s ({disp}).", flush=True)
    return modelo, disp


def descarregar_modelo_tts(modelo: Any = None) -> None:
    """Libera tensores da memória VRAM/RAM (MPS / CUDA / CPU) e executa gc."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
            torch.mps.empty_cache()
    except Exception:
        pass
    gc.collect()
    print("[WorkerQuente] Memória do modelo liberada.", flush=True)


class WorkerQuente:
    """Gerencia a persistência do modelo XTTS v2 em memória para execuções consecutivas."""

    def __init__(
        self,
        raiz_fila: Path | str | None = None,
        dispositivo: str = "auto",
        ocioso: float = 300.0,
        on_event: Callable[[dict], None] | None = None,
    ):
        self.raiz_fila = Path(raiz_fila or (pasta_dados() / "local" / "fila")).resolve()
        self.dispositivo = dispositivo
        self.ocioso = float(ocioso)
        self.on_event = on_event
        self._modelo: Any = None
        self._dispositivo_ativo: str | None = None
        self._tempo_carga_s: float = 0.0

    @property
    def esta_quente(self) -> bool:
        return self._modelo is not None

    def obter_modelo(self):
        """Retorna o modelo carregado na memória, instanciando-o sob demanda se necessário."""
        if self._modelo is None:
            inicio = time.monotonic()
            self._modelo, self._dispositivo_ativo = carregar_modelo_tts(self.dispositivo)
            self._tempo_carga_s = time.monotonic() - inicio
        return self._modelo

    def descarregar(self) -> None:
        """Descarta a referência do modelo e limpa a memória."""
        if self._modelo is not None:
            self._modelo = None
            self._dispositivo_ativo = None
            descarregar_modelo_tts()

    def executar_pedido(
        self,
        caminho_pedido: Path | str,
        on_event: Callable[[dict], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        tarefa_id: str | None = None,
        tentativa: int | None = None,
        fila: Any = None,
    ) -> dict[str, Any]:
        """Executa um pedido de síntese ou análise aproveitando o modelo já carregado."""
        from contextlib import nullcontext
        from exclusao import recursos
        from vozes import REFERENCIAS_CONGELADAS

        caminho = Path(caminho_pedido).resolve()
        pedido = json.loads(caminho.read_text(encoding="utf-8"))
        cfg = pedido["configuracao"]
        resultados: dict[str, Any] = {}

        def emitir_evento(evento: dict) -> None:
            if evento.get("tipo") in (
                "plano", "resultado", "resultado_validacao",
                "interrompido", "tomada_registrada", "erro"
            ):
                resultados[evento["tipo"]] = evento

            if on_event:
                try:
                    on_event(evento)
                except Exception:
                    pass
            elif self.on_event:
                try:
                    self.on_event(evento)
                except Exception:
                    pass
            else:
                try:
                    print("\n" + PREFIXO_EVENTO + json.dumps(evento, ensure_ascii=False), flush=True)
                except BrokenPipeError:
                    pass

            if fila and tarefa_id:
                try:
                    fila.evento(tarefa_id, evento)
                except Exception:
                    pass

        token = REFERENCIAS_CONGELADAS.set(pedido.get("_referencias_congeladas", {}))
        base = Path(cfg.get("saida") or "audio")
        cache = cfg.get("cache_segmentos") or str(base.parent / (base.name + ".segmentos"))

        codigo_erro = 0
        try:
            with recursos(base, cache) if pedido["modo"] in ("gerar", "amostra") else nullcontext():
                self._executar_interno(caminho, pedido, emitir_evento, should_stop=should_stop)
        except SystemExit as exc:
            codigo_erro = int(exc.code or 0)
            if codigo_erro:
                emitir_evento({"tipo": "erro", "mensagem": "Confira os parâmetros e o registro."})
        except Exception as exc:
            codigo_erro = 1
            try:
                traceback.print_exc()
            except OSError:
                pass
            emitir_evento({"tipo": "erro", "mensagem": str(exc)})
        finally:
            REFERENCIAS_CONGELADAS.reset(token)

        if fila and tarefa_id and tentativa is not None:
            estado = (
                "falha" if codigo_erro
                else "interrompida" if "interrompido" in resultados
                else "concluida"
            )
            try:
                fila.gravar_recibo(tarefa_id, tentativa, estado, resultados)
            except Exception as exc:
                print(f"[WorkerQuente] Erro ao gravar recibo da tarefa {tarefa_id}: {exc}", file=sys.stderr)

        return resultados

    def _executar_interno(
        self,
        caminho: Path,
        pedido: dict,
        emitir: Callable[[dict], None],
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        modo = pedido["modo"]
        if modo == "biblioteca_importar":
            from biblioteca_vozes import BibliotecaVozes
            cfg = pedido["configuracao"]
            perfil = BibliotecaVozes(cfg["raiz"]).importar(
                cfg["arquivo"], cfg["nome"], cfg["idioma"], cfg["estilo"],
                cfg.get("transcricao", ""), cfg.get("autorizacao", False), cfg.get("limpar", False)
            )
            emitir({"tipo": "perfil_importado", "id": perfil["documento"]["id"]})
            return

        if modo not in ("analisar", "gerar", "amostra", "validar", "metricas"):
            raise ValueError(f"Modo de trabalho inválido: {modo}")

        if modo in ("validar", "metricas"):
            from audio_persistente import salvar_json
            from validar_audio import validar_manifesto
            emitir({"tipo": "etapa", "etapa": "validacao", "mensagem": "Analisando os segmentos…"})
            relatorio = validar_manifesto(pedido["manifesto"], somente_metricas=(modo == "metricas"), on_event=emitir)
            origem = Path(pedido["manifesto"])
            destino = origem.with_name(origem.stem + (".metricas.json" if modo == "metricas" else ".validacao.json"))
            salvar_json(destino, relatorio)
            emitir({
                "tipo": "resultado_validacao",
                "relatorio": str(destino),
                "aprovado": relatorio["aprovado"],
                "wer_global": relatorio["wer_global"],
            })
            return

        from normalizador import carregar_glossario
        from tts import main, SinteseInterrompida

        cfg = pedido["configuracao"]
        cfg["glossario"] = str(Path(cfg["glossario"]).resolve()) if cfg.get("glossario") else None
        glossario = (
            cfg["glossario_integrado"]
            if "glossario_integrado" in cfg
            else carregar_glossario(cfg.get("glossario"), texto_path=pedido.get("origem") or pedido["entrada"])
        )
        g_path = caminho.parent / "glossario_snapshot.json"
        g_path.write_text(json.dumps(glossario, ensure_ascii=False), encoding="utf-8")
        cfg["glossario"] = str(g_path)

        def verificar_parada():
            if (caminho.parent / "interromper.flag").exists():
                return True
            if should_stop and should_stop():
                return True
            return False

        # No modo analisar não é necessário carregar o modelo de áudio
        modelo = None if modo == "analisar" else self.obter_modelo()

        try:
            main(
                argumentos_sintese(pedido),
                on_event=emitir,
                origem_referencias=pedido.get("origem"),
                glossario_precarregado=glossario,
                modelo_precarregado=modelo,
                should_stop=verificar_parada,
            )
            if cfg.get("_projeto") and modo == "gerar":
                emitir({"tipo": "etapa", "etapa": "registro", "mensagem": "Preservando a tomada no projeto…"})
                from projetos import Projeto
                projeto = Projeto.abrir(cfg["_projeto"])
                base = Path(cfg["saida"])
                arquivos = [str(base.parent / f"{base.name}.{ext}") for ext in cfg.get("formatos", "mp3,wav").split(",")]
                snapshot = pedido.get("_snapshot_projeto", {})
                registro = projeto.registrar_tomada(
                    base.parent / f"{base.name}.blocos.json",
                    arquivos,
                    proveniencia={
                        "tarefa_id": os.environ.get("TTSBR_FILA_ID"),
                        "revisao_origem": snapshot.get("dados", {}).get("configuracao", {}).get("_estudio", {}).get("revisao"),
                    },
                )
                emitir({"tipo": "tomada_registrada", "id": registro["id"]})
        except SinteseInterrompida:
            return

    def rodar_loop(self, timeout_ocioso: float | None = None, parar_evento: Any = None) -> int:
        """Consome tarefas da Fila mantendo o modelo residente na memória."""
        from contextlib import closing
        from tarefas import Fila

        timeout = self.ocioso if timeout_ocioso is None else float(timeout_ocioso)
        fila = Fila(self.raiz_fila)

        limite_inicio = time.monotonic() + 1
        coordenador = None
        while True:
            try:
                coordenador = Trava(fila.raiz / "coordenador.lock").adquirir()
                break
            except RecursoOcupado:
                if time.monotonic() >= limite_inicio:
                    print("[WorkerQuente] Outro coordenador já está ativo.", flush=True)
                    return 0
                time.sleep(0.05)

        print(f"[WorkerQuente] Coordenador quente ativo na fila '{fila.raiz}'. Timeout ocioso: {timeout}s.", flush=True)
        try:
            sem_trabalho = time.monotonic()
            while True:
                if parar_evento and parar_evento.is_set():
                    print("[WorkerQuente] Sinal de parada recebido.", flush=True)
                    break

                try:
                    recurso = Trava(fila.raiz / "recurso.lock").adquirir()
                except RecursoOcupado:
                    time.sleep(0.1)
                    continue

                try:
                    fila.recuperar()
                    fila.reconciliar_vinculos()
                    with closing(fila.conectar()) as db:
                        row = db.execute(
                            "SELECT id FROM tarefas WHERE estado='aguardando' ORDER BY criada LIMIT 1"
                        ).fetchone()

                    if row is None:
                        if timeout > 0 and (time.monotonic() - sem_trabalho >= timeout):
                            print(f"[WorkerQuente] Limite de ociosidade ({timeout}s) atingido. Encerrando.", flush=True)
                            break
                    else:
                        sem_trabalho = time.monotonic()
                        tarefa_id = row[0]
                        try:
                            tarefa = fila.preparar(tarefa_id)
                            if tarefa:
                                print(f"[WorkerQuente] Processando tarefa {tarefa_id} (tentativa {tarefa['tentativa']})…", flush=True)
                                self._executar_tarefa_fila(fila, tarefa)
                        except Exception as exc:
                            print(f"[WorkerQuente] Falha ao preparar/executar tarefa {tarefa_id}: {exc}", file=sys.stderr)
                            with closing(fila.conectar()) as db, db:
                                db.execute(
                                    "UPDATE tarefas SET estado='falha', erro=?, atualizada=? WHERE id=?",
                                    (str(exc), time.time(), tarefa_id),
                                )
                            fila._liberar_perfil(tarefa_id)
                finally:
                    recurso.fechar()

                fila.limpar_historico()
                time.sleep(0.05)
        finally:
            self.descarregar()
            if coordenador:
                coordenador.fechar()

        return 0

    def _executar_tarefa_fila(self, fila: Any, tarefa: dict) -> None:
        """Executa a tarefa da fila sob o ambiente da tentativa."""
        pedido_tentativa = Path(tarefa["pedido_tentativa"])
        ambiente_anterior = os.environ.copy()
        os.environ.update(
            TTSBR_HOME=tarefa["dados_raiz"],
            TTSBR_FILA_RAIZ=str(fila.raiz),
            TTSBR_FILA_ID=tarefa["id"],
            TTSBR_FILA_TENTATIVA=str(tarefa["tentativa"]),
        )
        try:
            (pedido_tentativa.parent / "iniciar.flag").touch()
            self.executar_pedido(
                pedido_tentativa,
                tarefa_id=tarefa["id"],
                tentativa=tarefa["tentativa"],
                fila=fila,
                should_stop=lambda: bool(fila.obter(tarefa["id"]).get("solicitacao")),
            )
            fila.concluir_por_recibo(tarefa)
        finally:
            os.environ.clear()
            os.environ.update(ambiente_anterior)

    def rodar_ipc(self) -> int:
        """Protocolo IPC via stdin/stdout: permite a outros processos despachar pedidos por linha."""
        print(PREFIXO_EVENTO + json.dumps({"tipo": "ipc_pronto", "quente": self.esta_quente}), flush=True)
        for linha in sys.stdin:
            linha = linha.strip()
            if not linha:
                continue
            try:
                comando = json.loads(linha)
            except Exception as exc:
                print(PREFIXO_EVENTO + json.dumps({"tipo": "ipc_erro", "erro": f"JSON inválido: {exc}"}), flush=True)
                continue

            acao = comando.get("comando")
            if acao == "ping":
                print(PREFIXO_EVENTO + json.dumps({"tipo": "ipc_pong", "quente": self.esta_quente}), flush=True)
            elif acao == "aquecer":
                inicio = time.monotonic()
                self.obter_modelo()
                tempo = time.monotonic() - inicio
                print(PREFIXO_EVENTO + json.dumps({
                    "tipo": "ipc_aquecido",
                    "dispositivo": self._dispositivo_ativo,
                    "tempo_s": round(tempo, 2),
                }), flush=True)
            elif acao == "descarregar":
                self.descarregar()
                print(PREFIXO_EVENTO + json.dumps({"tipo": "ipc_descarregado"}), flush=True)
            elif acao == "executar":
                pedido_path = comando.get("pedido")
                if not pedido_path or not Path(pedido_path).exists():
                    print(PREFIXO_EVENTO + json.dumps({"tipo": "ipc_erro", "erro": "Pedido não encontrado"}), flush=True)
                    continue
                resultados = self.executar_pedido(
                    pedido_path,
                    tarefa_id=comando.get("tarefa_id"),
                    tentativa=comando.get("tentativa"),
                )
                print(PREFIXO_EVENTO + json.dumps({"tipo": "ipc_concluido", "resultados": resultados}), flush=True)
            elif acao == "parar":
                print(PREFIXO_EVENTO + json.dumps({"tipo": "ipc_parando"}), flush=True)
                break
            else:
                print(PREFIXO_EVENTO + json.dumps({"tipo": "ipc_erro", "erro": f"Comando desconhecido: {acao}"}), flush=True)

        self.descarregar()
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fila", type=Path, help="Caminho raiz da fila SQLite")
    parser.add_argument("--dispositivo", default="auto", choices=("auto", "mps", "cuda", "cpu"))
    parser.add_argument("--ocioso", type=float, default=300.0, help="Tempo limite ocioso em segundos antes de descarregar")
    parser.add_argument("--aquecer", action="store_true", help="Pré-carrega o modelo XTTS v2 imediatamente")
    parser.add_argument("--ipc", action="store_true", help="Inicia em modo servidor IPC via stdin/stdout")
    parser.add_argument("--pedido", type=Path, help="Executa um pedido.json específico")
    args = parser.parse_args(argv)

    worker = WorkerQuente(raiz_fila=args.fila, dispositivo=args.dispositivo, ocioso=args.ocioso)

    if args.aquecer:
        worker.obter_modelo()

    if args.pedido:
        worker.executar_pedido(args.pedido)
        return 0

    if args.ipc:
        return worker.rodar_ipc()

    return worker.rodar_loop()


if __name__ == "__main__":
    sys.exit(main())
