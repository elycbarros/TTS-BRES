"""Supervisão real de workers falsos; não exige modelo, rede ou voz pessoal."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from comparar_motores_e4 import executar, verificar_pesos

WORKER = '''
import json,sys,time,wave
from pathlib import Path
pedido=json.load(sys.stdin)
ACAO
'''


class TestComparacaoE4(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.modelo = self.root / 'modelo'; self.modelo.mkdir()
        self.registrar('config.json', b'{"modelo": "falso"}', 'git')
        self.registrar('model.safetensors', b'pesos falsos', 'lfs')
        self.ref = self.root / 'referência.wav'; self.ref.write_bytes('referência autorizada'.encode())
        self.worker = self.root / 'worker.py'
        self.destino = self.root / 'resultado.wav'

    def registrar(self, rel, conteudo, tipo, revisao='revisao-teste'):
        """Simula um download do Hugging Face em diretório local, com ETag correspondente."""
        caminho = self.modelo / rel
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(conteudo)
        if tipo == 'lfs':
            etag = hashlib.sha256(conteudo).hexdigest()
        else:
            etag = hashlib.sha1(b'blob %d\0' % len(conteudo) + conteudo).hexdigest()
        meta = self.modelo / '.cache' / 'huggingface' / 'download' / (rel + '.metadata')
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(f'{revisao}\n{etag}\n1794057740.0\n', encoding='utf-8')

    def preparar(self, acao):
        self.worker.write_text(WORKER.replace('ACAO', acao), encoding='utf-8')

    def executar(self, **kwargs):
        return executar(sys.executable, self.modelo, self.ref, 'Minha voz.', 'Olá mundo.',
                        'pt', self.destino, 'revisao-teste', worker=self.worker, **kwargs)

    def sucesso(self, adicional=''):
        self.preparar("""with wave.open(pedido['saida'],'wb') as a:
 a.setparams((1,2,24000,0,'NONE','not compressed')); a.writeframes(bytes(4800))
print(json.dumps({'resultado':{'motor':'omnivoice_experimental','carga_s':2,'primeira_sintese_s':1,'sintese_quente_s':.5}}))
""" + adicional)

    def test_worker_real_separado_gera_relatorio_e_wav(self):
        self.sucesso()
        resultado = self.executar()
        self.assertTrue(self.destino.exists())
        self.assertEqual(resultado['duracao_s'], .1)
        self.assertEqual(resultado['rtf_quente'], 5)
        self.assertEqual(resultado['revisao_modelo'], 'revisao-teste')
        self.assertTrue(resultado['revisao_verificada'])
        self.assertEqual(resultado['pesos_arquivos_verificados'], 2)
        self.assertEqual(len(resultado['pesos_manifesto_sha256']), 64)
        self.assertNotIn('Olá mundo.', json.dumps(resultado))
        self.assertNotIn('Minha voz.', json.dumps(resultado))

    def test_preserva_saida_existente_antes_e_durante_execucao(self):
        self.sucesso()
        self.destino.write_bytes(b'existente')
        with self.assertRaises(FileExistsError): self.executar()
        self.assertEqual(self.destino.read_bytes(), b'existente')
        self.destino.unlink()
        self.sucesso('Path(' + repr(str(self.destino)) + ").write_bytes(b'concorrente')\n")
        with self.assertRaises(FileExistsError): self.executar()
        self.assertEqual(self.destino.read_bytes(), b'concorrente')

    def test_falha_sem_worker_e_resposta_malformada(self):
        with self.assertRaisesRegex(ValueError, 'Worker'): self.executar()
        self.preparar("print('não é JSON')")
        with self.assertRaisesRegex(ValueError, 'Resposta'): self.executar()
        self.assertFalse(self.destino.exists())
        self.preparar('sys.exit(3)')
        with self.assertRaises(RuntimeError): self.executar()
        self.assertFalse(self.destino.exists())

    def test_timeout_e_falha_nao_publicam_arquivo(self):
        self.preparar('time.sleep(10)')
        with self.assertRaises(TimeoutError): self.executar(timeout=.2)
        self.assertFalse(self.destino.exists())

    def test_referencia_alterada_nao_publica(self):
        self.sucesso("Path(pedido['referencia']).write_bytes(b'alterada')\n")
        with self.assertRaisesRegex(ValueError, 'mudou'): self.executar()
        self.assertFalse(self.destino.exists())

    def test_timeout_e_identificacao_invalidos(self):
        self.sucesso()
        for valor in (0, float('nan'), True):
            with self.subTest(valor=valor), self.assertRaises(ValueError): self.executar(timeout=valor)

    def test_verificacao_de_pesos_aceita_download_integro(self):
        resultado = verificar_pesos(self.modelo, 'revisao-teste')
        self.assertEqual(resultado['pesos_arquivos_verificados'], 2)
        (self.modelo / '._model.safetensors').write_bytes(b'AppleDouble do exFAT')
        self.assertEqual(verificar_pesos(self.modelo, 'revisao-teste'), resultado)

    def test_verificacao_de_pesos_recusa_revisao_conteudo_e_arquivos_divergentes(self):
        with self.assertRaisesRegex(ValueError, 'outra revisão'):
            verificar_pesos(self.modelo, 'outra')
        (self.modelo / 'model.safetensors').write_bytes(b'pesos adulterados')
        with self.assertRaisesRegex(ValueError, 'não corresponde'):
            verificar_pesos(self.modelo, 'revisao-teste')
        self.registrar('model.safetensors', b'pesos falsos', 'lfs')
        (self.modelo / 'extra.bin').write_bytes(b'sem registro')
        with self.assertRaisesRegex(ValueError, 'não conferem'):
            verificar_pesos(self.modelo, 'revisao-teste')
        (self.modelo / 'extra.bin').unlink()
        (self.modelo / 'config.json').unlink()
        with self.assertRaisesRegex(ValueError, 'não conferem'):
            verificar_pesos(self.modelo, 'revisao-teste')

    def test_pesos_sem_metadados_nao_iniciam_worker(self):
        self.sucesso()
        shutil.rmtree(self.modelo / '.cache')
        with self.assertRaisesRegex(ValueError, 'metadados'): self.executar()
        self.assertFalse(self.destino.exists())


if __name__ == '__main__': unittest.main()
