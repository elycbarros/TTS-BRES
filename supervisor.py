"""Execução supervisionada em grupo de processos, sem carregar modelos no coordenador."""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time

from gui_core import interpretar_linha


class GrupoWindows:
    """Job Object: kill-on-close impede filhos órfãos quando o supervisor termina."""
    def __init__(self):
        self.handle = None
        if os.name != 'nt': return
        import ctypes
        from ctypes import wintypes as w
        class BASIC(ctypes.Structure):
            _fields_ = [('per_process', ctypes.c_longlong), ('per_job', ctypes.c_longlong),
                        ('flags', w.DWORD), ('min_working', ctypes.c_size_t), ('max_working', ctypes.c_size_t),
                        ('active', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class EXTENDED(ctypes.Structure):
            _fields_ = [('basic', BASIC), ('io', IO), ('process_mem', ctypes.c_size_t),
                        ('job_mem', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        class ACCOUNTING(ctypes.Structure):
            _fields_ = [('user', ctypes.c_longlong), ('kernel', ctypes.c_longlong),
                        ('period_user', ctypes.c_longlong), ('period_kernel', ctypes.c_longlong),
                        ('faults', w.DWORD), ('total', w.DWORD), ('active', w.DWORD), ('terminated', w.DWORD)]
        self.accounting = ACCOUNTING
        self.ctypes = ctypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.kernel.SetInformationJobObject.restype = w.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = w.BOOL
        self.kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.kernel.TerminateJobObject.restype = w.BOOL
        self.kernel.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
        self.kernel.QueryInformationJobObject.restype = w.BOOL
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.CloseHandle.restype = w.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        limites = EXTENDED(); limites.basic.flags = 0x2000
        if not self.handle or not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limites), ctypes.sizeof(limites)):
            self.fechar(); raise OSError('Não foi possível criar a contenção de processos do Windows.')

    def associar(self, processo):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle, int(processo._handle)):
            raise OSError('O Windows recusou o Job Object; execução não autorizada a iniciar síntese.')

    def matar(self):
        if self.handle: self.kernel.TerminateJobObject(self.handle, 1)

    def ativo(self):
        if not self.handle: return False
        conta = self.accounting()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, self.ctypes.byref(conta), self.ctypes.sizeof(conta), None):
            return True  # Sem confirmação de saída, conservar a trava e bloquear a próxima tarefa.
        return bool(conta.active)

    def fechar(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle); self.handle = None


def vivo_grupo(processo, grupo):
    if os.name == 'nt': return processo.poll() is None or grupo.ativo()
    try:
        os.killpg(processo.pid, 0)
        return True
    except ProcessLookupError: return False
    except PermissionError:
        # Alguns ambientes macOS filtram killpg(0) depois da saída. EPERM não é prova de saída:
        # confirmar pela lista de grupos, sem consultar nomes/comandos dos outros processos.
        try:
            consulta = subprocess.run(['/bin/ps', '-axo', 'pgid=,stat='], capture_output=True,
                                      text=True, timeout=3, check=False)
            if consulta.returncode: return True
            for linha in consulta.stdout.splitlines():
                campos = linha.split()
                if len(campos) >= 2 and campos[0] == str(processo.pid) and not campos[1].startswith('Z'):
                    return True
            return False
        except (OSError, subprocess.TimeoutExpired): return True


