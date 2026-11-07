"""Biblioteca real com áudio sintético público; sem modelo ou voz pessoal."""
from array import array
import contextlib
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from biblioteca_vozes import BibliotecaVozes, hash_arquivo
from gui_core import argumentos_sintese, salvar_pedido, interpretar_linha, ROOT


def criar_wav(caminho, silencioso=False, saturado=False, duracao=.15):
    with wave.open(str(caminho), 'wb') as audio:
        audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        valores = array('h', [0 if silencioso else 32767 if saturado else int(math.sin(i*.1)*5000)
                             for i in range(int(24000*duracao))])
        if sys.byteorder != 'little': valores.byteswap()
        audio.writeframes(valores.tobytes())


class TestBibliotecaVozes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'dados pessoais'
        self.bib = BibliotecaVozes(self.home / 'local' / 'vozes')
        self.wav = self.root / 'voz com acento á.wav'; criar_wav(self.wav)

    def importar(self, **extras):
        cfg = dict(origem=self.wav, nome='Tomada neutra', autorizacao=True)
        cfg.update(extras)
        return self.bib.importar(**cfg)

    def test_seis_tomadas_e_persistencia_sem_alterar_original(self):
        antes = self.wav.read_bytes()
        perfis = [self.importar(nome=f'{roteiro} {estilo}', estilo=estilo)
                  for roteiro in ('curto', 'longo') for estilo in ('neutra', 'expressiva', 'calma')]
        reaberta = BibliotecaVozes(self.bib.raiz)
        self.assertEqual(len(reaberta.listar()), 6)
        self.assertEqual(len({p['documento']['id'] for p in perfis}), 6)
        self.assertEqual(self.wav.read_bytes(), antes)
        for perfil in perfis:
            identidade = perfil['documento']['id']
            self.assertEqual(reaberta.resolver(identidade, original=True).read_bytes(), antes)
            self.assertIn('amostra_curta', perfil['audio']['metricas']['avisos'])

    def test_editar_preserva_id_e_bytes(self):
        perfil = self.importar(); identidade = perfil['documento']['id']
        caminho = self.bib.resolver(identidade); antes = caminho.read_bytes()
        self.bib.atualizar(identidade, nome='Nova descrição', idioma='es', estilo='calma', transcricao='¡Hola!')
        novo = self.bib.obter(identidade)['documento']
        self.assertEqual(novo['dados']['transcricao'], '¡Hola!')
        self.assertEqual(self.bib.resolver(identidade).read_bytes(), antes)
        with self.assertRaises(ValueError): self.bib.atualizar(identidade, referencia='../outra.wav')
        with self.assertRaises(ValueError): self.bib.renomear(identidade, ' ')

    def test_sem_autorizacao_e_arquivo_invalido_nao_criam_perfil(self):
        with self.assertRaises(ValueError): self.importar(autorizacao=False)
        self.wav.write_bytes(b'invalido')
        with self.assertRaises(ValueError): self.importar()
        self.assertEqual(self.bib.listar(), [])

    def test_original_alterado_bloqueia_reuso_e_backup(self):
        perfil = self.importar(); identidade = perfil['documento']['id']
        original = self.bib.resolver(identidade, original=True)
        original.write_bytes(b'alterado')
        with self.assertRaisesRegex(ValueError, 'alterada'): self.bib.resolver(identidade)
        with self.assertRaises(ValueError): self.bib.backup(self.root / 'backup')
        self.assertFalse((self.root / 'backup').exists())

    def test_arquivo_ausente_e_previa_alterada(self):
        perfil = self.importar(); identidade = perfil['documento']['id']
        caminho = self.bib.resolver(identidade); caminho.write_bytes(b'alterado')
        with self.assertRaisesRegex(ValueError, 'alterada'): self.bib.resolver(identidade)
        caminho.unlink()
        with self.assertRaisesRegex(ValueError, 'ausente'): self.bib.resolver(identidade)

    def test_link_simbolico_interno_recusado(self):
        perfil = self.importar(); identidade = perfil['documento']['id']
        caminho = self.bib.resolver(identidade)
        caminho.unlink()
        try: caminho.symlink_to(self.wav)
        except OSError: self.skipTest('Links simbólicos não permitidos neste ambiente.')
        with self.assertRaisesRegex(ValueError, 'simbólicos'): self.bib.resolver(identidade)

    def test_remocao_preserva_arquivos_e_bloqueia_perfil_vinculado(self):
        perfil = self.importar(); identidade = perfil['documento']['id']
        caminho = self.bib.resolver(identidade)
        self.bib.registrar_uso(identidade, 'projeto-1')
        with self.assertRaisesRegex(ValueError, 'vinculado'): self.bib.remover(identidade)
        self.bib.liberar_uso(identidade, 'projeto-1'); self.bib.remover(identidade)
        self.assertEqual(self.bib.listar(), [])
        self.assertTrue(caminho.exists())
        with self.assertRaises(ValueError): self.bib.resolver(identidade)
        with self.assertRaises(ValueError): self.bib.registrar_uso(identidade, 'projeto-2')
        self.assertEqual(self.bib.listar(removidas=True)[0]['documento']['id'], identidade)
        self.bib.restaurar(identidade)
        self.assertEqual(self.bib.resolver(identidade), caminho)

    def test_backup_reabre_com_tomadas_e_renomeia_sem_tocar_fonte(self):
        perfil = self.importar(); identidade = perfil['documento']['id']
        destino = self.bib.backup(self.root / 'backup separado')
        copia = BibliotecaVozes(destino)
        self.assertEqual(hash_arquivo(copia.resolver(identidade)), hash_arquivo(self.bib.resolver(identidade)))
        copia.renomear(identidade, 'Na cópia')
        self.assertNotEqual(copia.obter(identidade), self.bib.obter(identidade))
        with self.assertRaises(ValueError): self.bib.backup(destino)
        with self.assertRaises(ValueError): self.bib.backup(self.bib.raiz / 'backup')

    def test_versao_futura_nao_regravada(self):
        with sqlite3.connect(self.bib.banco) as banco: banco.execute('PRAGMA user_version=2')
        with self.assertRaisesRegex(ValueError, 'Versão'): BibliotecaVozes(self.bib.raiz)
        with sqlite3.connect(self.bib.banco) as banco:
            self.assertEqual(banco.execute('PRAGMA user_version').fetchone()[0], 2)

    def test_falha_transacao_nao_deixa_tomada_publicada(self):
        with patch.object(self.bib, '_conectar', side_effect=sqlite3.OperationalError('falha simulada')):
            with self.assertRaises(sqlite3.Error): self.importar()
        self.assertEqual(list((self.bib.raiz / 'referencias').iterdir()), [])
        self.assertEqual(self.bib.listar(), [])

    def test_limpeza_e_avisos_sao_derivados(self):
        criar_wav(self.wav, silencioso=True)
        perfil = self.importar(limpar=True)
        identidade = perfil['documento']['id']
        self.assertTrue(perfil['audio']['limpeza_aplicada'])
        self.assertNotEqual(self.bib.resolver(identidade), self.bib.resolver(identidade, original=True))
        self.assertIn('silencio_ou_nivel_muito_baixo', perfil['audio']['metricas']['avisos'])
        self.assertEqual(self.wav.read_bytes(), self.bib.resolver(identidade, original=True).read_bytes())

    def test_mp3_decodificado_pelo_ffmpeg_real(self):
        from biblioteca_vozes import ffmpeg_disponivel
        mp3 = self.root / 'amostra.mp3'
        subprocess.run([ffmpeg_disponivel(), '-nostdin', '-y', '-loglevel', 'error', '-i', str(self.wav), str(mp3)], check=True)
        perfil = self.importar(origem=mp3)
        self.assertEqual(perfil['audio']['metricas']['taxa_hz'], 24000)

    def test_limite_duracao_nao_importa_audio_truncado(self):
        from biblioteca_vozes import medir
        criar_wav(self.wav, duracao=76)
        with self.assertRaisesRegex(ValueError, '75 segundos'): medir(self.wav)

    def test_argumentos_gui_enviam_id_e_nao_voz_conflitante(self):
        args = argumentos_sintese({'entrada': 'texto.txt', 'modo': 'analisar',
                                   'configuracao': {'saida': 'audio', 'perfil_voz': 'id-1', 'voz': 'antiga.wav'}})
        self.assertIn('--perfil-voz', args); self.assertNotIn('--voz', args)

    def test_cli_confere_perfil_antes_modelo_e_detecta_alteracao(self):
        import tts
        perfil = self.importar(); identidade = perfil['documento']['id']
        roteiro = self.root / 'roteiro.txt'; roteiro.write_text('Olá mundo.', encoding='utf-8')
        argv = [str(roteiro), '--perfil-voz', identidade, '--analisar']
        with patch.dict(os.environ, {'TTSBR_HOME': str(self.home)}), contextlib.redirect_stdout(io.StringIO()):
            tts.main(argv)
            self.bib.resolver(identidade).write_bytes(b'alterada')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as erro:
                tts.main(argv)
            self.assertEqual(erro.exception.code, 2)

    def test_perfil_em_sintese_simulada_e_cache_por_referencia(self):
        import tts
        import numpy as np
        from unittest.mock import MagicMock
        perfil = self.importar(); identidade = perfil['documento']['id']
        roteiro = self.root / 'narracao.txt'; roteiro.write_text('Olá mundo.', encoding='utf-8')
        modelo = MagicMock()
        modelo.tts.return_value = np.sin(np.arange(2400) * .1) * .1
        argv = [str(roteiro), '--perfil-voz', identidade, '--formatos', 'wav',
                '--saida', str(self.root / 'audio')]
        with patch.dict(os.environ, {'TTSBR_HOME': str(self.home)}), contextlib.redirect_stdout(io.StringIO()):
            tts.main(argv, modelo_precarregado=modelo)
            self.assertEqual(modelo.tts.call_count, 1)
            self.assertEqual(modelo.tts.call_args.kwargs['speaker_wav'], str(self.bib.resolver(identidade)))
            tts.main(argv, modelo_precarregado=modelo)
            self.assertEqual(modelo.tts.call_count, 1)
            criar_wav(self.wav, silencioso=True)
            outro = self.importar()['documento']['id']
            argv[argv.index('--perfil-voz') + 1] = outro
            tts.main(argv, modelo_precarregado=modelo)
            self.assertEqual(modelo.tts.call_count, 2)

    def test_worker_importa_sem_carregar_modelo(self):
        pedido = salvar_pedido('biblioteca_importar', '', {
            'raiz': str(self.bib.raiz), 'arquivo': str(self.wav), 'nome': 'Via worker',
            'idioma': 'pt', 'estilo': 'neutra', 'autorizacao': True}, pasta=self.root / 'pedidos')
        resultado = subprocess.run([sys.executable, '-B', str(ROOT / 'gui_worker.py'), str(pedido)],
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        eventos = [interpretar_linha(l) for l in resultado.stdout.splitlines()]
        identidade = next(e['id'] for e in eventos if e['tipo'] == 'perfil_importado')
        self.assertEqual(self.bib.obter(identidade)['documento']['dados']['nome'], 'Via worker')


if __name__ == '__main__': unittest.main()
