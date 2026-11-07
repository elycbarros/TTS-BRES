#!/usr/bin/env python3
"""Servidor HTTP local compatível com o endpoint OpenAI TTS (/v1/audio/speech).

Permite integrar o TTSBR como backend local em ferramentas como Obsidian,
Open-WebUI, leitores de tela e agentes locais sem dependências web externas.

Uso:
    python servidor_api.py --porta 8000
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
from pathlib import Path
import queue
import struct
import sys
import tempfile
import threading
import time
from typing import Any, Generator
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tts
from caminhos import pasta_dados

OPENAI_VOICE_MAP = {
    "alloy": None,  # automático pelo idioma detectado
    "auto": None,
    "onyx": "Luis Moray",
    "echo": "Luis Moray",
    "fable": "Marcos Rudaski",
    "nova": "Alma María",
    "shimmer": "Ana Florence",
    "iapetus": "Xavier Hayasaka",
}

CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "pcm": "audio/pcm",
    "raw": "audio/pcm",
}


def cabecalho_wav_streaming(sample_rate: int = 24000, canais: int = 1, bits: int = 16) -> bytes:
    """Gera cabeçalho WAV padrão de 44 bytes para streaming contínuo."""
    byte_rate = sample_rate * canais * (bits // 8)
    block_align = canais * (bits // 8)
    data_size = 0x7FFFFFFF
    riff_size = data_size + 36
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        canais,
        sample_rate,
        byte_rate,
        block_align,
        bits,
        b"data",
        data_size,
    )


def resolver_voz_openai(voice: str | None) -> tuple[str | None, str | None]:
    """Retorna (locutor, caminho_voz) a partir do campo 'voice' da requisição."""
    if not voice or not str(voice).strip():
        return None, None
    v = str(voice).strip()
    chave = v.lower()
    if chave in OPENAI_VOICE_MAP:
        return OPENAI_VOICE_MAP[chave], None
    if tts.eh_caminho_audio(v):
        return None, tts.resolver_caminho_voz(v)
    try:
        from biblioteca_vozes import BibliotecaVozes
        caminho_perfil = BibliotecaVozes().resolver(v)
        return None, str(caminho_perfil)
    except Exception:
        pass
    return tts.resolver_locutor(v, "pt", v), None


class MotorAPI:
    """Gerencia a execução thread-safe e o cache persistente de segmentos do servidor."""

    def __init__(self, pasta_cache: Path | str | None = None, dispositivo: str = "auto",
                 usar_fila=True, fila=None):
        self.pasta_cache = Path(pasta_cache or (pasta_dados() / "saida" / "api_cache"))
        self.pasta_cache.mkdir(parents=True, exist_ok=True)
        self.dispositivo = dispositivo
        self.lock = threading.Lock()
        self.usar_fila = usar_fila
        self.fila = fila

    def sintetizar(self, dados: dict) -> tuple[bytes, str]:
        if not isinstance(dados, dict):
            raise ValueError("O corpo da requisição deve ser um objeto JSON.")
        if not isinstance(dados.get("input"), str):
            raise ValueError("O campo 'input' deve ser uma string.")
        texto = dados["input"].strip()
        if not texto:
            raise ValueError("O campo 'input' é obrigatório e não pode ser vazio.")
        formato = str(dados.get("response_format") or "mp3").strip().lower()
        if formato not in CONTENT_TYPES:
            raise ValueError(f"Formato inválido ({formato!r}); use mp3, wav, srt, vtt, pcm ou raw.")
        valor_velocidade = dados.get("speed", 1.1)
        if isinstance(valor_velocidade, bool):
            raise ValueError("O campo 'speed' deve ser numérico.")
        try:
            velocidade = float(valor_velocidade)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("O campo 'speed' deve ser numérico.") from exc
        if "limpar_referencia" in dados and not isinstance(dados["limpar_referencia"], bool):
            raise ValueError("O campo 'limpar_referencia' deve ser booleano.")
        if not math.isfinite(velocidade) or not (0.25 <= velocidade <= 4.0):
            raise ValueError("O campo 'speed' deve estar entre 0.25 e 4.0.")
        idioma = str(dados.get("language") or dados.get("idioma") or "auto").strip().lower()
        if idioma not in ("auto", "pt", "es"):
            raise ValueError("O campo 'language' deve ser 'auto', 'pt' ou 'es'.")

        locutor, caminho_voz = resolver_voz_openai(dados.get("voice"))
        formato_execucao = "wav" if formato in ("pcm", "raw") else formato

        if self.usar_fila:
            from tarefas import Fila, TERMINAIS
            from gui_core import salvar_pedido
            if self.fila is None: self.fila = Fila()
            cfg = {'saida': None, 'idioma': idioma, 'formatos': formato_execucao,
                   'velocidade': velocidade, 'dispositivo': self.dispositivo,
                   'cache_segmentos': str(self.pasta_cache / 'api_cache.segmentos')}
            if caminho_voz: cfg['voz'] = caminho_voz
            elif locutor: cfg['locutor'] = locutor
            if dados.get('lufs') is not None: cfg['lufs'] = dados['lufs']
            if dados.get('limpar_referencia'): cfg['limpar_referencia'] = True
            with tempfile.TemporaryDirectory(dir=self.pasta_cache) as tmp:
                pedido = salvar_pedido('gerar', texto, cfg, pasta=tmp)
                identidade = self.fila.enfileirar(sys.executable, pedido)
            self.fila.iniciar_coordenador()
            ultimo_inicio = time.monotonic()
            while True:
                tarefa = self.fila.obter(identidade)
                if tarefa['estado'] in TERMINAIS: break
                if tarefa['estado'] == 'aguardando' and time.monotonic() - ultimo_inicio > 1:
                    self.fila.iniciar_coordenador(); ultimo_inicio = time.monotonic()
                time.sleep(.1)
            if tarefa['estado'] != 'concluida':
                raise RuntimeError(tarefa['erro'] or 'Tarefa não concluída: ' + tarefa['estado'])
            resultado = tarefa['resultado']['resultado']
            arquivo = next(p for p in resultado['arquivos'] if p.endswith('.' + formato_execucao))
            if formato in ("pcm", "raw"):
                with wave.open(str(arquivo), "rb") as w:
                    return w.readframes(w.getnframes()), CONTENT_TYPES[formato]
            return Path(arquivo).read_bytes(), CONTENT_TYPES[formato]

        with self.lock, tempfile.TemporaryDirectory(dir=self.pasta_cache, prefix=".req-") as tmp:
            entrada = Path(tmp) / "entrada.txt"
            entrada.write_text(texto, encoding="utf-8")
            base = self.pasta_cache / "api_cache"
            argv = [
                str(entrada),
                "--saida", str(base),
                "--formatos", formato_execucao,
                "--idioma", idioma,
                "--velocidade", str(velocidade),
                "--dispositivo", self.dispositivo,
            ]
            if caminho_voz:
                argv.extend(["--voz", caminho_voz])
            elif locutor:
                argv.extend(["--locutor", locutor])
            if dados.get("lufs") is not None:
                argv.extend(["--lufs", str(dados["lufs"])])
            if dados.get("limpar_referencia"):
                argv.append("--limpar-referencia")

            saida_log = io.StringIO()
            erro_log = io.StringIO()
            try:
                with contextlib.redirect_stdout(saida_log), contextlib.redirect_stderr(erro_log):
                    tts.main(argv)
            except SystemExit as exc:
                detalhe = erro_log.getvalue().strip() or saida_log.getvalue().strip() or f"Erro na síntese (código {exc.code})"
                raise ValueError(detalhe) from exc

            arquivo_gerado = self.pasta_cache / f"api_cache.{formato_execucao}"
            if formato in ("pcm", "raw"):
                with wave.open(str(arquivo_gerado), "rb") as w:
                    return w.readframes(w.getnframes()), CONTENT_TYPES[formato]
            return arquivo_gerado.read_bytes(), CONTENT_TYPES[formato]

    def sintetizar_stream(self, dados: dict, interromper: threading.Event | None = None) -> tuple[Generator[bytes, None, None], str]:
        if not isinstance(dados, dict):
            raise ValueError("O corpo da requisição deve ser um objeto JSON.")
        if not isinstance(dados.get("input"), str):
            raise ValueError("O campo 'input' deve ser uma string.")
        texto = dados["input"].strip()
        if not texto:
            raise ValueError("O campo 'input' é obrigatório e não pode ser vazio.")
        formato = str(dados.get("response_format") or "wav").strip().lower()
        if formato not in ("wav", "pcm", "raw"):
            raise ValueError(f"Formato de streaming inválido ({formato!r}); use wav, pcm ou raw.")
        content_type = CONTENT_TYPES[formato]

        valor_velocidade = dados.get("speed", 1.1)
        if isinstance(valor_velocidade, bool):
            raise ValueError("O campo 'speed' deve ser numérico.")
        try:
            velocidade = float(valor_velocidade)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("O campo 'speed' deve ser numérico.") from exc
        if "limpar_referencia" in dados and not isinstance(dados["limpar_referencia"], bool):
            raise ValueError("O campo 'limpar_referencia' deve ser booleano.")
        if not math.isfinite(velocidade) or not (0.25 <= velocidade <= 4.0):
            raise ValueError("O campo 'speed' deve estar entre 0.25 e 4.0.")
        idioma = str(dados.get("language") or dados.get("idioma") or "auto").strip().lower()
        if idioma not in ("auto", "pt", "es"):
            raise ValueError("O campo 'language' deve ser 'auto', 'pt' ou 'es'.")

        locutor, caminho_voz = resolver_voz_openai(dados.get("voice"))

        fila_audio: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=64)
        if interromper is None:
            interromper = threading.Event()

        def worker():
            chunks_emitidos = 0
            try:
                def on_event(ev):
                    nonlocal chunks_emitidos
                    if interromper.is_set():
                        return
                    tipo = ev.get("tipo")
                    if tipo == "segmento":
                        arq = ev["segmento"]["arquivo"]
                        try:
                            with wave.open(arq, "rb") as w:
                                pcm = w.readframes(w.getnframes())
                            if pcm:
                                chunks_emitidos += 1
                                fila_audio.put(("chunk", pcm))
                        except Exception as exc:
                            fila_audio.put(("erro", exc))
                    elif tipo == "pausa":
                        ms = ev.get("duracao_ms", 0)
                        if ms > 0:
                            qtd_amostras = int(24000 * (ms / 1000.0))
                            silencio = b"\x00\x00" * qtd_amostras
                            fila_audio.put(("chunk", silencio))

                with self.lock, tempfile.TemporaryDirectory(dir=self.pasta_cache, prefix=".stream-") as tmp:
                    entrada = Path(tmp) / "entrada.txt"
                    entrada.write_text(texto, encoding="utf-8")
                    base = Path(tmp) / "saida"
                    argv = [
                        str(entrada),
                        "--saida", str(base),
                        "--formatos", "wav",
                        "--idioma", idioma,
                        "--velocidade", str(velocidade),
                        "--dispositivo", self.dispositivo,
                        "--cache-segmentos", str(self.pasta_cache / "api_cache.segmentos"),
                    ]
                    if caminho_voz:
                        argv.extend(["--voz", caminho_voz])
                    elif locutor:
                        argv.extend(["--locutor", locutor])
                    if dados.get("lufs") is not None:
                        argv.extend(["--lufs", str(dados["lufs"])])
                    if dados.get("limpar_referencia"):
                        argv.append("--limpar-referencia")

                    saida_log = io.StringIO()
                    erro_log = io.StringIO()
                    try:
                        with contextlib.redirect_stdout(saida_log), contextlib.redirect_stderr(erro_log):
                            tts.main(argv, on_event=on_event, should_stop=interromper.is_set)
                    except tts.SinteseInterrompida:
                        pass
                    except SystemExit as exc:
                        detalhe = erro_log.getvalue().strip() or saida_log.getvalue().strip() or f"Erro na síntese (código {exc.code})"
                        fila_audio.put(("erro", ValueError(detalhe)))
                        return
                    except Exception as exc:
                        fila_audio.put(("erro", exc))
                        return

                    if chunks_emitidos == 0 and not interromper.is_set():
                        wav_final = base.parent / f"{base.name}.wav"
                        if wav_final.is_file():
                            try:
                                with wave.open(str(wav_final), "rb") as w:
                                    pcm = w.readframes(w.getnframes())
                                if pcm:
                                    fila_audio.put(("chunk", pcm))
                            except Exception:
                                pass
            finally:
                fila_audio.put(("fim", None))

        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()

        def gerador():
            try:
                if formato == "wav":
                    yield cabecalho_wav_streaming(sample_rate=24000, canais=1, bits=16)
                while True:
                    try:
                        tipo, payload = fila_audio.get(timeout=0.1)
                    except queue.Empty:
                        if interromper.is_set():
                            break
                        if not worker_thread.is_alive():
                            while not fila_audio.empty():
                                tipo, payload = fila_audio.get_nowait()
                                if tipo == "chunk":
                                    yield payload
                                elif tipo == "erro":
                                    raise payload
                            break
                        continue
                    if tipo == "chunk":
                        yield payload
                    elif tipo == "erro":
                        raise payload
                    elif tipo == "fim":
                        break
            finally:
                interromper.set()
                worker_thread.join(timeout=2.0)

        return gerador(), content_type


def criar_servidor(host: str = "127.0.0.1", porta: int = 8000,
                   pasta_cache: Path | str | None = None, dispositivo: str = "auto", usar_fila=True, fila=None) -> ThreadingHTTPServer:
    motor = MotorAPI(pasta_cache=pasta_cache, dispositivo=dispositivo, usar_fila=usar_fila, fila=fila)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _responder_json(self, status: int, payload: dict):
            corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            caminho = self.path.split("?", 1)[0].rstrip("/") or "/"
            if caminho in ("/health", "/"):
                self._responder_json(HTTPStatus.OK, {"status": "ok", "servico": "ttsbr"})
            elif caminho == "/v1/models":
                self._responder_json(HTTPStatus.OK, {
                    "object": "list",
                    "data": [
                        {"id": "tts-1", "object": "model", "owned_by": "ttsbr"},
                        {"id": "tts-1-hd", "object": "model", "owned_by": "ttsbr"},
                        {"id": "xtts_v2", "object": "model", "owned_by": "coqui"},
                    ],
                })
            elif caminho == "/v1/voices":
                self._responder_json(HTTPStatus.OK, {
                    "voices": sorted(set(tts.PERSONAGENS_MAP.values())),
                    "aliases_openai": OPENAI_VOICE_MAP,
                })
            else:
                self._responder_json(HTTPStatus.NOT_FOUND, {"error": {"message": f"Rota não encontrada: {caminho}"}})

        def do_POST(self):
            caminho = self.path.split("?", 1)[0].rstrip("/")
            if caminho != "/v1/audio/speech":
                self._responder_json(HTTPStatus.NOT_FOUND, {"error": {"message": f"Rota não encontrada: {caminho}"}})
                return
            try:
                tamanho = int(self.headers.get("Content-Length") or 0)
                if tamanho <= 0 or tamanho > 2_000_000:
                    raise ValueError("Tamanho da requisição inválido.")
                bruto = self.rfile.read(tamanho)
                dados = json.loads(bruto.decode("utf-8"))
            except (ValueError, json.JSONDecodeError) as exc:
                self._responder_json(HTTPStatus.BAD_REQUEST, {"error": {"message": str(exc), "type": "invalid_request_error"}})
                return
            except Exception as exc:
                self._responder_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": {"message": str(exc), "type": "server_error"}})
                return

            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            query_params = {p.split("=")[0]: p.split("=")[1] for p in query.split("&") if "=" in p} if query else {}
            stream_mode = (
                isinstance(dados, dict)
                and (
                    bool(dados.get("stream"))
                    or dados.get("stream_format") == "audio"
                    or query_params.get("stream", "").lower() in ("1", "true")
                )
            )

            if stream_mode:
                interromper = threading.Event()
                try:
                    gerador, content_type = motor.sintetizar_stream(dados, interromper=interromper)
                except ValueError as exc:
                    self._responder_json(HTTPStatus.BAD_REQUEST, {"error": {"message": str(exc), "type": "invalid_request_error"}})
                    return
                except Exception as exc:
                    self._responder_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": {"message": str(exc), "type": "server_error"}})
                    return

                try:
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    for chunk in gerador:
                        if not chunk:
                            continue
                        tamanho_hex = f"{len(chunk):x}\r\n".encode("ascii")
                        self.wfile.write(tamanho_hex)
                        self.wfile.write(chunk)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    interromper.set()
                finally:
                    interromper.set()
                    gerador.close()
                return

            try:
                conteudo, content_type = motor.sintetizar(dados)
            except ValueError as exc:
                self._responder_json(HTTPStatus.BAD_REQUEST, {"error": {"message": str(exc), "type": "invalid_request_error"}})
                return
            except Exception as exc:
                self._responder_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": {"message": str(exc), "type": "server_error"}})
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(conteudo)))
            self.end_headers()
            self.wfile.write(conteudo)

    return ThreadingHTTPServer((host, porta), Handler)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="endereço de escuta (padrão: 127.0.0.1)")
    ap.add_argument("--porta", type=int, default=8000, help="porta HTTP (padrão: 8000)")
    ap.add_argument("--pasta-cache", default=None, help="pasta de cache para os segmentos da API")
    ap.add_argument("--dispositivo", default="auto", choices=["auto", "cpu", "cuda", "mps"])
    args = ap.parse_args(argv)

    servidor = criar_servidor(args.host, args.porta, args.pasta_cache, args.dispositivo)
    host, porta = servidor.server_address
    print(f"Servidor TTSBR (compatível com OpenAI) ativo em http://{host}:{porta}/v1/audio/speech")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor…")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
