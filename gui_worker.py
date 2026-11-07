"""Processo isolado usado pela GUI. A CLI permanece disponível normalmente."""
import json
import os
from pathlib import Path
import sys
import time
import traceback

from gui_core import PREFIXO_EVENTO, argumentos_sintese

RESULTADOS = {}


def emitir(evento):
    if evento.get('tipo') in ('plano', 'resultado', 'resultado_validacao', 'interrompido', 'tomada_registrada', 'erro'):
        RESULTADOS[evento['tipo']] = evento
    try:
        print('\n' + PREFIXO_EVENTO + json.dumps(evento, ensure_ascii=False), flush=True)
    except BrokenPipeError:
        sys.stdout = open(os.devnull, 'w')


def _executar(caminho):
    caminho = Path(caminho)
    pedido = json.loads(caminho.read_text(encoding='utf-8'))
    modo = pedido['modo']
    if modo == 'biblioteca_importar':
        from biblioteca_vozes import BibliotecaVozes
        cfg = pedido['configuracao']
        perfil = BibliotecaVozes(cfg['raiz']).importar(
            cfg['arquivo'], cfg['nome'], cfg['idioma'], cfg['estilo'],
            cfg.get('transcricao', ''), cfg.get('autorizacao', False), cfg.get('limpar', False))
        emitir({'tipo': 'perfil_importado', 'id': perfil['documento']['id']})
        return
    if modo not in ('analisar', 'gerar', 'amostra', 'validar', 'metricas'):
        raise ValueError('Modo de trabalho inválido.')
    if modo in ('validar', 'metricas'):
        from audio_persistente import salvar_json
        from validar_audio import validar_manifesto
        emitir({'tipo': 'etapa', 'etapa': 'validacao', 'mensagem': 'Analisando os segmentos…'})
        relatorio = validar_manifesto(pedido['manifesto'], somente_metricas=modo == 'metricas', on_event=emitir)
        origem = Path(pedido['manifesto'])
        destino = origem.with_name(origem.stem + ('.metricas.json' if modo == 'metricas' else '.validacao.json'))
        salvar_json(destino, relatorio)
        emitir({'tipo': 'resultado_validacao', 'relatorio': str(destino),
                'aprovado': relatorio['aprovado'], 'wer_global': relatorio['wer_global']})
        return
    from normalizador import carregar_glossario
    from tts import main, SinteseInterrompida
    # Mantém os glossários associados ao roteiro aberto, mesmo usando um snapshot.
    cfg = pedido['configuracao']
    cfg['glossario'] = str(Path(cfg['glossario']).resolve()) if cfg.get('glossario') else None
    glossario = (cfg['glossario_integrado'] if 'glossario_integrado' in cfg
                else carregar_glossario(cfg.get('glossario'), texto_path=pedido.get('origem') or pedido['entrada']))
    g_path = caminho.parent / 'glossario_snapshot.json'
    g_path.write_text(json.dumps(glossario, ensure_ascii=False), encoding='utf-8')
    cfg['glossario'] = str(g_path)
    try:
        main(argumentos_sintese(pedido), on_event=emitir, origem_referencias=pedido.get('origem'),
             glossario_precarregado=glossario,
             should_stop=lambda: (caminho.parent / 'interromper.flag').exists())
        if cfg.get('_projeto') and modo == 'gerar':
            emitir({'tipo': 'etapa', 'etapa': 'registro', 'mensagem': 'Preservando a tomada no projeto…'})
            from projetos import Projeto
            projeto = Projeto.abrir(cfg['_projeto'])
            base = Path(cfg['saida'])
            arquivos = [str(base.parent / f'{base.name}.{ext}') for ext in cfg.get('formatos', 'mp3,wav').split(',')]
            snapshot = pedido.get('_snapshot_projeto', {})
            registro = projeto.registrar_tomada(base.parent / f'{base.name}.blocos.json', arquivos,
                       proveniencia={'tarefa_id': os.environ.get('TTSBR_FILA_ID'),
                         'revisao_origem': snapshot.get('dados', {}).get('configuracao', {}).get('_estudio', {}).get('revisao')})
            emitir({'tipo': 'tomada_registrada', 'id': registro['id']})
    except SinteseInterrompida:
        return


def executar(caminho):
    from contextlib import nullcontext
    from exclusao import recursos
    from vozes import REFERENCIAS_CONGELADAS
    pedido = json.loads(Path(caminho).read_text(encoding='utf-8'))
    cfg = pedido['configuracao']
    token = REFERENCIAS_CONGELADAS.set(pedido.get('_referencias_congeladas', {}))
    base = Path(cfg.get('saida') or 'audio')
    cache = cfg.get('cache_segmentos') or str(base.parent / (base.name + '.segmentos'))
    try:
        with recursos(base, cache) if pedido['modo'] in ('gerar', 'amostra') else nullcontext():
            return _executar(caminho)
    finally:
        REFERENCIAS_CONGELADAS.reset(token)


def main():
    RESULTADOS.clear()
    codigo = 0
    try:
        if len(sys.argv) != 2:
            raise ValueError('Uso: python gui_worker.py pedido.json')
        if os.environ.get('TTSBR_FILA_ID'):
            limite = time.monotonic() + 30
            while not (Path(sys.argv[1]).parent / 'iniciar.flag').exists():
                if time.monotonic() > limite: raise RuntimeError('Supervisor não liberou a execução.')
                time.sleep(.02)
        executar(sys.argv[1])
    except SystemExit as exc:
        if exc.code:
            emitir({'tipo': 'erro', 'mensagem': 'Confira os parâmetros e os detalhes exibidos no registro.'})
        codigo = int(exc.code or 0)
    except Exception as exc:
        try: traceback.print_exc()
        except OSError: pass
        emitir({'tipo': 'erro', 'mensagem': str(exc)})
        codigo = 1
    if os.environ.get('TTSBR_FILA_ID'):
        try:
            from tarefas import Fila
            estado = 'falha' if codigo else 'interrompida' if 'interrompido' in RESULTADOS else 'concluida'
            Fila(os.environ['TTSBR_FILA_RAIZ']).gravar_recibo(os.environ['TTSBR_FILA_ID'],
                 int(os.environ['TTSBR_FILA_TENTATIVA']), estado, RESULTADOS)
        except Exception:
            codigo = 1
    return codigo


if __name__ == '__main__':
    sys.exit(main())
