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
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading

import tts

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
}


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
    return tts.resolver_locutor(v, "pt", v), None


class MotorAPI:
    """Gerencia a execução thread-safe e o cache persistente de segmentos do servidor."""

    def __init__(self, pasta_cache: Path | str | None = None, dispositivo: str = "auto"):
        self.pasta_cache = Path(pasta_cache or (Path(__file__).resolve().parent / "saida" / "api_cache"))
        self.pasta_cache.mkdir(parents=True, exist_ok=True)
        self.dispositivo = dispositivo
        self.lock = threading.Lock()

    def sintetizar(self, dados: dict) -> tuple[bytes, str]:
        if not isinstance(dados, dict):
            raise ValueError("O corpo da requisição deve ser um objeto JSON.")
        texto = str(dados.get("input") or "").strip()
        if not texto:
            raise ValueError("O campo 'input' é obrigatório e não pode ser vazio.")
        formato = str(dados.get("response_format") or "mp3").strip().lower()
        if formato not in CONTENT_TYPES:
            raise ValueError(f"Formato inválido ({formato!r}); use mp3, wav, srt ou vtt.")
        velocidade = float(dados.get("speed", 1.1))
        if not math.isfinite(velocidade) or not (0.25 <= velocidade <= 4.0):
            raise ValueError("O campo 'speed' deve estar entre 0.25 e 4.0.")
        idioma = str(dados.get("language") or dados.get("idioma") or "auto").strip().lower()
        if idioma not in ("auto", "pt", "es"):
            raise ValueError("O campo 'language' deve ser 'auto', 'pt' ou 'es'.")

        locutor, caminho_voz = resolver_voz_openai(dados.get("voice"))

        with self.lock, tempfile.TemporaryDirectory(dir=self.pasta_cache, prefix=".req-") as tmp:
            entrada = Path(tmp) / "entrada.txt"
            entrada.write_text(texto, encoding="utf-8")
            base = self.pasta_cache / "api_cache"
            argv = [
                str(entrada),
                "--saida", str(base),
                "--formatos", formato,
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

            arquivo_gerado = self.pasta_cache / f"api_cache.{formato}"
            return arquivo_gerado.read_bytes(), CONTENT_TYPES[formato]


def criar_servidor(host: str = "127.0.0.1", porta: int = 8000,
                   pasta_cache: Path | str | None = None, dispositivo: str = "auto") -> ThreadingHTTPServer:
    motor = MotorAPI(pasta_cache=pasta_cache, dispositivo=dispositivo)

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
                conteudo, content_type = motor.sintetizar(dados)
            except (ValueError, json.JSONDecodeError) as exc:
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
