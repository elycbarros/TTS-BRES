"""Projetos locais JSON v1 com revisão otimista, backup e histórico de tomadas."""
from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

from audio_persistente import hash_arquivo, salvar_json
from biblioteca_vozes import BibliotecaVozes
from caminhos import pasta_dados
from contratos import carregar, validar, identificador, caminho_relativo
from revisao_segmentos import reconciliar, documento_revisao, aplicar_revisao

CAMINHOS_CFG = ('saida', 'voz', 'glossario', 'trilha', 'cache_segmentos')


def relativo(caminho, pasta):
    return os.path.relpath(Path(caminho).resolve(), pasta) if caminho else None


class Projeto:
    def __init__(self, caminho, documento):
        self.caminho = Path(caminho).resolve()
        self.documento = validar(documento)
        if self.documento['formato'] != 'ttsbr.projeto':
            raise ValueError('Selecione um projeto TTSBR.')
        estado = self.estado
        if not isinstance(estado, dict) or estado.get('versao') != 1 or type(estado.get('versao')) is not int:
            raise ValueError('Versão de estúdio não suportada.')
        if type(estado.get('revisao')) is not int or estado['revisao'] < 0:
            raise ValueError('Revisão de projeto inválida.')
        if not isinstance(estado.get('tomadas'), list) or not isinstance(estado.get('segmentos'), list):
            raise ValueError('Histórico/plano inválido.')
        if not isinstance(estado.get('edicoes'), dict):
            raise ValueError('Edições inválidas.')
        for numero, segmento in enumerate(estado['segmentos'], 1):
            if (not isinstance(segmento, dict) or type(segmento.get('id')) is not int
                    or segmento['id'] != numero or not identificador(segmento.get('id_estavel'))
                    or not isinstance(segmento.get('texto'), str) or segmento.get('idioma') not in ('pt', 'es')
                    or not isinstance(segmento.get('locutor'), str)):
                raise ValueError('Segmento de projeto inválido.')
        for tomada in estado['tomadas']:
            if (not isinstance(tomada, dict) or not identificador(tomada.get('id'))
                    or not caminho_relativo(tomada.get('manifesto'))
                    or not tomada['manifesto'].startswith('tomadas/' + tomada['id'] + '/')
                    or not isinstance(tomada.get('arquivos'), list)
                    or not all(caminho_relativo(p) and p.startswith('tomadas/' + tomada['id'] + '/')
                               for p in tomada['arquivos'])):
                raise ValueError('Registro de tomada inválido.')
        aplicar_revisao(estado['segmentos'], documento_revisao(estado['segmentos'], estado['edicoes']))

    @property
    def estado(self):
        return self.documento['dados']['configuracao'].get('_estudio')

    @property
    def id(self):
        return self.documento['id']

    @classmethod
    def criar(cls, titulo, roteiro, raiz=None):
        raiz = Path(raiz or (pasta_dados() / 'local' / 'projetos')).resolve()
        identidade = uuid.uuid4().hex
        caminho = raiz / identidade / 'projeto.json'
        cfg = {'_estudio': {'versao': 1, 'revisao': 0, 'origem': None,
                             'segmentos': [], 'edicoes': {}, 'tomadas': []}}
        projeto = cls(caminho, {'formato': 'ttsbr.projeto', 'versao_esquema': 1,
                               'id': identidade, 'dados': {'titulo': titulo, 'roteiro': roteiro,
                                                          'elenco': {}, 'glossario': {}, 'configuracao': cfg}})
        projeto.salvar()
        return projeto

    @classmethod
    def abrir(cls, caminho, backup=False):
        caminho = Path(caminho).resolve()
        fonte = caminho.with_suffix('.backup.json') if backup else caminho
        return cls(caminho, carregar(fonte.read_text(encoding='utf-8')))

    def configuracao(self):
        cfg = {k: v for k, v in self.documento['dados']['configuracao'].items() if k != '_estudio'}
        for chave in CAMINHOS_CFG:
            if cfg.get(chave): cfg[chave] = str((self.caminho.parent / cfg[chave]).resolve())
        cfg['glossario_integrado'] = deepcopy(self.documento['dados']['glossario'])
        return cfg

    def mesmo_conteudo(self, outro):
        def editavel(projeto):
            dados = deepcopy(projeto.documento['dados'])
            dados['configuracao'].pop('_estudio', None)
            return dados
        return self.id == outro.id and editavel(self) == editavel(outro)

    def atualizar(self, roteiro, configuracao, glossario, origem=None):
        anterior = deepcopy(self.documento)
        cfg = deepcopy(configuracao)
        for chave in ('python', 'glossario_integrado', '_projeto', 'revisao_segmentos', 'refazer_segmentos', 'refazer'):
            cfg.pop(chave, None)
        for chave in CAMINHOS_CFG:
            if cfg.get(chave): cfg[chave] = relativo(cfg[chave], self.caminho.parent)
        cfg['_estudio'] = deepcopy(self.estado)
        cfg['_estudio']['origem'] = relativo(origem, self.caminho.parent)
        self.documento['dados'].update(roteiro=roteiro, configuracao=cfg, glossario=deepcopy(glossario),
                                       elenco={'narrador': cfg['perfil_voz']} if cfg.get('perfil_voz') else {})
        try: self.salvar()
        except Exception:
            self.documento = anterior
            raise

    def salvar(self, recuperar=False):
        validar(self.documento)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        # O banco contém somente o índice/lock. O JSON é a autoridade do conteúdo.
        indice = self.caminho.parent / 'indice.sqlite3'
        with closing(sqlite3.connect(indice, timeout=10)) as banco, banco:
            banco.execute('CREATE TABLE IF NOT EXISTS projetos (id TEXT PRIMARY KEY, arquivo TEXT NOT NULL)')
            banco.execute('BEGIN IMMEDIATE')
            atual = None
            if self.caminho.exists():
                try:
                    atual = Projeto.abrir(self.caminho)
                except (ValueError, OSError):
                    if not recuperar: raise
                    try:
                        bruto = json.loads(self.caminho.read_text(encoding='utf-8'))
                    except (ValueError, OSError):
                        bruto = None
                    if isinstance(bruto, dict) and (bruto.get('versao_esquema') != 1
                            or bruto.get('dados', {}).get('configuracao', {}).get('_estudio', {}).get('versao') != 1):
                        raise ValueError('Versão desconhecida: recupere o backup em outra pasta; não sobrescreva este projeto.')
                    shutil.copyfile(self.caminho, self.caminho.with_name('projeto.corrompido-' + uuid.uuid4().hex + '.json'))
                if atual and atual.estado['revisao'] != self.estado['revisao'] and not recuperar:
                    raise ValueError('O projeto foi alterado por outra sessão. Reabra antes de salvar.')
                if atual and atual.id != self.id:
                    raise ValueError('Identidade de projeto incompatível.')
            biblioteca = BibliotecaVozes()
            novos = set(self.documento['dados']['elenco'].values())
            antigos = set(atual.documento['dados']['elenco'].values()) if atual else set()
            # Registrar antes de publicar: um crash pode deixar vínculo conservador, nunca voz desprotegida.
            for identidade in novos: biblioteca.registrar_uso(identidade, self.id)
            candidato = deepcopy(self.documento)
            candidato['dados']['configuracao']['_estudio']['revisao'] = (atual.estado['revisao'] if atual else self.estado['revisao']) + 1
            if atual:
                salvar_json(self.caminho.with_suffix('.backup.json'), atual.documento)
            salvar_json(self.caminho, candidato)
            banco.execute('INSERT OR REPLACE INTO projetos VALUES (?,?)', (self.id, self.caminho.name))
            self.documento = candidato
            biblioteca.reconciliar_usos(self.id, novos)

    def conferir_plano(self, segmentos):
        anteriores = self.estado['segmentos']
        novos = reconciliar(anteriores, segmentos)
        ids = {s['id_estavel'] for s in novos}
        self.estado['segmentos'] = novos
        self.estado['edicoes'] = {k: v for k, v in self.estado['edicoes'].items() if k in ids}
        self.salvar()

    def editar_segmento(self, id_estavel, texto):
        edicoes = {**self.estado['edicoes'], id_estavel: texto}
        aplicar_revisao(self.estado['segmentos'], documento_revisao(self.estado['segmentos'], edicoes))
        self.estado['edicoes'] = edicoes
        self.salvar()

    def preparar_execucao(self):
        cfg = self.configuracao()
        tomada = self.caminho.parent / 'tomadas' / uuid.uuid4().hex
        tomada.mkdir(parents=True)
        cfg['saida'] = str(tomada / 'audio')
        cfg['cache_segmentos'] = str(self.caminho.parent / 'cache.segmentos')
        revisao = tomada / 'revisao.json'
        salvar_json(revisao, documento_revisao(self.estado['segmentos'], self.estado['edicoes']))
        cfg['revisao_segmentos'] = str(revisao)
        cfg['_projeto'] = str(self.caminho)
        return cfg

    def registrar_tomada(self, manifesto, arquivos, proveniencia=None):
        manifesto = Path(manifesto).resolve()
        if not manifesto.is_relative_to(self.caminho.parent / 'tomadas'):
            raise ValueError('A tomada deve estar dentro do projeto.')
        existente = next((t for t in self.estado['tomadas'] if t['id'] == manifesto.parent.name), None)
        if existente: return existente
        dados = json.loads(manifesto.read_text(encoding='utf-8'))
        if dados.get('estado') != 'concluido': raise ValueError('Tomada incompleta.')
        # Snapshot de segmentos: --refazer pode substituir os WAVs do cache compartilhado.
        pasta = manifesto.parent / 'segmentos'
        pasta.mkdir(exist_ok=True)
        for segmento in dados['segmentos']:
            fonte = Path(segmento['arquivo'])
            destino = pasta / f"{segmento['id']}.wav"
            if fonte.resolve() != destino.resolve(): shutil.copyfile(fonte, destino)
            if hash_arquivo(fonte) != hash_arquivo(destino): raise ValueError('Cópia de segmento inválida.')
            segmento['arquivo'] = str(destino)
        salvar_json(manifesto, dados)
        registro = {'id': manifesto.parent.name, 'manifesto': relativo(manifesto, self.caminho.parent),
                    'arquivos': [relativo(p, self.caminho.parent) for p in arquivos]}
        if proveniencia is not None: registro['proveniencia'] = proveniencia
        if not any(t['id'] == registro['id'] for t in self.estado['tomadas']):
            self.estado['tomadas'].append(registro)
            self.salvar()
        return registro

    def rascunho(self, roteiro, configuracao=None):
        salvar_json(self.caminho.with_suffix('.rascunho.json'), {'formato': 'ttsbr.rascunho',
                    'projeto_id': self.id, 'revisao_base': self.estado['revisao'], 'roteiro': roteiro,
                    'configuracao': {k: v for k, v in (configuracao or {}).items() if k != 'python'}})

    def ler_rascunho(self):
        caminho = self.caminho.with_suffix('.rascunho.json')
        if not caminho.exists(): return None
        dados = json.loads(caminho.read_text(encoding='utf-8'))
        if dados.get('formato') != 'ttsbr.rascunho' or dados.get('projeto_id') != self.id or not isinstance(dados.get('roteiro'), str):
            raise ValueError('Rascunho inválido.')
        return dados

    def exportar_pacote(self, destino, incluir_referencia=False):
        """Exporta um pacote JSON portátil (somente dados necessários; referência opcional em pasta adjacente)."""
        destino = Path(destino).expanduser().absolute()
        if destino.suffix.lower() != '.json':
            raise ValueError('O pacote exportado deve ter extensão .json.')
        if destino.exists():
            raise FileExistsError('O arquivo de exportação já existe; escolha outro nome.')
        if not destino.parent.is_dir():
            raise ValueError('A pasta de destino da exportação deve existir.')
        doc = deepcopy(self.documento)
        cfg = doc['dados']['configuracao']
        for chave in CAMINHOS_CFG:
            cfg.pop(chave, None)
        cfg.pop('perfil_voz', None)
        doc['dados']['elenco'] = {}
        est = cfg.get('_estudio', {})
        est['origem'] = None
        est['tomadas'] = []
        validar(doc)
        pacote = {'formato': 'ttsbr.pacote_projeto', 'versao_esquema': 1,
                  'projeto': doc, 'referencia': None}
        if incluir_referencia:
            cfg_atual = self.configuracao()
            caminho_ref = None
            if cfg_atual.get('perfil_voz'):
                caminho_ref = BibliotecaVozes().resolver(cfg_atual['perfil_voz'])
            elif cfg_atual.get('voz'):
                caminho_ref = Path(cfg_atual['voz']).resolve()
            if caminho_ref is not None:
                caminho_ref = Path(caminho_ref).resolve()
                if not caminho_ref.is_file():
                    raise ValueError('Referência de voz indisponível para exportação.')
                if caminho_ref.suffix.lower() != '.wav':
                    raise ValueError('Apenas referências .wav podem ser incluídas no pacote.')
                tamanho = caminho_ref.stat().st_size
                if tamanho <= 44 or tamanho > 50 * 1024 * 1024:
                    raise ValueError('Tamanho de referência fora do limite permitido (44 B a 50 MB).')
                pasta_arquivos = destino.with_suffix('') .with_name(destino.stem + '.arquivos')
                rel_ref = f'{pasta_arquivos.name}/referencia.wav'
                if not caminho_relativo(rel_ref):
                    raise ValueError('Nome de destino inválido para referência portátil.')
                pasta_arquivos.mkdir(parents=True, exist_ok=True)
                alvo_ref = pasta_arquivos / 'referencia.wav'
                shutil.copyfile(caminho_ref, alvo_ref)
                sha = hash_arquivo(alvo_ref)
                if sha != hash_arquivo(caminho_ref):
                    raise ValueError('Falha ao verificar hash da referência exportada.')
                pacote['referencia'] = {'caminho': rel_ref, 'sha256': sha, 'tamanho_bytes': tamanho}
        salvar_json(destino, pacote)
        return pacote

    @classmethod
    def importar_pacote(cls, origem, raiz=None):
        """Importa um pacote portátil validando versão, caminhos relativos, extensão, tamanho e SHA-256."""
        origem = Path(origem).expanduser().resolve()
        if not origem.is_file() or origem.suffix.lower() != '.json':
            raise ValueError('Selecione um pacote de projeto .json válido.')
        if origem.stat().st_size > 10 * 1024 * 1024:
            raise ValueError('Arquivo de pacote excede o limite de 10 MB.')
        bruto = json.loads(origem.read_text(encoding='utf-8'))
        if not isinstance(bruto, dict) or bruto.get('formato') != 'ttsbr.pacote_projeto' or bruto.get('versao_esquema') != 1:
            raise ValueError('Formato ou versão de pacote não suportada.')
        if set(bruto) - {'formato', 'versao_esquema', 'projeto', 'referencia'}:
            raise ValueError('Campos desconhecidos no pacote de projeto.')
        doc = validar(bruto.get('projeto'))
        if doc['formato'] != 'ttsbr.projeto':
            raise ValueError('O pacote não contém um projeto válido.')
        cfg = doc['dados']['configuracao']
        for chave in CAMINHOS_CFG:
            if cfg.get(chave):
                raise ValueError(f'Caminho local não permitido no pacote: {chave}')
        info_ref = bruto.get('referencia')
        ref_origem = None
        if info_ref is not None:
            if not isinstance(info_ref, dict) or set(info_ref) != {'caminho', 'sha256', 'tamanho_bytes'}:
                raise ValueError('Metadados de referência inválidos no pacote.')
            rel = info_ref['caminho']
            if not caminho_relativo(rel) or not rel.lower().endswith('.wav'):
                raise ValueError('Caminho de referência inválido ou extensão não permitida.')
            tam = info_ref['tamanho_bytes']
            if type(tam) is not int or tam <= 44 or tam > 50 * 1024 * 1024:
                raise ValueError('Tamanho de referência inválido no pacote.')
            candidato = (origem.parent / rel).resolve()
            if not candidato.is_relative_to(origem.parent) or not candidato.is_file():
                raise ValueError('Arquivo de referência do pacote ausente ou fora da pasta de origem.')
            if candidato.stat().st_size != tam or hash_arquivo(candidato) != info_ref['sha256']:
                raise ValueError('Integridade da referência do pacote falhou (tamanho ou SHA-256 divergente).')
            ref_origem = candidato
        raiz = Path(raiz or (pasta_dados() / 'local' / 'projetos')).resolve()
        identidade = uuid.uuid4().hex
        doc['id'] = identidade
        doc['dados']['elenco'] = {}
        est = doc['dados']['configuracao'].get('_estudio', {})
        est['revisao'] = 0
        est['origem'] = None
        est['tomadas'] = []
        caminho = raiz / identidade / 'projeto.json'
        caminho.parent.mkdir(parents=True, exist_ok=True)
        if ref_origem is not None:
            destino_ref = caminho.parent / 'referencia_importada.wav'
            shutil.copyfile(ref_origem, destino_ref)
            if hash_arquivo(destino_ref) != info_ref['sha256']:
                raise ValueError('Falha ao copiar referência importada.')
            doc['dados']['configuracao']['voz'] = 'referencia_importada.wav'
        projeto = cls(caminho, doc)
        projeto.salvar()
        return projeto
