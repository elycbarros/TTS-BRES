"""Projetos, identidade estável, backup e tomadas com síntese simulada."""
import contextlib
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

import tts
from projetos import Projeto
from revisao_segmentos import reconciliar, documento_revisao, aplicar_revisao
from audio_persistente import salvar_json, hash_arquivo
from biblioteca_vozes import BibliotecaVozes
from test_biblioteca_vozes import criar_wav
from gui_core import ROOT, salvar_pedido, interpretar_linha


def segmentos(textos):
    return [{'id': n, 'bloco': 1, 'texto': t, 'idioma': 'pt', 'locutor': 'Luis Moray'}
            for n, t in enumerate(textos, 1)]


class TestRevisaoEstavel(unittest.TestCase):
    def test_insercao_preserva_ids_unicos_e_reordena_numeros(self):
        antigos = reconciliar([], segmentos(['A', 'B']))
        novos = reconciliar(antigos, segmentos(['C', 'A', 'B']))
        self.assertEqual([s['id_estavel'] for s in antigos], [s['id_estavel'] for s in novos[1:]])
        self.assertEqual([s['id'] for s in novos], [1, 2, 3])

    def test_repeticoes_ambiguas_invalidam_ids_apos_mudanca(self):
        antigos = reconciliar([], segmentos(['A', 'A', 'B']))
        self.assertEqual(reconciliar(antigos, segmentos(['A', 'A', 'B'])), antigos)
        novos = reconciliar(antigos, segmentos(['X', 'A', 'A', 'B']))
        self.assertTrue(set(s['id_estavel'] for s in antigos[:2]).isdisjoint(s['id_estavel'] for s in novos))
        self.assertEqual(antigos[-1]['id_estavel'], novos[-1]['id_estavel'])

    def test_revisao_obsoleta_e_textos_invalidos(self):
        plano = reconciliar([], segmentos(['A']))
        doc = documento_revisao(plano, {})
        with self.assertRaisesRegex(ValueError, 'mudou'): aplicar_revisao(segmentos(['B']), doc)
        for texto in ('', 'a'*201, '[pausa:100]'):
            doc = documento_revisao(plano, {plano[0]['id_estavel']: texto})
            with self.assertRaises(ValueError): aplicar_revisao(plano, doc)
        with self.assertRaises(ValueError): aplicar_revisao(plano, documento_revisao(plano, {'desconhecido': 'Oi'}))


