"""Processo isolado usado pela GUI. A CLI permanece disponível normalmente."""
import json
from pathlib import Path
import sys
import traceback

from gui_core import PREFIXO_EVENTO, argumentos_sintese


def emitir(evento):
    print('\n' + PREFIXO_EVENTO + json.dumps(evento, ensure_ascii=False), flush=True)


def executar(caminho):
    caminho = Path(caminho)
    pedido = json.loads(caminho.read_text(encoding='utf-8'))
    modo = pedido['modo']
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
    glossario = carregar_glossario(cfg.get('glossario'), texto_path=pedido.get('origem') or pedido['entrada'])
    g_path = caminho.parent / 'glossario_snapshot.json'
    g_path.write_text(json.dumps(glossario, ensure_ascii=False), encoding='utf-8')
    cfg['glossario'] = str(g_path)
    try:
        main(argumentos_sintese(pedido), on_event=emitir,
             should_stop=lambda: (caminho.parent / 'interromper.flag').exists())
    except SinteseInterrompida:
        return


def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError('Uso: python gui_worker.py pedido.json')
        executar(sys.argv[1])
    except SystemExit as exc:
        if exc.code:
            emitir({'tipo': 'erro', 'mensagem': 'Confira os parâmetros e os detalhes exibidos no registro.'})
        return int(exc.code or 0)
    except Exception as exc:
        traceback.print_exc()
        emitir({'tipo': 'erro', 'mensagem': str(exc)})
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
