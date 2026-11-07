"""Fila e supervisão com processos reais, snapshots públicos e workers sintéticos."""
import contextlib
import http.client
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from audio_persistente import hash_arquivo
from biblioteca_vozes import BibliotecaVozes
from exclusao import Trava, RecursoOcupado, recursos
from gui_core import ROOT, salvar_pedido
from tarefas import Fila, ClienteFila, TERMINAIS
from test_biblioteca_vozes import criar_wav

WORKER = r'''
import json,os,sys,time,subprocess,wave
from pathlib import Path
sys.path.insert(0, CODIGO)
from tarefas import Fila
from exclusao import recursos
p=Path(sys.argv[1]); doc=json.loads(p.read_text()); cfg=doc['configuracao']; teste=cfg.get('_teste',{})
fila=Fila(os.environ['TTSBR_FILA_RAIZ']); identidade=os.environ['TTSBR_FILA_ID']; tentativa=int(os.environ['TTSBR_FILA_TENTATIVA'])
while not (p.parent/'iniciar.flag').exists(): time.sleep(.01)
traco=Path(teste['traco']) if teste.get('traco') else None
if traco:
 with traco.open('a') as f: f.write(json.dumps({'id':identidade,'evento':'inicio','tempo':time.monotonic()})+'\n')
if teste.get('filho'):
 filho=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
 Path(teste['filho']).write_text(str(filho.pid))
print('TTSBR_EVENT '+json.dumps({'tipo':'etapa','etapa':'sintese','mensagem':'worker sintético'}),flush=True)
if teste.get('falha'): os._exit(3)
if teste.get('sem_recibo'): sys.exit(0)
fim=time.monotonic()+teste.get('tempo',.05)
while time.monotonic()<fim:
 if teste.get('logs'): print('registro sem avanço',flush=True)
 if (p.parent/'interromper.flag').exists():
  ev={'interrompido':{'tipo':'interrompido','concluidos':1}}
  print('TTSBR_EVENT '+json.dumps(ev['interrompido']),flush=True)
  fila.gravar_recibo(identidade,tentativa,'interrompida',ev); sys.exit(0)
 time.sleep(.01)
if doc['modo']=='analisar':
 eventos={'plano':{'tipo':'plano','total':1,'segmentos':[{'id':1,'texto':Path(doc['entrada']).read_text(),'idioma':'pt','locutor':'Luis Moray'}]}}
else:
 base=Path(cfg['saida']); base.parent.mkdir(parents=True,exist_ok=True)
 with recursos(base,cfg.get('cache_segmentos')):
  segmento=base.parent/'seg.wav'
  with wave.open(str(segmento),'wb') as a: a.setparams((1,2,24000,0,'NONE','not compressed')); a.writeframes(bytes(480))
  arquivos=[]
  for ext in cfg.get('formatos','wav').split(','):
   destino=base.parent/(base.name+'.'+ext); destino.write_bytes(segmento.read_bytes()); arquivos.append(str(destino))
  manifesto=base.parent/(base.name+'.blocos.json')
  manifesto.write_text(json.dumps({'estado':'concluido','segmentos':[{'id':1,'arquivo':str(segmento)}]}))
  eventos={'resultado':{'tipo':'resultado','manifesto':str(manifesto),'arquivos':arquivos}}
for evento in eventos.values():
 try: print('TTSBR_EVENT '+json.dumps(evento),flush=True)
 except BrokenPipeError: pass
fila.gravar_recibo(identidade,tentativa,'concluida',eventos)
if teste.get('corromper') and doc['modo']!='analisar': Path(eventos['resultado']['arquivos'][0]).write_bytes(b'alterado')
if traco:
 with traco.open('a') as f: f.write(json.dumps({'id':identidade,'evento':'fim','tempo':time.monotonic()})+'\n')
'''


