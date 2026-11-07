"""Contratos v1 do preview. Independentes de GUI, modelos e armazenamento."""
from copy import deepcopy
import json
import math
import re

VERSAO_ESQUEMA = 1
ESTADOS_TAREFA = frozenset(('aguardando', 'executando', 'interrupcao_solicitada',
                          'interrompida', 'concluida', 'falha', 'cancelada'))


class DocumentoInvalido(ValueError):
    """Documento inválido ou versão que esta aplicação não entende."""


def exigir(condicao, mensagem):
    if not condicao:
        raise DocumentoInvalido(mensagem)


def identificador(valor):
    return isinstance(valor, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', valor) is not None


def texto(valor):
    return isinstance(valor, str) and bool(valor.strip())


def caminho_relativo(valor):
    # Formato portátil POSIX; impede drive Windows, UNC e travessia.
    return (texto(valor) and not valor.startswith('/') and '\\' not in valor
            and ':' not in valor and '\x00' not in valor
            and all(parte not in ('', '.', '..') for parte in valor.split('/')))


def json_finito(valor, profundidade=0):
    if profundidade > 32:
        return False
    if valor is None or type(valor) in (str, bool, int):
        return True
    if type(valor) is float:
        return math.isfinite(valor)
    if isinstance(valor, list):
        return all(json_finito(v, profundidade + 1) for v in valor)
    if isinstance(valor, dict):
        return all(isinstance(k, str) and json_finito(v, profundidade + 1) for k, v in valor.items())
    return False


def glossario_valido(valor, profundidade=0):
    return (isinstance(valor, dict) and profundidade <= 2
            and all(texto(k) and (texto(v) or glossario_valido(v, profundidade + 1))
                    for k, v in valor.items()))


def validar(documento):
    """Valida e devolve cópia. Nunca altera ou migra silenciosamente a entrada."""
    exigir(isinstance(documento, dict), 'Documento deve ser um objeto.')
    exigir(json_finito(documento), 'Documento deve conter apenas JSON finito.')
    exigir(type(documento.get('versao_esquema')) is int
           and documento['versao_esquema'] == VERSAO_ESQUEMA, 'Versão de esquema não suportada.')
    formato = documento.get('formato')
    exigir(formato in ('ttsbr.voz', 'ttsbr.projeto', 'ttsbr.tarefa'), 'Formato não suportado.')
    exigir(set(documento) == {'formato', 'versao_esquema', 'id', 'dados'}, 'Campos de envelope inválidos.')
    exigir(identificador(documento.get('id')), 'ID inválido.')
    dados = documento.get('dados')
    exigir(isinstance(dados, dict), 'Dados devem ser um objeto.')
    if formato == 'ttsbr.voz':
        exigir(set(dados) == {'nome', 'idioma', 'estilo', 'referencia', 'sha256',
                              'transcricao', 'autorizacao_declarada'}, 'Campos de voz inválidos.')
        exigir(texto(dados['nome']) and texto(dados['estilo']), 'Nome e estilo são obrigatórios.')
        exigir(dados['idioma'] in ('pt', 'es'), 'Idioma inválido.')
        exigir(caminho_relativo(dados['referencia']), 'Referência deve ser relativa e portátil.')
        exigir(isinstance(dados['sha256'], str)
               and re.fullmatch(r'[0-9a-f]{64}', dados['sha256']), 'Hash inválido.')
        exigir(isinstance(dados['transcricao'], str), 'Transcrição deve ser texto.')
        exigir(type(dados['autorizacao_declarada']) is bool, 'Autorização deve ser booleana.')
    elif formato == 'ttsbr.projeto':
        exigir(set(dados) == {'titulo', 'roteiro', 'elenco', 'glossario', 'configuracao'},
               'Campos de projeto inválidos.')
        exigir(texto(dados['titulo']) and isinstance(dados['roteiro'], str), 'Título/roteiro inválido.')
        for nome in ('elenco', 'glossario', 'configuracao'):
            exigir(isinstance(dados[nome], dict), f'{nome} deve ser objeto.')
        exigir(all(texto(k) and identificador(v) for k, v in dados['elenco'].items()), 'Elenco inválido.')
        exigir(glossario_valido(dados['glossario']), 'Glossário inválido.')
    else:
        exigir(set(dados) == {'projeto_id', 'estado', 'snapshot', 'saida_relativa', 'erro'},
               'Campos de tarefa inválidos.')
        exigir(identificador(dados['projeto_id']), 'Projeto inválido.')
        exigir(isinstance(dados['estado'], str) and dados['estado'] in ESTADOS_TAREFA, 'Estado inválido.')
        exigir(caminho_relativo(dados['saida_relativa']), 'Saída inválida.')
        exigir(dados['erro'] is None or texto(dados['erro']), 'Erro inválido.')
        if dados['estado'] == 'falha':
            exigir(texto(dados['erro']), 'Falha deve informar erro.')
        exigir(isinstance(dados['snapshot'], dict)
               and dados['snapshot'].get('formato') == 'ttsbr.projeto', 'Snapshot deve ser projeto.')
        snapshot = validar(dados['snapshot'])
        exigir(snapshot is not None and snapshot['formato'] == 'ttsbr.projeto'
               and snapshot['id'] == dados['projeto_id'], 'Snapshot deve corresponder ao projeto.')
    return deepcopy(documento)


def carregar(texto_json):
    """Rejeita chaves duplicadas, evitando interpretação ambígua de snapshots."""
    def pares(itens):
        dados = {}
        for chave, valor in itens:
            exigir(chave not in dados, 'Chave JSON duplicada.')
            dados[chave] = valor
        return dados
    try:
        return validar(json.loads(texto_json, object_pairs_hook=pares))
    except (ValueError, TypeError, RecursionError) as exc:
        raise DocumentoInvalido('JSON inválido ou contrato não suportado.') from exc