def encerrar_grupo(processo, grupo, espera=2):
    if os.name == 'nt':
        grupo.matar()
    else:
        try: os.killpg(processo.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        except PermissionError:
            if not vivo_grupo(processo, grupo): return True
            return False
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        processo.poll()
        if not vivo_grupo(processo, grupo): return True
        time.sleep(.02)
    if os.name != 'nt':
        try: os.killpg(processo.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        except PermissionError:
            return not vivo_grupo(processo, grupo)
    else: grupo.matar()
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        processo.poll()
        if not vivo_grupo(processo, grupo): return True
        time.sleep(.02)
    return False


def executar(fila, tarefa, trava, worker=None):
    """Retorna somente após confirmar a saída; retenção da trava se houver filho vivo."""
    pedido = Path(tarefa['pedido_tentativa'])
    inicio = time.monotonic()
    etapa = 'inicio'
    limites = tarefa['limites']
    deadline = inicio + limites[etapa]
    ambiente = os.environ.copy()
    ambiente.update(PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8', TTSBR_HOME=tarefa['dados_raiz'],
                    TTSBR_FILA_RAIZ=str(fila.raiz), TTSBR_FILA_ID=tarefa['id'],
                    TTSBR_FILA_TENTATIVA=str(tarefa['tentativa']))
    ambiente.setdefault('NUMBA_CACHE_DIR', str(fila.raiz / 'numba_cache'))
    opcoes = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {
        'start_new_session': True, 'pass_fds': (trava.arquivo.fileno(),)}
    grupo = GrupoWindows()
    processo = None
    eventos = queue.Queue(maxsize=500)
    erro = None
    cancelou = False
    try:
        Path(tarefa['dados_raiz']).mkdir(parents=True, exist_ok=True)
        processo = subprocess.Popen([tarefa['python'], '-u', str(worker or Path(__file__).with_name('gui_worker.py')), str(pedido)],
                                    cwd=tarefa['dados_raiz'], env=ambiente, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding='utf-8', errors='replace', **opcoes)
        try:
            grupo.associar(processo)
            # Libera o worker apenas depois de configurar a contenção no Windows.
            (pedido.parent / 'iniciar.flag').touch()
        except Exception:
            processo.kill(); processo.wait(timeout=5)
            raise
        def ler():
            with processo.stdout:
                for linha in processo.stdout:
                    evento = interpretar_linha(linha)
                    try: eventos.put_nowait(evento)
                    except queue.Full:
                        if evento['tipo'] != 'log': eventos.put(evento)
        leitor = threading.Thread(target=ler, daemon=True); leitor.start()
        while processo.poll() is None:
            while True:
                try: evento = eventos.get_nowait()
                except queue.Empty: break
                fila.evento(tarefa['id'], evento)
                if evento['tipo'] == 'etapa':
                    etapa = evento.get('etapa', etapa)
                    deadline = time.monotonic() + limites.get(etapa, limites['sintese'])
                elif evento['tipo'] == 'segmento':
                    etapa = 'sintese'; deadline = time.monotonic() + limites['sintese']
            solicitacao = fila.obter(tarefa['id'])['solicitacao']
            if solicitacao:
                (pedido.parent / 'interromper.flag').touch()
            if solicitacao == 'cancelar':
                cancelou = True; erro = 'Cancelamento forçado solicitado.'; break
            if time.monotonic() > deadline:
                erro = f'Tempo limite excedido na etapa {etapa}.'; break
            time.sleep(.03)
        if erro or vivo_grupo(processo, grupo):
            if erro or processo.poll() is not None:
                # Inclui filhos que sobreviveram à saída do worker principal.
                while not encerrar_grupo(processo, grupo):
                    fila.evento(tarefa['id'], {'tipo': 'etapa', 'etapa': 'encerramento',
                               'mensagem': 'Aguardando confirmação do encerramento dos processos; fila bloqueada.'})
                    time.sleep(.3)
        processo.wait()
        leitor.join(timeout=2)
        while not eventos.empty(): fila.evento(tarefa['id'], eventos.get_nowait())
        if erro:
            fila.finalizar(tarefa, 'cancelada' if cancelou else 'falha', erro)
        elif processo.returncode:
            fila.finalizar(tarefa, 'falha', f'Worker encerrou com código {processo.returncode}.')
        else:
            fila.concluir_por_recibo(tarefa)
    except Exception as exc:
        if processo:
            while not encerrar_grupo(processo, grupo): time.sleep(.3)
            processo.wait()
        fila.finalizar(tarefa, 'falha', str(exc))
    finally:
        grupo.fechar()


def despachar(fila, tarefa, trava, worker=None):
    """Um guardião por tarefa continua vivo se o coordenador cair."""
    import sys
    from exclusao import Trava, RecursoOcupado
    ambiente = os.environ.copy()
    if os.name == 'nt':
        # O guardião reclama a trava antes de liberar seu worker; estado/tentativa são rechecados.
        trava.fechar()
        opcoes = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        ambiente['TTSBR_GUARDIAO_FD'] = str(trava.arquivo.fileno())
        opcoes = {'start_new_session': True, 'pass_fds': (trava.arquivo.fileno(),)}
    comando = [sys.executable, '-u', str(Path(__file__)), '--fila', str(fila.raiz),
               '--id', tarefa['id'], '--tentativa', str(tarefa['tentativa'])]
    if worker: comando += ['--worker', str(worker)]
    guardiao = subprocess.Popen(comando, env=ambiente, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **opcoes)
    codigo = guardiao.wait()
    # Nunca destravar explicitamente uma descrição ainda herdada por um worker sobrevivente.
    trava.abandonar()
    try: nova = Trava(fila.raiz / 'recurso.lock').adquirir()
    except RecursoOcupado:
        return  # Sem confirmação: próximas iterações também aguardam a liberação do recurso.
    trava.arquivo = nova.arquivo
    nova.arquivo = None
    atual = fila.obter(tarefa['id'])
    if atual['estado'] in ('executando', 'interrupcao_solicitada'):
        diagnostico = Path(tarefa['pedido_tentativa']).parent / 'guardiao.erro.txt'
        detalhe = diagnostico.read_text(encoding='utf-8')[-16000:] if diagnostico.exists() else ''
        fila.finalizar(tarefa, 'falha', f'Guardião encerrou sem confirmação (código {codigo}). ' + detalhe)


def main():
    import argparse
    from exclusao import Trava, RecursoOcupado
    from tarefas import Fila
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fila', required=True)
    parser.add_argument('--id', required=True)
    parser.add_argument('--tentativa', required=True, type=int)
    parser.add_argument('--worker')
    args = parser.parse_args()
    fila = Fila(args.fila)
    trava = Trava(fila.raiz / 'recurso.lock')
    herdado = os.environ.pop('TTSBR_GUARDIAO_FD', None)
    if herdado is not None and os.name != 'nt':
        trava.arquivo = os.fdopen(int(herdado), 'a+b')
    else:
        try: trava.adquirir()
        except RecursoOcupado: return 1
    try:
        tarefa = fila.obter(args.id)
        if tarefa['tentativa'] != args.tentativa or tarefa['estado'] not in ('executando', 'interrupcao_solicitada'):
            return 1
        tarefa['pedido_tentativa'] = str(Path(tarefa['pedido']).parent / 'tentativas' / str(args.tentativa) / 'pedido.json')
        executar(fila, tarefa, trava, worker=args.worker)
        return 0
    except Exception:
        import traceback
        pasta = Path(fila.obter(args.id)['pedido']).parent / 'tentativas' / str(args.tentativa)
        try: (pasta / 'guardiao.erro.txt').write_text(traceback.format_exc()[-16000:], encoding='utf-8')
        except OSError: pass
        return 1
    finally:
        if os.name == 'nt': trava.fechar()
        else: trava.abandonar()


if __name__ == '__main__':
    import sys
    sys.exit(main())
