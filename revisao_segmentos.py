"""Identidade e edições de segmentos, vinculadas ao plano normalizado completo."""
from copy import deepcopy
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import uuid

from contratos import identificador


def assinatura(segmento):
    return json.dumps({k: segmento[k] for k in ('texto', 'idioma', 'locutor')},
                      sort_keys=True, ensure_ascii=False)


def hash_plano(segmentos):
    return hashlib.sha256(json.dumps([assinatura(s) for s in segmentos],
                                    ensure_ascii=False).encode()).hexdigest()


def reconciliar(antigos, novos):
    """Preserva IDs nas subsequências iguais; segmentos alterados ganham novo ID."""
    resultado = deepcopy(novos)
    for segmento in resultado:
        segmento['id_estavel'] = uuid.uuid4().hex
    a_ass = [assinatura(s) for s in antigos]
    b_ass = [assinatura(s) for s in novos]
    cont_a, cont_b = Counter(a_ass), Counter(b_ass)
    matcher = SequenceMatcher(a=a_ass, b=b_ass, autojunk=False)
    for a, b, tamanho in matcher.get_matching_blocks():
        for deslocamento in range(tamanho):
            chave = b_ass[b + deslocamento]
            if a_ass != b_ass and (cont_a[chave] > 1 or cont_b[chave] > 1):
                continue  # Não transportar correções para uma ocorrência ambígua.
            resultado[b + deslocamento]['id_estavel'] = antigos[a + deslocamento]['id_estavel']
    return resultado


def documento_revisao(segmentos, edicoes):
    return {'formato': 'ttsbr.revisao', 'versao_esquema': 1,
            'plano_sha256': hash_plano(segmentos),
            'ids': {str(s['id']): s['id_estavel'] for s in segmentos},
            'edicoes': dict(edicoes)}


def aplicar_revisao(segmentos, documento, max_chars=200):
    if not isinstance(documento, dict) or set(documento) != {'formato', 'versao_esquema', 'plano_sha256', 'ids', 'edicoes'}:
        raise ValueError('Documento de revisão inválido.')
    if documento['formato'] != 'ttsbr.revisao' or type(documento['versao_esquema']) is not int or documento['versao_esquema'] != 1:
        raise ValueError('Versão de revisão não suportada.')
    if documento['plano_sha256'] != hash_plano(segmentos):
        raise ValueError('O roteiro ou sua preparação mudou. Confira o roteiro antes de regerar segmentos.')
    ids, edicoes = documento['ids'], documento['edicoes']
    if not isinstance(ids, dict) or not isinstance(edicoes, dict):
        raise ValueError('IDs/edições inválidos.')
    if set(ids) != {str(s['id']) for s in segmentos} or not all(identificador(v) for v in ids.values()) or len(set(ids.values())) != len(ids):
        raise ValueError('IDs da revisão não correspondem ao plano.')
    if set(edicoes) - set(ids.values()):
        raise ValueError('Edição aponta para segmento que não existe no plano.')
    for texto in edicoes.values():
        if not isinstance(texto, str) or not texto.strip() or len(texto) > max_chars or '[' in texto or ']' in texto:
            raise ValueError('Correção deve conter de 1 a 200 caracteres, sem tags de direção.')
    resultado = deepcopy(segmentos)
    for segmento in resultado:
        segmento['id_estavel'] = ids[str(segmento['id'])]
        segmento['texto_base'] = segmento['texto']
        if segmento['id_estavel'] in edicoes:
            segmento['texto'] = edicoes[segmento['id_estavel']].strip()
    return resultado


def carregar_revisao(caminho, segmentos):
    return aplicar_revisao(segmentos, json.loads(Path(caminho).read_text(encoding='utf-8')))
