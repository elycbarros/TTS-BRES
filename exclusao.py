"""Exclusão entre processos por arquivo; liberada pelo SO, sem confiar em PID salvo."""
from contextlib import ExitStack, contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import sys

_ATIVOS = threading.local()


class RecursoOcupado(RuntimeError):
    pass


class Trava:
    def __init__(self, caminho):
        self.caminho = Path(caminho)
        self.arquivo = None

    def adquirir(self):
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        arquivo = self.caminho.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if arquivo.seek(0, 2) == 0:
                    arquivo.write(b'0'); arquivo.flush()
                arquivo.seek(0)
                msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            arquivo.close()
            raise RecursoOcupado('Recurso em uso por outro processo; aguarde sua liberação.') from exc
        self.arquivo = arquivo
        return self

    def fechar(self):
        if self.arquivo:
            if os.name == 'nt':
                import msvcrt
                self.arquivo.seek(0)
                msvcrt.locking(self.arquivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.arquivo.fileno(), fcntl.LOCK_UN)
            self.arquivo.close(); self.arquivo = None

    def abandonar(self):
        """Fecha só esta cópia do FD; uma cópia herdada pelo worker conserva a trava POSIX."""
        if self.arquivo:
            self.arquivo.close(); self.arquivo = None

    def __enter__(self): return self if self.arquivo is not None else self.adquirir()
    def __exit__(self, *_args): self.fechar()


def identidade_recurso(caminho):
    chave = os.path.normcase(str(Path(caminho).expanduser().resolve()))
    # Conservador em volumes macOS sensíveis a caixa; não deixar colisões passarem em APFS/exFAT sem distinção.
    return chave.casefold() if sys.platform == 'darwin' else chave


@contextmanager
def recursos(*caminhos):
    ativos = getattr(_ATIVOS, 'caminhos', None)
    if ativos is None:
        ativos = _ATIVOS.caminhos = set()
    chaves = sorted({identidade_recurso(p) for p in caminhos if p} - ativos)
    with ExitStack() as pilha:
        for chave in chaves:
            nome = hashlib.sha256(chave.encode('utf-8')).hexdigest() + '.lock'
            pilha.enter_context(Trava(Path(tempfile.gettempdir()) / 'ttsbr-travas' / nome))
        ativos.update(chaves)
        try: yield
        finally: ativos.difference_update(chaves)