class TestProjetos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'TTSBR_HOME': str(self.root / 'dados')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.projeto = Projeto.criar('Título á', 'Primeira fala. Segunda fala.')
        self.roteiro = self.root / 'roteiro com espaço.txt'
        self.roteiro.write_text(self.projeto.documento['dados']['roteiro'], encoding='utf-8')

    def test_roundtrip_config_glossario_original_e_caminhos(self):
        self.projeto.atualizar('Original 10:30.', {'saida': str(self.root/'áudio'), 'python': '/nao/restaurar'},
                               {'pt': {'Acme': 'ácme'}}, self.roteiro)
        novo = Projeto.abrir(self.projeto.caminho)
        self.assertEqual(novo.documento['dados']['roteiro'], 'Original 10:30.')
        self.assertNotIn('python', novo.configuracao())
        self.assertEqual(novo.configuracao()['saida'], str((self.root/'áudio').resolve()))
        self.assertEqual(novo.documento['dados']['glossario'], {'pt': {'Acme': 'ácme'}})

    def test_snapshot_mais_novo_bloqueia_sobrescrita(self):
        stale = Projeto.abrir(self.projeto.caminho)
        self.projeto.atualizar('Novo texto', {}, {})
        with self.assertRaisesRegex(ValueError, 'outra sessão'): stale.atualizar('Antigo', {}, {})
        self.assertEqual(Projeto.abrir(self.projeto.caminho).documento['dados']['roteiro'], 'Novo texto')

    def test_backup_e_recuperacao_preservam_corrompido(self):
        self.projeto.atualizar('Segundo texto', {}, {})
        self.projeto.caminho.write_text('{quebrado')
        with self.assertRaises(ValueError): Projeto.abrir(self.projeto.caminho)
        recuperado = Projeto.abrir(self.projeto.caminho, backup=True)
        recuperado.salvar(recuperar=True)
        self.assertEqual(Projeto.abrir(self.projeto.caminho).documento['dados']['roteiro'], 'Primeira fala. Segunda fala.')
        self.assertEqual(len(list(self.projeto.caminho.parent.glob('projeto.corrompido-*.json'))), 1)

    def test_falha_gravacao_preserva_documento_anterior(self):
        antigo = self.projeto.caminho.read_bytes()
        with patch('projetos.salvar_json', side_effect=OSError('disco cheio')):
            with self.assertRaises(OSError): self.projeto.atualizar('Novo', {}, {})
        self.assertEqual(self.projeto.caminho.read_bytes(), antigo)
        self.assertEqual(self.projeto.documento['dados']['roteiro'], 'Primeira fala. Segunda fala.')

    def test_rascunho_preserva_salvo_e_nao_guarda_python(self):
        antigo = self.projeto.caminho.read_bytes()
        self.projeto.rascunho('Não salvo', {'python': '/privado/python', 'idioma': 'es'})
        dados = self.projeto.ler_rascunho()
        self.assertEqual(dados['roteiro'], 'Não salvo')
        self.assertNotIn('python', dados['configuracao'])
        self.assertEqual(self.projeto.caminho.read_bytes(), antigo)

    def test_perfil_vinculado_nao_remove_e_arquivo_ausente_e_religacao(self):
        wav = self.root/'ref.wav'; criar_wav(wav)
        biblioteca = BibliotecaVozes()
        identidade = biblioteca.importar(wav, 'Referência', autorizacao=True)['documento']['id']
        self.projeto.atualizar('Olá', {'perfil_voz': identidade}, {})
        with self.assertRaisesRegex(ValueError, 'vinculado'): biblioteca.remover(identidade)
        biblioteca.resolver(identidade).unlink()
        reaberto = Projeto.abrir(self.projeto.caminho)
        self.assertEqual(reaberto.configuracao()['perfil_voz'], identidade)
        with self.assertRaisesRegex(ValueError, 'ausente'): biblioteca.resolver(identidade)
        novo = biblioteca.importar(wav, 'Outra referência', autorizacao=True)['documento']['id']
        reaberto.atualizar('Olá', {'perfil_voz': novo}, {})
        biblioteca.remover(identidade)
        self.assertTrue(biblioteca.resolver(novo).is_file())

    def test_edicao_preserva_original_e_descarta_edicao_de_segmento_removido(self):
        self.projeto.conferir_plano(segmentos(['Primeira', 'Segunda']))
        identidade = self.projeto.estado['segmentos'][0]['id_estavel']
        self.projeto.editar_segmento(identidade, 'Corrigida')
        self.assertEqual(self.projeto.documento['dados']['roteiro'], 'Primeira fala. Segunda fala.')
        self.projeto.conferir_plano(segmentos(['Segunda']))
        self.assertNotIn(identidade, self.projeto.estado['edicoes'])

    def test_versoes_futuras_nao_sao_regravadas(self):
        self.projeto.atualizar('Atual', {}, {})
        for alterar in ('envelope', 'estudio'):
            doc = deepcopy(self.projeto.documento)
            if alterar == 'envelope': doc['versao_esquema'] = 9
            else: doc['dados']['configuracao']['_estudio']['versao'] = 9
            self.projeto.caminho.write_text(json.dumps(doc))
            antigo = self.projeto.caminho.read_bytes()
            with self.assertRaises(ValueError): Projeto.abrir(self.projeto.caminho)
            self.assertEqual(self.projeto.caminho.read_bytes(), antigo)
            if alterar == 'estudio':
                recuperado = Projeto.abrir(self.projeto.caminho, backup=True)
                with self.assertRaisesRegex(ValueError, 'desconhecida'): recuperado.salvar(recuperar=True)
                self.assertEqual(self.projeto.caminho.read_bytes(), antigo)

    def test_worker_preserva_glossario_congelado_apesar_de_mudanca_externa(self):
        self.roteiro.write_text('Banco Acme.', encoding='utf-8')
        self.roteiro.with_name('roteiro com espaço.glossario.txt').write_text('Acme = outra empresa', encoding='utf-8')
        pedido = salvar_pedido('analisar', 'Banco Acme.', {
            'saida': str(self.root/'audio'), 'glossario_integrado': {'Acme': 'empresa congelada'}},
            origem=self.roteiro, pasta=self.root/'pedidos')
        resposta = subprocess.run([sys.executable, str(ROOT/'gui_worker.py'), str(pedido)],
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(resposta.returncode, 0, resposta.stderr + resposta.stdout)
        plano = next(e for e in map(interpretar_linha, resposta.stdout.splitlines()) if e['tipo'] == 'plano')
        self.assertIn('empresa congelada', plano['segmentos'][0]['texto'].lower())
        self.assertNotIn('outra empresa', plano['segmentos'][0]['texto'])

    def test_sintese_corrigida_reutiliza_cache_recalcula_legendas_e_preserva_tomadas(self):
        eventos = []
        modelo = MagicMock()
        modelo.tts.side_effect = lambda text, **_kw: np.sin(np.arange(2400 if text != 'Corrigida' else 4800) * .1) * .1
        with contextlib.redirect_stdout(io.StringIO()):
            tts.main([str(self.roteiro), '--analisar'], on_event=eventos.append)
        self.projeto.conferir_plano(eventos[0]['segmentos'])
        def gerar(refazer=None):
            cfg = self.projeto.preparar_execucao()
            argv = [str(self.roteiro), '--saida', cfg['saida'], '--formatos', 'wav,srt,vtt',
                    '--cache-segmentos', cfg['cache_segmentos'], '--revisao-segmentos', cfg['revisao_segmentos']]
            if refazer: argv += ['--refazer-segmentos', str(refazer)]
            with contextlib.redirect_stdout(io.StringIO()): tts.main(argv, modelo_precarregado=modelo)
            manifesto = Path(cfg['saida'] + '.blocos.json')
            arquivos = [cfg['saida'] + '.' + ext for ext in ('wav', 'srt', 'vtt')]
            self.projeto.registrar_tomada(manifesto, arquivos)
            return manifesto, json.loads(manifesto.read_text())
        primeiro, anterior = gerar()
        pcm_anterior = Path(anterior['segmentos'][0]['arquivo']).read_bytes()
        tempos_anteriores = [s['inicio_s'] for s in anterior['segmentos']]
        self.assertEqual(modelo.tts.call_count, 2)
        id_estavel = self.projeto.estado['segmentos'][0]['id_estavel']
        self.projeto.editar_segmento(id_estavel, 'Corrigida')
        segundo, atual = gerar(1)
        self.assertEqual(modelo.tts.call_count, 3)
        self.assertTrue(atual['segmentos'][1]['reutilizado'])
        self.assertGreater(atual['segmentos'][1]['inicio_s'], tempos_anteriores[1])
        self.assertEqual(atual['segmentos'][0]['id_estavel'], anterior['segmentos'][0]['id_estavel'])
        self.assertEqual(Path(anterior['segmentos'][0]['arquivo']).read_bytes(), pcm_anterior)
        self.assertEqual(json.loads(primeiro.read_text()), anterior)
        self.assertEqual(atual['segmentos'][0]['texto'], 'Corrigida')
        self.assertEqual(self.projeto.documento['dados']['roteiro'], 'Primeira fala. Segunda fala.')
        self.assertEqual(len(Projeto.abrir(self.projeto.caminho).estado['tomadas']), 2)
        self.assertNotEqual(primeiro.with_name('audio.srt').read_text(), segundo.with_name('audio.srt').read_text())
        self.assertIn('WEBVTT', segundo.with_name('audio.vtt').read_text())
        self.projeto.registrar_tomada(segundo, [])  # Retry de registro não duplica nem recopia sobre si.
        self.assertEqual(len(self.projeto.estado['tomadas']), 2)

    def test_revisao_errada_falha_antes_de_sobrescrever_saida(self):
        self.projeto.conferir_plano(segmentos(['Antiga']))
        cfg = self.projeto.preparar_execucao()
        arquivo = Path(cfg['saida']+'.wav'); arquivo.write_bytes(b'preservado')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tts.main([str(self.roteiro), '--saida', cfg['saida'], '--revisao-segmentos', cfg['revisao_segmentos']])
        self.assertEqual(arquivo.read_bytes(), b'preservado')

    def test_exportar_e_importar_pacote_projeto_com_e_sem_referencia(self):
        wav = self.root / 'minha_voz.wav'
        criar_wav(wav)
        self.projeto.atualizar('Texto do pacote.', {'voz': str(wav), 'velocidade': '1.0'}, {'pt': {'IA': 'i-á'}})
        pacote_sem_ref = self.root / 'export_sem_ref.json'
        dados_sem = self.projeto.exportar_pacote(pacote_sem_ref, incluir_referencia=False)
        self.assertIsNone(dados_sem['referencia'])
        self.assertNotIn(str(self.root), pacote_sem_ref.read_text(encoding='utf-8'))
        importado_sem = Projeto.importar_pacote(pacote_sem_ref, raiz=self.root / 'destino_sem')
        self.assertNotEqual(importado_sem.id, self.projeto.id)
        self.assertEqual(importado_sem.documento['dados']['roteiro'], 'Texto do pacote.')
        self.assertEqual(importado_sem.documento['dados']['glossario'], {'pt': {'IA': 'i-á'}})
        self.assertNotIn('voz', importado_sem.configuracao())

        # Com referência WAV verificada por hash e tamanho
        pacote_com_ref = self.root / 'export_com_ref.json'
        dados_com = self.projeto.exportar_pacote(pacote_com_ref, incluir_referencia=True)
        self.assertIsNotNone(dados_com['referencia'])
        importado_com = Projeto.importar_pacote(pacote_com_ref, raiz=self.root / 'destino_com')
        voz_imp = Path(importado_com.configuracao()['voz'])
        self.assertTrue(voz_imp.is_file())
        self.assertEqual(hash_arquivo(voz_imp), hash_arquivo(wav))

        # Rejeita adulteração de hash, travessia de caminho e sobrescrita
        with self.assertRaises(FileExistsError):
            self.projeto.exportar_pacote(pacote_com_ref)
        adulterado = json.loads(pacote_com_ref.read_text(encoding='utf-8'))
        adulterado['referencia']['sha256'] = '0' * 64
        pacote_bad = self.root / 'bad_hash.json'
        pacote_bad.write_text(json.dumps(adulterado), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Integridade'):
            Projeto.importar_pacote(pacote_bad, raiz=self.root / 'destino_bad')
        adulterado['referencia']['caminho'] = '../minha_voz.wav'
        pacote_trav = self.root / 'bad_path.json'
        pacote_trav.write_text(json.dumps(adulterado), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'inválido'):
            Projeto.importar_pacote(pacote_trav, raiz=self.root / 'destino_bad2')


if __name__ == '__main__': unittest.main()
