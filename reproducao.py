"""Player WAV PCM em subprocesso, com transporte JSON e saída sounddevice opcional."""
import argparse
import json
import math
from pathlib import Path
import queue
import subprocess
import sys
import threading
import wave


class TransportePCM:
    """Leitura limitada a blocos; pausa/busca não alteram o arquivo."""
    def __init__(self, caminho):
        self.audio = wave.open(str(caminho), 'rb')
        if self.audio.getsampwidth() != 2 or self.audio.getcomptype() != 'NONE':
            self.audio.close()
            raise ValueError('O player requer WAV PCM de 16 bits. Gere WAV para ouvir na interface.')
        self.taxa = self.audio.getframerate()
        self.canais = self.audio.getnchannels()
        self.total = self.audio.getnframes()
        if not self.total:
            self.audio.close(); raise ValueError('Áudio vazio.')
        self.pausado = False
        self.lock = threading.Lock()

    @property
    def duracao(self):
        return self.total / self.taxa

    def comando(self, dados):
        with self.lock:
            acao = dados.get('acao')
            if acao == 'pausar': self.pausado = True
            elif acao == 'reproduzir':
                if self.audio.tell() == self.total: self.audio.rewind()
                self.pausado = False
            elif acao == 'parar':
                self.pausado = True; self.audio.rewind()
            elif acao == 'buscar':
                valor = dados.get('segundos')
                if type(valor) not in (int, float) or not math.isfinite(valor):
                    raise ValueError('Posição de busca inválida.')
                self.audio.setpos(max(0, min(self.total, round(valor * self.taxa))))
            else: raise ValueError('Comando de reprodução inválido.')

    def ler(self, frames):
        with self.lock:
            dados = b'' if self.pausado else self.audio.readframes(frames)
            if self.audio.tell() == self.total: self.pausado = True
            return dados + bytes(frames * self.canais * 2 - len(dados))

    def estado(self):
        with self.lock:
            return {'tipo': 'posicao', 'segundos': self.audio.tell() / self.taxa,
                    'duracao': self.duracao, 'pausado': self.pausado}

    def fechar(self):
        with self.lock: self.audio.close()


def executar(caminho, inicio=0):
    try:
        import sounddevice
    except ImportError as exc:
        raise ValueError('Instale o extra reproducao no Python de síntese: python -m pip install ".[reproducao]"') from exc
    transporte = TransportePCM(caminho)
    try:
        transporte.comando({'acao': 'buscar', 'segundos': inicio})
    except Exception:
        transporte.fechar()
        raise
    comandos = queue.Queue()
    falhas = []
    def ler_comandos():
        try:
            for linha in sys.stdin:
                comandos.put(json.loads(linha))
        except (ValueError, OSError):
            comandos.put({'acao': 'fechar'})
        finally:
            comandos.put({'acao': 'fechar'})
    threading.Thread(target=ler_comandos, daemon=True).start()
    def callback(saida, frames, _tempo, _status):
        try: saida[:] = transporte.ler(frames)
        except Exception as exc:
            falhas.append(str(exc)); saida[:] = bytes(len(saida)); raise sounddevice.CallbackAbort()
    try:
        with sounddevice.RawOutputStream(samplerate=transporte.taxa, channels=transporte.canais,
                                         dtype='int16', callback=callback, blocksize=1024):
            while True:
                try:
                    dados = comandos.get(timeout=.1)
                    if not isinstance(dados, dict): raise ValueError('Comando inválido.')
                    if dados.get('acao') == 'fechar': break
                    transporte.comando(dados)
                except queue.Empty:
                    pass
                if falhas: raise ValueError('Falha na saída de áudio: ' + falhas[0])
                print(json.dumps(transporte.estado()), flush=True)
    finally:
        transporte.fechar()


class ProcessoPlayer:
    def __init__(self):
        self.processo = None
        self.eventos = queue.Queue(maxsize=500)

    def iniciar(self, python, caminho, inicio=0):
        self.fechar()
        # Fila nova: um evento do player anterior não pode atualizar a nova tomada.
        eventos = self.eventos = queue.Queue(maxsize=500)
        self.processo = subprocess.Popen([str(python), '-u', str(Path(__file__)), str(caminho), '--inicio', str(inicio)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, encoding='utf-8',
                                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        processo = self.processo
        def ler():
            try:
                for linha in processo.stdout:
                    try: evento = json.loads(linha)
                    except ValueError: continue
                    try: eventos.put_nowait(evento)
                    except queue.Full: pass
            finally:
                processo.stdout.close()
        threading.Thread(target=ler, daemon=True).start()

    def enviar(self, acao, **dados):
        if self.processo is None or self.processo.poll() is not None:
            raise ValueError('O player não está em execução.')
        try:
            self.processo.stdin.write(json.dumps({'acao': acao, **dados}) + '\n')
            self.processo.stdin.flush()
        except OSError as exc:
            raise ValueError('O player encerrou. Abra o áudio novamente.') from exc

    def fechar(self):
        if self.processo:
            if self.processo.poll() is None:
                try: self.enviar('fechar')
                except ValueError: pass
                try: self.processo.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.processo.terminate()
                    try: self.processo.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        self.processo.kill(); self.processo.wait(timeout=1)
            if self.processo.stdin: self.processo.stdin.close()
            self.processo = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arquivo', type=Path)
    parser.add_argument('--inicio', type=float, default=0)
    args = parser.parse_args()
    try: executar(args.arquivo, args.inicio)
    except Exception as exc:
        print(json.dumps({'tipo': 'erro', 'mensagem': str(exc)}, ensure_ascii=False), flush=True)
        return 1
    return 0


if __name__ == '__main__': sys.exit(main())
