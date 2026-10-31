"""Integração da GUI com processos de trabalho; sem dependências gráficas."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import uuid

from caminhos import pasta_dados

ROOT = Path(__file__).resolve().parent
DATA_ROOT = pasta_dados()
PREFIXO_EVENTO = 'TTSBR_EVENT '


def python_padrao():
    # Uma instalação deve usar seu próprio ambiente, sem escolher outro venv pessoal.
    if not (ROOT / 'pyproject.toml').is_file():
        return sys.executable
    for pasta in (ROOT / '.venv', Path.home() / '.venvs' / 'ttsbr'):
        for relativo in ('bin/python', 'Scripts/python.exe'):
            candidato = pasta / relativo
            if candidato.is_file():
                return str(candidato.absolute())
    return sys.executable


def argumentos_sintese(pedido):
    cfg = pedido['configuracao']
    args = [pedido['entrada'], '--saida', cfg['saida'], '--idioma', cfg.get('idioma', 'auto'),
            '--formatos', cfg.get('formatos', 'mp3,wav')]
    for nome in ('locutor', 'voz', 'vozes_personagens', 'vozes_tons', 'glossario',
                 'trilha', 'volume_trilha', 'refazer_segmentos',
                 'velocidade', 'volume_alvo', 'lufs', 'taxa_amostragem', 'max_tentativas', 'dispositivo',
                 'pausa_frase', 'pausa_reticencias', 'pausa_ponto_virgula', 'pausa_virgula',
                 'pausa_paragrafo', 'pausa_bloco'):
        valor = cfg.get(nome)
        if valor is not None and str(valor).strip():
            args.extend(['--' + nome.replace('_', '-'), str(valor)])
    for nome in ('sem_normalizar', 'sem_corte_silencio', 'limpar_referencia', 'refazer'):
        if cfg.get(nome):
            args.append('--' + nome.replace('_', '-'))
    if pedido['modo'] == 'analisar':
        args.append('--analisar')
    return args


def salvar_pedido(modo, texto, configuracao, origem=None, manifesto=None, pasta=None):
    sessao = (Path(pasta) if pasta else DATA_ROOT / 'local' / 'gui' / 'execucoes') / uuid.uuid4().hex
    sessao.mkdir(parents=True)
    entrada = sessao / 'roteiro.txt'
    entrada.write_text(texto, encoding='utf-8')
    pedido = {'modo': modo, 'entrada': str(entrada), 'origem': str(origem) if origem else None,
              'configuracao': dict(configuracao), 'manifesto': str(manifesto) if manifesto else None}
    caminho = sessao / 'pedido.json'
    caminho.write_text(json.dumps(pedido, ensure_ascii=False, indent=2), encoding='utf-8')
    return caminho


def interpretar_linha(linha):
    if linha.startswith(PREFIXO_EVENTO):
        try:
            evento = json.loads(linha[len(PREFIXO_EVENTO):])
            if isinstance(evento, dict) and isinstance(evento.get('tipo'), str):
                return evento
        except ValueError:
            pass
    return {'tipo': 'log', 'texto': linha.rstrip()}


class ProcessoTrabalho:
    """Leitura em thread; a janela consome a fila no próprio event loop."""
    def __init__(self):
        self.eventos = queue.Queue(maxsize=2000)
        self.processo = None
        self.pedido = None

    @property
    def ativo(self):
        return self.processo is not None and self.processo.poll() is None

    def iniciar(self, python, pedido):
        if self.ativo:
            raise RuntimeError('Já existe uma tarefa em execução.')
        if not Path(python).is_file():
            raise ValueError('Selecione o executável Python do ambiente do TTSBR.')
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        self.pedido = Path(pedido)
        ambiente = os.environ.copy()
        ambiente['PYTHONUNBUFFERED'] = '1'
        ambiente['PYTHONIOENCODING'] = 'utf-8'
        ambiente.setdefault('NUMBA_CACHE_DIR', str(DATA_ROOT / 'local' / 'gui' / 'numba_cache'))
        self.processo = subprocess.Popen(
            [str(python), '-u', str(ROOT / 'gui_worker.py'), str(pedido)],
            cwd=str(DATA_ROOT), env=ambiente, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
        )
        threading.Thread(target=self._ler, args=(self.processo,), daemon=True).start()

    def _ler(self, processo):
        try:
            with processo.stdout as saida:
                for linha in saida:
                    self.eventos.put(interpretar_linha(linha))
        except Exception as exc:
            self.eventos.put({'tipo': 'erro', 'mensagem': str(exc)})
        finally:
            codigo = processo.wait()
            self.eventos.put({'tipo': 'processo_encerrado', 'codigo': codigo})

    def interromper_apos_segmento(self):
        if self.ativo and self.pedido:
            (self.pedido.parent / 'interromper.flag').touch()

    def encerrar(self):
        if self.ativo:
            self.processo.terminate()