class TestFila(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.env = patch.dict(os.environ, {'TTSBR_HOME': str(self.root/'dados')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.fila = Fila(self.root/'fila')
        self.worker = self.root/'worker.py'
        self.worker.write_text(WORKER.replace('CODIGO', repr(str(ROOT))), encoding='utf-8')
        self.processos = []; self.addCleanup(self.encerrar)

    def encerrar(self):
        for processo in self.processos:
            if processo.poll() is None:
                processo.terminate()
                try: processo.wait(timeout=5)
                except subprocess.TimeoutExpired: processo.kill(); processo.wait(timeout=5)

    def pedido(self, nome='tarefa', modo='analisar', teste=None, **cfg):
        cfg = {'saida': str(self.root/nome/'audio'), 'formatos':'wav', '_teste':teste or {}, **cfg}
        return salvar_pedido(modo, 'Olá mundo.', cfg, pasta=self.root/'pedidos')

    def adicionar(self, **kwargs):
        limites = kwargs.pop('limites', None)
        return self.fila.enfileirar(sys.executable, self.pedido(**kwargs), limites=limites)

    def coordenador(self, worker=True):
        codigo = ('import sys; sys.path.insert(0,'+repr(str(ROOT))+'); from tarefas import Fila; '
                  'Fila('+repr(str(self.fila.raiz))+').rodar(ocioso=.15,worker='+repr(str(self.worker) if worker else None)+')')
        processo = subprocess.Popen([sys.executable,'-u','-c',codigo], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processos.append(processo); return processo

    def aguardar(self, identidade, estados=TERMINAIS, timeout=8):
        limite = time.monotonic()+timeout
        while time.monotonic()<limite:
            tarefa = self.fila.obter(identidade)
            if tarefa['estado'] in estados: return tarefa
            time.sleep(.02)
        self.fail('Tarefa não atingiu o estado esperado: '+repr(self.fila.obter(identidade)))

    def test_tres_tarefas_seriadas_sobrevivem_reabertura(self):
        traco=self.root/'traco.jsonl'
        ids=[self.adicionar(nome=str(i),teste={'traco':str(traco),'tempo':.1}) for i in range(3)]
        self.assertEqual([r['estado'] for r in Fila(self.fila.raiz).listar()],['aguardando']*3)
        processo=self.coordenador(); processo.wait(timeout=8)
        self.assertEqual([self.fila.obter(i)['estado'] for i in ids],['concluida']*3)
        linhas=[json.loads(l) for l in traco.read_text().splitlines()]
        self.assertEqual([(l['id'],l['evento']) for l in linhas],[(i,e) for i in ids for e in ('inicio','fim')])

    def test_inicializacao_concorrente_de_bancos_novos_e_atomica(self):
        barreira=threading.Barrier(4)
        erros=[]
        def iniciar():
            try:
                barreira.wait(timeout=5)
                Fila(self.root/'fila-nova').listar()
                BibliotecaVozes(self.root/'biblioteca-nova').listar()
            except Exception as exc: erros.append(str(exc))
        threads=[threading.Thread(target=iniciar) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=10)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(erros,[])

    def test_coordenadores_concorrentes_nao_duplicam_tarefa(self):
        traco=self.root/'traco'
        identidade=self.adicionar(teste={'traco':str(traco),'tempo':.25})
        a,b=self.coordenador(),self.coordenador()
        a.wait(timeout=8); b.wait(timeout=8)
        self.assertEqual(self.fila.obter(identidade)['tentativa'],1)
        self.assertEqual(len(traco.read_text().splitlines()),2)

    def test_snapshot_imutavel_texto_glossario_referencia_e_perfil(self):
        voz=self.root/'ref.wav'; criar_wav(voz)
        bib=BibliotecaVozes(); perfil=bib.importar(voz,'Teste',autorizacao=True)['documento']['id']
        pedido=self.pedido(perfil_voz=perfil,glossario_integrado={'Acme':'empresa'})
        identidade=self.fila.enfileirar(sys.executable,pedido)
        original=json.loads(pedido.read_text()); Path(original['entrada']).write_text('Alterado')
        tarefa=self.fila.obter(identidade); snapshot=self.fila.verificar_snapshot(tarefa)
        self.assertEqual(Path(snapshot['entrada']).read_text(),'Olá mundo.')
        self.assertEqual(snapshot['configuracao']['glossario_integrado'],{'Acme':'empresa'})
        self.assertNotIn('perfil_voz',snapshot['configuracao'])
        with self.assertRaisesRegex(ValueError,'vinculado'): bib.remover(perfil)
        self.fila.solicitar(identidade,forcar=True); bib.remover(perfil)

    def test_tag_de_voz_congelada_funciona_apos_original_sumir(self):
        voz=self.root/'ref.wav'; criar_wav(voz)
        pedido=salvar_pedido('analisar',f'[{voz}|pt]: Olá mundo.',{'saida':str(self.root/'audio')},pasta=self.root/'pedidos')
        identidade=self.fila.enfileirar(sys.executable,pedido)
        voz.unlink()
        processo=self.coordenador(worker=False); processo.wait(timeout=8)
        self.assertEqual(self.fila.obter(identidade)['estado'],'concluida',self.fila.obter(identidade)['erro'])

    def test_colisao_de_saida_reservada_e_cancelamento_aguardando(self):
        identidade=self.adicionar(modo='gerar')
        with self.assertRaisesRegex(ValueError,'reservando'): self.adicionar(modo='gerar')
        self.fila.solicitar(identidade,forcar=True)
        self.assertEqual(self.fila.obter(identidade)['estado'],'cancelada')
        outro=self.adicionar(modo='gerar'); self.assertNotEqual(outro,identidade)

    def test_interrupcao_segura_e_retomada_mesmo_snapshot(self):
        identidade=self.adicionar(teste={'tempo':1})
        processo=self.coordenador()
        self.aguardar(identidade,estados=('executando',))
        self.fila.solicitar(identidade)
        self.assertEqual(self.aguardar(identidade)['estado'],'interrompida')
        processo.wait(timeout=8)
        sha=self.fila.obter(identidade)['sha256']
        self.fila.retomar(identidade)
        processo=self.coordenador(); processo.wait(timeout=8)
        tarefa=self.fila.obter(identidade)
        self.assertEqual((tarefa['estado'],tarefa['tentativa'],tarefa['sha256']),('concluida',2,sha))

    def test_cancelamento_forcado_so_termina_apos_worker_sair(self):
        identidade=self.adicionar(teste={'tempo':10})
        processo=self.coordenador()
        self.aguardar(identidade,estados=('executando',)); time.sleep(.15)
        self.fila.solicitar(identidade,forcar=True)
        self.assertEqual(self.aguardar(identidade)['estado'],'cancelada')
        processo.wait(timeout=8)
        with Trava(self.fila.raiz/'recurso.lock'): pass

    def test_timeout_nao_usa_logs_como_progresso_e_fila_continua(self):
        travada=self.adicionar(teste={'tempo':3,'logs':True},limites={'sintese':.2})
        proxima=self.adicionar(nome='outra')
        processo=self.coordenador(); processo.wait(timeout=8)
        self.assertEqual(self.fila.obter(travada)['estado'],'falha')
        self.assertIn('etapa sintese',self.fila.obter(travada)['erro'])
        self.assertEqual(self.fila.obter(proxima)['estado'],'concluida')

    def test_codigo_zero_sem_recibo_nao_significa_conclusao(self):
        identidade=self.adicionar(teste={'sem_recibo':True})
        processo=self.coordenador(); processo.wait(timeout=8)
        self.assertEqual(self.fila.obter(identidade)['estado'],'falha')

    def test_falha_worker_e_recuperacao_na_proxima_tarefa(self):
        identidade=self.adicionar(teste={'falha':True}); outra=self.adicionar(nome='outra')
        processo=self.coordenador(); processo.wait(timeout=8)
        self.assertEqual(self.fila.obter(identidade)['estado'],'falha')
        self.assertEqual(self.fila.obter(outra)['estado'],'concluida')

    def test_snapshot_alterado_falha_sem_bloquear_proxima(self):
        identidade=self.adicionar(); outra=self.adicionar(nome='outra')
        Path(self.fila.obter(identidade)['pedido']).write_text('{}')
        processo=self.coordenador(); processo.wait(timeout=8)
        self.assertEqual(self.fila.obter(identidade)['estado'],'falha')
        self.assertEqual(self.fila.obter(outra)['estado'],'concluida')

    def test_falha_de_disco_na_captura_nao_publica_tarefa(self):
        with patch('tarefas.salvar_json',side_effect=OSError('disco cheio')):
            with self.assertRaises(OSError): self.adicionar()
        self.assertEqual(self.fila.listar(),[])
        self.assertEqual(list((self.fila.raiz/'tarefas').iterdir()),[])

    def test_resultado_alterado_apos_recibo_nao_e_aprovado(self):
        identidade=self.adicionar(modo='gerar',teste={'corromper':True})
        processo=self.coordenador(); processo.wait(timeout=8)
        self.assertEqual(self.fila.obter(identidade)['estado'],'falha')
        self.assertIn('alterado',self.fila.obter(identidade)['erro'])

    def test_snapshot_de_projeto_nao_muda_com_edicao_posterior(self):
        from projetos import Projeto
        projeto=Projeto.criar('Original','Texto original')
        antes=Projeto.abrir(projeto.caminho)
        pedido=self.pedido(_projeto=str(projeto.caminho))
        identidade=self.fila.enfileirar(sys.executable,pedido)
        projeto.atualizar('Novo roteiro',{}, {})
        self.assertFalse(antes.mesmo_conteudo(projeto))
        snapshot=self.fila.verificar_snapshot(self.fila.obter(identidade))
        self.assertEqual(snapshot['_snapshot_projeto']['dados']['roteiro'],'Texto original')

    def test_reconciliacao_de_vinculos_orfaos_nao_afeta_outra_fila(self):
        voz=self.root/'voz.wav'; criar_wav(voz)
        biblioteca=BibliotecaVozes(); perfil=biblioteca.importar(voz,'Teste',autorizacao=True)['documento']['id']
        biblioteca.registrar_uso(perfil,self.fila.dono('orfao'))
        outra=Fila(self.root/'outra-fila')
        identidade=outra.enfileirar(sys.executable,self.pedido(perfil_voz=perfil))
        self.fila.reconciliar_vinculos()
        self.assertEqual(biblioteca.listar_usos(self.fila.dono()),[])
        with self.assertRaises(ValueError): biblioteca.remover(perfil)
        outra.solicitar(identidade,forcar=True); biblioteca.remover(perfil)

    def test_reconciliacao_de_projeto_repara_vinculo_de_gravacao_falha(self):
        from projetos import Projeto
        voz=self.root/'voz.wav'; criar_wav(voz)
        biblioteca=BibliotecaVozes(); perfil=biblioteca.importar(voz,'Teste',autorizacao=True)['documento']['id']
        projeto=Projeto.criar('Teste','Roteiro')
        with patch('projetos.salvar_json',side_effect=OSError('disco cheio')):
            with self.assertRaises(OSError): projeto.atualizar('Novo',{'perfil_voz':perfil},{})
        self.assertTrue(biblioteca.listar_usos(projeto.id))
        projeto.salvar()
        self.assertEqual(biblioteca.listar_usos(projeto.id),[])

    def test_historico_limitado_preserva_artefatos_e_aguardando(self):
        ids=[]
        for i in range(4):
            identidade=self.adicionar(nome=str(i)); ids.append(identidade)
            tarefa=self.fila.preparar(identidade); self.fila.finalizar(tarefa,'concluida',resultado={})
        pendente=self.adicionar(nome='pendente')
        with patch('tarefas.MAX_FINALIZADAS',2): self.fila.limpar_historico()
        self.assertEqual(len(self.fila.listar()),3)
        self.assertEqual(self.fila.obter(pendente)['estado'],'aguardando')
        self.assertTrue((self.fila.raiz/'tarefas'/ids[0]).exists())

    def test_cancelamento_encerra_filho_antes_da_proxima_tarefa(self):
        filho=self.root/'filho.pid'
        antiga=self.adicionar(teste={'tempo':10,'filho':str(filho)})
        proxima=self.adicionar(nome='proxima')
        processo=self.coordenador()
        limite=time.monotonic()+5
        while not filho.exists() and time.monotonic()<limite: time.sleep(.02)
        self.assertTrue(filho.exists())
        self.fila.solicitar(antiga,forcar=True)
        self.assertEqual(self.aguardar(antiga)['estado'],'cancelada')
        self.assertEqual(self.aguardar(proxima)['estado'],'concluida')
        if os.name!='nt':
            with self.assertRaises(ProcessLookupError): os.kill(int(filho.read_text()),0)
        processo.wait(timeout=8)

    def test_retomada_nao_refaz_segmentos_ja_verificados(self):
        identidade=self.adicionar(refazer=True,refazer_segmentos='1,2')
        tarefa=self.fila.preparar(identidade)
        self.fila.finalizar(tarefa,'falha','falha simulada')
        self.fila.retomar(identidade)
        nova=self.fila.preparar(identidade)
        cfg=json.loads(Path(nova['pedido_tentativa']).read_text())['configuracao']
        self.assertFalse(cfg['refazer']); self.assertNotIn('refazer_segmentos',cfg)

    def test_recuperacao_sem_worker_nao_deixa_estado_executando(self):
        identidade=self.adicionar(); self.fila.preparar(identidade)
        processo=self.coordenador(); processo.wait(timeout=8)
        self.assertEqual(self.fila.obter(identidade)['estado'],'interrompida')

    def test_eventos_limitados_e_versao_futura_preservada(self):
        identidade=self.adicionar()
        with patch('tarefas.MAX_EVENTOS',5):
            for i in range(12): self.fila.evento(identidade,{'tipo':'log','texto':str(i)})
        self.assertEqual(len(self.fila.eventos_desde(identidade)),5)
        with sqlite3.connect(self.fila.banco) as db: db.execute('PRAGMA user_version=9')
        with self.assertRaises(ValueError): Fila(self.fila.raiz)
        with sqlite3.connect(self.fila.banco) as db: self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],9)

    def test_cliente_gui_recebe_eventos_sem_depender_do_worker_na_janela(self):
        cliente=ClienteFila(self.fila)
        with patch.object(self.fila,'iniciar_coordenador',side_effect=self.coordenador):
            identidade=cliente.iniciar(sys.executable,self.pedido())
            vistos=[]
            limite=time.monotonic()+8
            while time.monotonic()<limite:
                e=cliente.eventos.get(timeout=5); vistos.append(e)
                if e['tipo']=='processo_encerrado': break
        self.assertEqual(vistos[-1]['codigo'],0)
        self.assertTrue(any(e['tipo']=='plano' for e in vistos))
        self.assertFalse(cliente.ativo)

    def test_trava_de_saida_impede_cli_independente_e_e_reentrante(self):
        base=self.root/'saida'
        with recursos(base):
            with recursos(base): pass
            codigo='import sys; sys.path.insert(0,'+repr(str(ROOT))+'); from exclusao import recursos;\nwith recursos('+repr(str(base))+'): pass'
            r=subprocess.run([sys.executable,'-c',codigo],capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0)
            entrada=self.root/'texto.txt'; entrada.write_text('Olá mundo.')
            cli=subprocess.run([sys.executable,str(ROOT/'tts.py'),str(entrada),'--saida',str(base)],capture_output=True,text=True)
            self.assertNotEqual(cli.returncode,0)
            self.assertIn('Recurso em uso',cli.stderr)
        with recursos(base): pass

    @unittest.skipIf(os.name=='nt','Ensaio POSIX de herança de trava; Windows depende de Job Object e teste real.')
    def test_queda_coordenador_nao_inicia_outro_worker_antes_de_liberar_trava(self):
        traco=self.root/'traco'
        antigo=self.adicionar(teste={'tempo':1,'traco':str(traco)})
        proxima=self.adicionar(nome='outra',teste={'traco':str(traco)})
        processo=self.coordenador()
        limite=time.monotonic()+5
        while not traco.exists() and time.monotonic()<limite: time.sleep(.02)
        self.assertTrue(traco.exists())
        processo.kill(); processo.wait(timeout=5)
        with self.assertRaises(RecursoOcupado): Trava(self.fila.raiz/'recurso.lock').adquirir()
        novo=self.coordenador(); novo.wait(timeout=8)
        self.assertEqual(self.fila.obter(antigo)['estado'],'concluida')
        self.assertEqual(self.fila.obter(proxima)['estado'],'concluida')
        eventos=[json.loads(l) for l in traco.read_text().splitlines()]
        self.assertEqual([(e['id'],e['evento']) for e in eventos],[(antigo,'inicio'),(antigo,'fim'),(proxima,'inicio'),(proxima,'fim')])

    def test_guardiao_aceita_cancelar_apos_queda_do_coordenador(self):
        traco=self.root/'traco'
        antiga=self.adicionar(teste={'tempo':10,'traco':str(traco)})
        proxima=self.adicionar(nome='seguinte')
        processo=self.coordenador()
        limite=time.monotonic()+5
        while not traco.exists() and time.monotonic()<limite: time.sleep(.02)
        self.assertTrue(traco.exists())
        processo.kill(); processo.wait(timeout=5)
        self.fila.solicitar(antiga,forcar=True)
        novo=self.coordenador(); novo.wait(timeout=8)
        self.assertEqual(self.fila.obter(antiga)['estado'],'cancelada')
        self.assertEqual(self.fila.obter(proxima)['estado'],'concluida')

    def test_api_http_e_gui_compartilham_fila_e_origem_de_eventos(self):
        import servidor_api
        traco=self.root/'traco'
        gui=self.adicionar(teste={'tempo':.2,'traco':str(traco)})
        servidor=servidor_api.criar_servidor('127.0.0.1',0,self.root/'api','cpu',fila=self.fila)
        thread=threading.Thread(target=servidor.serve_forever,daemon=True); thread.start()
        try:
            with patch.object(self.fila,'iniciar_coordenador',side_effect=self.coordenador):
                conn=http.client.HTTPConnection('127.0.0.1',servidor.server_port,timeout=8)
                conn.request('POST','/v1/audio/speech',json.dumps({'input':'Olá mundo.','response_format':'wav'}),{'Content-Type':'application/json'})
                resposta=conn.getresponse(); corpo=resposta.read(); conn.close()
            self.assertEqual(resposta.status,200,corpo)
            self.assertTrue(corpo.startswith(b'RIFF'))
            tarefas=self.fila.listar()
            self.assertEqual(len(tarefas),2)
            self.assertEqual([t['estado'] for t in tarefas],['concluida','concluida'])
            self.assertEqual(tarefas[0]['id'],gui)
        finally:
            servidor.shutdown(); servidor.server_close(); thread.join(timeout=5)


if __name__=='__main__': unittest.main()
