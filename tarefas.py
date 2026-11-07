"""Fila local durável: snapshots, estados, eventos limitados e coordenador único."""
import argparse
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

from audio_persistente import hash_arquivo, salvar_json
from caminhos import pasta_dados
from contratos import identificador
from exclusao import Trava, RecursoOcupado, identidade_recurso

ATIVOS = ('aguardando', 'executando', 'interrupcao_solicitada')
TERMINAIS = ('interrompida', 'concluida', 'falha', 'cancelada')
LIMITES = {'inicio': 600, 'modelo': 600, 'sintese': 600, 'montagem': 600,
           'validacao': 900, 'registro': 300}
MAX_EVENTOS = 1000
MAX_FINALIZADAS = 200


class Fila:
    def __init__(self, raiz=None):
        self.raiz = Path(raiz or (pasta_dados() / 'local' / 'fila')).resolve()
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.banco = self.raiz / 'fila.sqlite3'
        self.coordenador = None
        with closing(self.conectar()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            versao = db.execute('PRAGMA user_version').fetchone()[0]
            if versao not in (0, 1): raise ValueError('Versão de fila não suportada.')
            if versao == 0 and db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError('Banco sem versão de fila reconhecida.')
            db.execute('CREATE TABLE IF NOT EXISTS tarefas ('
                       'id TEXT PRIMARY KEY, estado TEXT NOT NULL, pedido TEXT NOT NULL, dados_raiz TEXT NOT NULL, perfil TEXT, '
                       'sha256 TEXT NOT NULL, python TEXT NOT NULL, saida TEXT, limites TEXT NOT NULL, '
                       'criada REAL NOT NULL, atualizada REAL NOT NULL, tentativa INTEGER NOT NULL DEFAULT 0, '
                       'solicitacao TEXT, erro TEXT, resultado TEXT, rotulo TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS eventos ('
                       'seq INTEGER PRIMARY KEY AUTOINCREMENT, tarefa_id TEXT NOT NULL, evento TEXT NOT NULL)')
            db.execute('PRAGMA user_version=1')

    def dono(self, identidade=''):
        return 'fila-' + hashlib.sha256(str(self.raiz).encode()).hexdigest()[:16] + '-' + identidade

    def captura(self):
        limite = time.monotonic() + 15
        while True:
            try: return Trava(self.raiz / 'captura.lock').adquirir()
            except RecursoOcupado:
                if time.monotonic() >= limite: raise
                time.sleep(.03)

    def reconciliar_vinculos(self):
        try: trava = Trava(self.raiz / 'captura.lock').adquirir()
        except RecursoOcupado: return
        try:
            from biblioteca_vozes import BibliotecaVozes
            with closing(self.conectar()) as db:
                tarefas = [dict(r) for r in db.execute('SELECT id,estado,dados_raiz FROM tarefas')]
            ativos = {self.dono(t['id']) for t in tarefas if t['estado'] in ATIVOS}
            raizes = {t['dados_raiz'] for t in tarefas} | {str(pasta_dados().resolve())}
            for raiz in raizes:
                biblioteca = BibliotecaVozes(Path(raiz) / 'local' / 'vozes')
                for perfil, dono in biblioteca.listar_usos(self.dono()):
                    if dono not in ativos: biblioteca.liberar_uso(perfil, dono)
        finally: trava.fechar()

    def conectar(self):
        db = sqlite3.connect(self.banco, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def obter(self, identidade):
        if not identificador(identidade): raise ValueError('ID de tarefa inválido.')
        with closing(self.conectar()) as db:
            row = db.execute('SELECT * FROM tarefas WHERE id=?', (identidade,)).fetchone()
        if row is None: raise ValueError('Tarefa não encontrada.')
        dados = dict(row)
        dados['limites'] = json.loads(dados['limites'])
        dados['resultado'] = json.loads(dados['resultado']) if dados['resultado'] else None
        dados['pedido'] = str(self.raiz / dados['pedido'])
        return dados

    def listar(self):
        with closing(self.conectar()) as db:
            return [dict(row) for row in db.execute('SELECT id,estado,rotulo,criada,atualizada,tentativa,erro,solicitacao FROM tarefas ORDER BY criada')]

    def _copiar(self, caminho, pasta, arquivos):
        caminho = Path(caminho).expanduser().resolve()
        if not caminho.is_file(): raise ValueError(f'Arquivo necessário ausente: {caminho}')
        nome = f'{len(arquivos):04d}' + caminho.suffix.lower()
        destino = pasta / 'arquivos' / nome
        destino.parent.mkdir(exist_ok=True)
        shutil.copyfile(caminho, destino)
        digest = hash_arquivo(destino)
        if digest != hash_arquivo(caminho): raise ValueError('Arquivo mudou durante a captura do snapshot.')
        arquivos.append({'caminho': str(destino), 'sha256': digest})
        return str(destino)

    def enfileirar(self, python, pedido, limites=None):
        with self.captura():
            return self._enfileirar(python, pedido, limites)

    def _enfileirar(self, python, pedido, limites=None):
        python = str(Path(python).expanduser().absolute())
        if not Path(python).is_file(): raise ValueError('Python de síntese não encontrado.')
        tempos = {**LIMITES, **(limites or {})}
        if set(tempos) != set(LIMITES) or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in tempos.values()):
            raise ValueError('Limites de tempo devem ser números positivos por etapa conhecida.')
        documento = json.loads(Path(pedido).read_text(encoding='utf-8'))
        if documento.get('modo') not in ('analisar', 'gerar', 'amostra', 'validar', 'metricas'):
            raise ValueError('Modo de tarefa não suportado.')
        identidade = uuid.uuid4().hex
        pasta = self.raiz / 'tarefas' / identidade
        pasta.mkdir(parents=True)
        perfil = None
        vinculado = False
        try:
            cfg = documento['configuracao'] = deepcopy(documento['configuracao'])
            documento['_dados_raiz'] = str(pasta_dados().resolve())
            arquivos = []
            documento['entrada'] = self._copiar(documento['entrada'], pasta, arquivos)
            from normalizador import carregar_glossario
            if 'glossario_integrado' not in cfg:
                cfg['glossario_integrado'] = carregar_glossario(cfg.get('glossario'), documento.get('origem'))
            cfg['glossario'] = ''
            for campo in ('revisao_segmentos', 'trilha'):
                if cfg.get(campo): cfg[campo] = self._copiar(cfg[campo], pasta, arquivos)
            aliases = {}
            from vozes import eh_caminho_audio, resolver_caminho_voz, carregar_vozes_personagens
            origem = Path(documento['origem']) if documento.get('origem') else Path(documento['entrada'])
            def congelar_ref(valor):
                resolvido = resolver_caminho_voz(valor, origem)
                copia = self._copiar(resolvido, pasta, arquivos)
                candidatos = [Path(valor).expanduser().absolute(), Path(resolvido)]
                if not Path(valor).is_absolute(): candidatos.append(origem.parent / valor)
                for candidato in candidatos:
                    aliases[str(candidato.absolute())] = copia
                    aliases[str(candidato.resolve())] = copia
                return copia
            if cfg.get('perfil_voz'):
                from biblioteca_vozes import BibliotecaVozes
                perfil = cfg.pop('perfil_voz')
                biblioteca = BibliotecaVozes()
                cfg['voz'] = congelar_ref(str(biblioteca.resolver(perfil)))
                biblioteca.registrar_uso(perfil, self.dono(identidade)); vinculado = True
                documento['_perfil_original'] = perfil
            elif cfg.get('voz'):
                cfg['voz'] = congelar_ref(cfg['voz'])
            for campo in ('vozes_personagens', 'vozes_tons'):
                for valor in carregar_vozes_personagens(cfg.get(campo), origem).values(): congelar_ref(valor)
            texto = Path(documento['entrada']).read_text(encoding='utf-8-sig')
            for tag in re.findall(r'\[([^\]\n]+)\]', texto):
                nome = tag.split('|', 1)[0].strip()
                if eh_caminho_audio(nome): congelar_ref(nome)
            documento['_referencias_congeladas'] = aliases
            if documento.get('manifesto'):
                manifesto = json.loads(Path(documento['manifesto']).read_text(encoding='utf-8'))
                origem_manifesto = Path(documento['manifesto']).resolve().parent
                for segmento in manifesto.get('segmentos', []):
                    segmento['arquivo'] = self._copiar(origem_manifesto / segmento['arquivo'], pasta, arquivos)
                congelado = pasta / 'manifesto.json'; salvar_json(congelado, manifesto)
                arquivos.append({'caminho': str(congelado), 'sha256': hash_arquivo(congelado)})
                documento['manifesto'] = str(congelado)
            if cfg.get('_projeto'):
                from projetos import Projeto
                projeto = Projeto.abrir(cfg['_projeto'])
                documento['_snapshot_projeto'] = projeto.documento
            if documento['modo'] in ('gerar', 'amostra') and not cfg.get('saida'):
                cfg['saida'] = str(pasta / 'resultado' / 'audio')
            saida = identidade_recurso(cfg['saida']) if cfg.get('saida') and documento['modo'] in ('gerar', 'amostra') else None
            documento['_arquivos'] = arquivos
            caminho = pasta / 'pedido.json'; salvar_json(caminho, documento)
            agora = time.time()
            with closing(self.conectar()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                if saida and db.execute("SELECT 1 FROM tarefas WHERE saida=? AND estado IN ('aguardando','executando','interrupcao_solicitada')", (saida,)).fetchone():
                    raise ValueError('Já existe uma tarefa ativa reservando essa saída.')
                db.execute('INSERT INTO tarefas(id,estado,pedido,sha256,python,saida,limites,criada,atualizada,rotulo,dados_raiz,perfil) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                           (identidade, 'aguardando', str(caminho.relative_to(self.raiz)), hash_arquivo(caminho), python,
                            saida, json.dumps(tempos), agora, agora,
                            documento.get('_snapshot_projeto', {}).get('dados', {}).get('titulo', documento['modo']),
                            documento['_dados_raiz'], perfil))
            return identidade
        except Exception:
            if vinculado:
                from biblioteca_vozes import BibliotecaVozes
                BibliotecaVozes().liberar_uso(perfil, self.dono(identidade))
            shutil.rmtree(pasta)
            raise

    def evento(self, identidade, evento):
        if evento.get('tipo') == 'log': evento = {**evento, 'texto': str(evento.get('texto', ''))[:16000]}
        texto = json.dumps(evento, ensure_ascii=False, allow_nan=False)
        with closing(self.conectar()) as db, db:
            db.execute('INSERT INTO eventos(tarefa_id,evento) VALUES(?,?)', (identidade, texto))
            db.execute('DELETE FROM eventos WHERE tarefa_id=? AND seq NOT IN (SELECT seq FROM eventos WHERE tarefa_id=? ORDER BY seq DESC LIMIT ?)',
                       (identidade, identidade, MAX_EVENTOS))

    def eventos_desde(self, identidade, cursor=0):
        with closing(self.conectar()) as db:
            return [(r['seq'], json.loads(r['evento'])) for r in db.execute(
                'SELECT seq,evento FROM eventos WHERE tarefa_id=? AND seq>? ORDER BY seq', (identidade, cursor))]

    def solicitar(self, identidade, forcar=False):
        with closing(self.conectar()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT estado FROM tarefas WHERE id=?', (identidade,)).fetchone()
            if row is None: raise ValueError('Tarefa não encontrada.')
            if row[0] in TERMINAIS: return
            if row[0] == 'aguardando':
                estado = 'cancelada' if forcar else 'interrompida'
                db.execute('UPDATE tarefas SET estado=?,atualizada=? WHERE id=?', (estado, time.time(), identidade))
            else:
                db.execute("UPDATE tarefas SET estado='interrupcao_solicitada',solicitacao=?,atualizada=? WHERE id=?",
                           ('cancelar' if forcar else 'pausar', time.time(), identidade))
        if row[0] == 'aguardando': self._liberar_perfil(identidade)

    def retomar(self, identidade):
        with self.captura():
            return self._retomar(identidade)

    def _retomar(self, identidade):
        tarefa = self.obter(identidade)
        if tarefa['estado'] not in ('falha', 'interrompida', 'cancelada'):
            raise ValueError('Só é possível retomar tarefa interrompida, cancelada ou com falha.')
        self.verificar_snapshot(tarefa)
        documento = json.loads(Path(tarefa['pedido']).read_text(encoding='utf-8'))
        if documento.get('_perfil_original'):
            from biblioteca_vozes import BibliotecaVozes
            BibliotecaVozes().registrar_uso(documento['_perfil_original'], self.dono(identidade))
        with closing(self.conectar()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if tarefa['saida'] and db.execute("SELECT 1 FROM tarefas WHERE id<>? AND saida=? AND estado IN ('aguardando','executando','interrupcao_solicitada')", (identidade, tarefa['saida'])).fetchone():
                raise ValueError('Outra tarefa está reservando essa saída.')
            db.execute("UPDATE tarefas SET estado='aguardando',erro=NULL,solicitacao=NULL,resultado=NULL,atualizada=? WHERE id=? AND estado IN ('falha','interrompida','cancelada')", (time.time(), identidade))

    def verificar_snapshot(self, tarefa):
        caminho = Path(tarefa['pedido'])
        if hash_arquivo(caminho) != tarefa['sha256']: raise ValueError('Snapshot da tarefa alterado.')
        documento = json.loads(caminho.read_text(encoding='utf-8'))
        for arquivo in documento['_arquivos']:
            if hash_arquivo(arquivo['caminho']) != arquivo['sha256']: raise ValueError('Arquivo do snapshot alterado.')
        return documento

    def preparar(self, identidade):
        tarefa = self.obter(identidade)
        documento = self.verificar_snapshot(tarefa)
        with closing(self.conectar()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT estado,tentativa FROM tarefas WHERE id=?', (identidade,)).fetchone()
            if row['estado'] != 'aguardando': return None
            tentativa = row['tentativa'] + 1
            pasta = Path(tarefa['pedido']).parent / 'tentativas' / str(tentativa)
            pasta.mkdir(parents=True, exist_ok=True)
            if tentativa > 1:
                documento['configuracao']['refazer'] = False
                documento['configuracao'].pop('refazer_segmentos', None)
            caminho = pasta / 'pedido.json'; salvar_json(caminho, documento)
            db.execute("UPDATE tarefas SET estado='executando',tentativa=?,atualizada=?,erro=NULL WHERE id=?", (tentativa, time.time(), identidade))
        tarefa = self.obter(identidade)
        tarefa['pedido_tentativa'] = str(caminho)
        return tarefa

    def _liberar_perfil(self, identidade):
        tarefa = self.obter(identidade)
        if tarefa.get('perfil'):
            from biblioteca_vozes import BibliotecaVozes
            BibliotecaVozes(Path(tarefa['dados_raiz']) / 'local' / 'vozes').liberar_uso(tarefa['perfil'], self.dono(identidade))

    def finalizar(self, tarefa, estado, erro=None, resultado=None):
        if estado not in TERMINAIS: raise ValueError('Estado final inválido.')
        with closing(self.conectar()) as db, db:
            cursor = db.execute('UPDATE tarefas SET estado=?,erro=?,resultado=?,solicitacao=NULL,atualizada=? WHERE id=? AND tentativa=? AND estado IN (\'executando\',\'interrupcao_solicitada\')',
                                (estado, erro, json.dumps(resultado) if resultado is not None else None, time.time(), tarefa['id'], tarefa['tentativa']))
        if cursor.rowcount: self._liberar_perfil(tarefa['id'])

    def gravar_recibo(self, identidade, tentativa, estado, eventos):
        tarefa = self.obter(identidade)
        if tentativa != tarefa['tentativa']: raise ValueError('Tentativa obsoleta.')
        resultado = {'estado': estado, 'eventos': eventos, 'tentativa': tentativa, 'pedido_sha256': tarefa['sha256'], 'arquivos': []}
        if estado == 'concluida':
            pedido = self.verificar_snapshot(tarefa)
            modo = pedido['modo']
            if modo in ('gerar', 'amostra'):
                final = eventos.get('resultado')
                if not final: raise ValueError('Worker não publicou resultado.')
                manifesto = json.loads(Path(final['manifesto']).read_text(encoding='utf-8'))
                if manifesto.get('estado') != 'concluido': raise ValueError('Manifesto incompleto.')
                if pedido['configuracao'].get('_projeto') and modo == 'gerar' and 'tomada_registrada' not in eventos:
                    raise ValueError('Tomada ainda não registrada no projeto.')
                caminhos = [final['manifesto'], *final['arquivos'], *[s['arquivo'] for s in manifesto['segmentos']]]
            elif modo in ('metricas', 'validar'):
                caminhos = [eventos['resultado_validacao']['relatorio']]
            else:
                if 'plano' not in eventos: raise ValueError('Análise não publicou um plano.')
                caminhos = []
            resultado['arquivos'] = [{'caminho': str(p), 'sha256': hash_arquivo(p)} for p in caminhos]
        caminho = Path(tarefa['pedido']).parent / 'tentativas' / str(tentativa) / 'conclusao.json'
        salvar_json(caminho, resultado)

    def concluir_por_recibo(self, tarefa):
        try:
            caminho = Path(tarefa['pedido']).parent / 'tentativas' / str(tarefa['tentativa']) / 'conclusao.json'
            recibo = json.loads(caminho.read_text(encoding='utf-8'))
            if recibo['tentativa'] != tarefa['tentativa'] or recibo['pedido_sha256'] != tarefa['sha256']:
                raise ValueError('Recibo incompatível.')
            if recibo['estado'] not in ('concluida', 'interrompida', 'falha'): raise ValueError('Recibo inválido.')
            for arquivo in recibo['arquivos']:
                if hash_arquivo(arquivo['caminho']) != arquivo['sha256']: raise ValueError('Resultado alterado ou incompleto.')
            self.finalizar(tarefa, recibo['estado'], 'Worker reportou falha.' if recibo['estado'] == 'falha' else None, recibo['eventos'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.finalizar(tarefa, 'falha', 'Não foi possível confirmar conclusão: ' + str(exc))

    def recuperar(self):
        # Chamado somente sob a trava global de recurso: nenhum worker anterior pode estar usando o modelo.
        with closing(self.conectar()) as db:
            ids = [r[0] for r in db.execute("SELECT id FROM tarefas WHERE estado IN ('executando','interrupcao_solicitada')")]
        for identidade in ids:
            tarefa = self.obter(identidade)
            recibo = Path(tarefa['pedido']).parent / 'tentativas' / str(tarefa['tentativa']) / 'conclusao.json'
            if recibo.exists(): self.concluir_por_recibo(tarefa)
            else: self.finalizar(tarefa, 'interrompida', 'Execução anterior terminou sem confirmação; retome para verificar o cache.')

    def limpar_historico(self):
        # Remove só metadados antigos concluídos/cancelados. Artefatos privados não são apagados automaticamente.
        with closing(self.conectar()) as db, db:
            ids = [r[0] for r in db.execute("SELECT id FROM tarefas WHERE estado IN ('concluida','cancelada') ORDER BY atualizada DESC LIMIT -1 OFFSET ?", (MAX_FINALIZADAS,))]
            for identidade in ids:
                db.execute('DELETE FROM eventos WHERE tarefa_id=?', (identidade,))
                db.execute('DELETE FROM tarefas WHERE id=?', (identidade,))

    def rodar(self, ocioso=2, worker=None):
        from supervisor import despachar
        limite_inicio = time.monotonic() + 1
        while True:
            try:
                coordenador = Trava(self.raiz / 'coordenador.lock').adquirir(); break
            except RecursoOcupado:
                if time.monotonic() >= limite_inicio: return
                time.sleep(.05)
        try:
            sem_trabalho = time.monotonic()
            while True:
                try: recurso = Trava(self.raiz / 'recurso.lock').adquirir()
                except RecursoOcupado:
                    time.sleep(.1); continue
                try:
                    self.recuperar()
                    self.reconciliar_vinculos()
                    with closing(self.conectar()) as db:
                        row = db.execute("SELECT id FROM tarefas WHERE estado='aguardando' ORDER BY criada LIMIT 1").fetchone()
                    if row is None:
                        if time.monotonic() - sem_trabalho >= ocioso: break
                    else:
                        sem_trabalho = time.monotonic()
                        try:
                            tarefa = self.preparar(row[0])
                            if tarefa: despachar(self, tarefa, recurso, worker=worker)
                        except Exception as exc:
                            with closing(self.conectar()) as db, db:
                                db.execute("UPDATE tarefas SET estado='falha',erro=?,atualizada=? WHERE id=?", (str(exc), time.time(), row[0]))
                            self._liberar_perfil(row[0])
                finally: recurso.fechar()
                self.limpar_historico()
                time.sleep(.05)
        finally: coordenador.fechar()

    def iniciar_coordenador(self):
        if self.coordenador is not None and self.coordenador.poll() is None: return self.coordenador
        self.coordenador = subprocess.Popen([sys.executable, '-u', str(Path(__file__)), '--raiz', str(self.raiz), 'rodar'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                cwd=str(self.raiz), start_new_session=(os.name != 'nt'),
                                creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0)
        return self.coordenador



class ClienteFila:
    """Adapter da GUI: eventos da tarefa selecionada; trabalho não depende da janela."""
    def __init__(self, fila=None):
        self.fila = fila or Fila()
        self.eventos = queue.Queue()
        self.identidade = None

    @property
    def ativo(self):
        return self.identidade is not None and self.fila.obter(self.identidade)['estado'] in ATIVOS

    def iniciar(self, python, pedido):
        if self.ativo: raise RuntimeError('Já existe uma tarefa associada à janela.')
        self.identidade = self.fila.enfileirar(python, pedido)
        self.fila.iniciar_coordenador()
        identidade = self.identidade
        def acompanhar():
            cursor = 0
            ultima_inicio = time.monotonic()
            while True:
                try:
                    for seq, evento in self.fila.eventos_desde(identidade, cursor):
                        cursor = seq
                        self.eventos.put(evento)
                    tarefa = self.fila.obter(identidade)
                    if tarefa['estado'] in TERMINAIS:
                        # O commit final pode ocorrer entre a leitura dos eventos e a leitura do estado.
                        for seq, evento in self.fila.eventos_desde(identidade, cursor):
                            cursor = seq; self.eventos.put(evento)
                        self.eventos.put({'tipo': 'estado_fila', 'estado': tarefa['estado'], 'erro': tarefa['erro']})
                        self.eventos.put({'tipo': 'processo_encerrado', 'codigo': 0 if tarefa['estado'] in ('concluida','interrompida') else 1})
                        break
                    if tarefa['estado'] == 'aguardando' and time.monotonic() - ultima_inicio > 1:
                        self.fila.iniciar_coordenador(); ultima_inicio = time.monotonic()
                    time.sleep(.1)
                except Exception as exc:
                    self.eventos.put({'tipo': 'erro', 'mensagem': str(exc)})
                    self.eventos.put({'tipo': 'processo_encerrado', 'codigo': 1}); break
        threading.Thread(target=acompanhar, daemon=True).start()
        return identidade

    def interromper_apos_segmento(self):
        if self.identidade: self.fila.solicitar(self.identidade)

    def encerrar(self):
        if self.identidade: self.fila.solicitar(self.identidade, forcar=True)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raiz', type=Path)
    sub = parser.add_subparsers(dest='acao', required=True)
    sub.add_parser('listar'); sub.add_parser('rodar')
    adicionar = sub.add_parser('adicionar'); adicionar.add_argument('pedido'); adicionar.add_argument('--python', default=sys.executable)
    for acao in ('interromper', 'cancelar', 'retomar'):
        comando = sub.add_parser(acao); comando.add_argument('id')
    args = parser.parse_args(argv)
    try:
        fila = Fila(args.raiz)
        if args.acao == 'listar': print(json.dumps(fila.listar(), ensure_ascii=False, indent=2))
        elif args.acao == 'rodar': fila.rodar()
        elif args.acao == 'adicionar':
            identidade = fila.enfileirar(args.python, args.pedido)
            fila.iniciar_coordenador(); print(identidade)
        elif args.acao == 'retomar': fila.retomar(args.id); fila.iniciar_coordenador()
        else: fila.solicitar(args.id, forcar=args.acao == 'cancelar')
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
