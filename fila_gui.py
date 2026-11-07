"""Consulta e operação da fila persistente, inclusive enquanto a janela principal trabalha."""
from pathlib import Path
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from gui_core import salvar_pedido
from tarefas import LIMITES


class JanelaFila:
    def __init__(self, parent, fila, python):
        self.fila, self.python = fila, python
        self.ocupada = False
        self.retornos = queue.Queue()
        self.janela = tk.Toplevel(parent); self.janela.title('Fila persistente do TTSBR')
        self.janela.geometry('920x550')
        self.janela.transient(parent)
        self.janela.protocol('WM_DELETE_WINDOW', self.fechar)
        painel = ttk.Frame(self.janela, padding=12); painel.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(painel, columns=('rotulo', 'estado', 'tentativa', 'erro'), show='headings')
        for c, tamanho in [('rotulo',180), ('estado',170), ('tentativa',60), ('erro',350)]:
            self.tree.heading(c, text=c.capitalize()); self.tree.column(c, width=tamanho)
        scroll = ttk.Scrollbar(painel, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); self.tree.pack(fill='both', expand=True)
        barra = ttk.Frame(painel); barra.pack(fill='x', pady=10)
        for texto, acao in [('Adicionar projeto…', self.adicionar), ('Iniciar fila', self.iniciar),
                            ('Interromper', lambda: self.acao('interromper')),
                            ('Cancelar à força', lambda: self.acao('cancelar')), ('Retomar', lambda: self.acao('retomar'))]:
            ttk.Button(barra, text=texto, command=acao).pack(side='left', padx=3)
        tempos = ttk.LabelFrame(painel, text='Limites por etapa, em segundos, para novas tarefas', padding=8)
        tempos.pack(fill='x')
        self.limites = {k: tk.StringVar(value=str(v)) for k,v in LIMITES.items()}
        for coluna, (chave, var) in enumerate(self.limites.items()):
            ttk.Label(tempos, text=chave.capitalize()).grid(row=0, column=coluna, padx=5)
            ttk.Entry(tempos, textvariable=var, width=10).grid(row=1, column=coluna, padx=5)
        self.status = tk.StringVar(value='A fila continua em execução ao fechar esta janela. Estados e arquivos são privados.')
        ttk.Label(painel, textvariable=self.status, wraplength=840).pack(fill='x', pady=8)
        self.atualizar()

    def erro(self, exc): messagebox.showerror('Fila de tarefas', str(exc), parent=self.janela)

    def atualizar(self):
        try:
            selecionados = self.tree.selection()
            dados = self.fila.listar()
            atuais = {d['id'] for d in dados}
            for identidade in self.tree.get_children():
                if identidade not in atuais: self.tree.delete(identidade)
            for tarefa in dados:
                valores = (tarefa['rotulo'], tarefa['estado'], tarefa['tentativa'], tarefa['erro'] or '')
                if self.tree.exists(tarefa['id']): self.tree.item(tarefa['id'], values=valores)
                else: self.tree.insert('', 'end', iid=tarefa['id'], values=valores)
            for identidade in selecionados:
                if self.tree.exists(identidade): self.tree.selection_set(identidade)
            while True:
                try: identidade, erro = self.retornos.get_nowait()
                except queue.Empty: break
                self.ocupada = False
                if erro: self.erro(erro); self.status.set('Não foi possível enfileirar o projeto.')
                else:
                    self.status.set('Projeto capturado e enfileirado: ' + identidade)
                    self.fila.iniciar_coordenador()
        except (OSError, ValueError, sqlite3.Error) as exc: self.status.set(str(exc))
        self.after_id = self.janela.after(500, self.atualizar)

    def iniciar(self):
        self.fila.iniciar_coordenador(); self.status.set('Coordenador solicitado. A execução é serial.')

    def adicionar(self):
        if self.ocupada: return
        caminho = filedialog.askopenfilename(parent=self.janela, title='Projeto salvo para enfileirar', filetypes=[('Projeto','projeto.json')])
        if not caminho: return
        try: limites = {k: float(v.get()) for k,v in self.limites.items()}
        except ValueError as exc: self.erro(exc); return
        self.ocupada = True
        self.status.set('Capturando o projeto salvo e suas referências…')
        def rodar():
            try:
                from projetos import Projeto
                projeto = Projeto.abrir(caminho)
                if not projeto.estado['segmentos']: raise ValueError('Confira e salve o roteiro do projeto antes de enfileirar.')
                cfg = projeto.preparar_execucao()
                origem = projeto.estado['origem']
                origem = projeto.caminho.parent / origem if origem else None
                pedido = salvar_pedido('gerar', projeto.documento['dados']['roteiro'], cfg, origem=origem,
                                      pasta=self.fila.raiz / 'pedidos')
                identidade = self.fila.enfileirar(self.python, pedido, limites=limites)
                self.retornos.put((identidade, None))
            except Exception as exc: self.retornos.put((None, str(exc)))
        threading.Thread(target=rodar, daemon=True).start()

    def acao(self, acao):
        selecao = self.tree.selection()
        if not selecao: return
        try:
            if acao == 'retomar': self.fila.retomar(selecao[0]); self.iniciar()
            elif acao == 'cancelar':
                if messagebox.askyesno('Cancelar tarefa', 'Encerrar o worker e seus filhos? Os segmentos já verificados e as tomadas anteriores serão preservados.', parent=self.janela):
                    self.fila.solicitar(selecao[0], forcar=True)
            else: self.fila.solicitar(selecao[0])
        except (OSError, ValueError, sqlite3.Error) as exc: self.erro(exc)

    def fechar(self):
        if self.ocupada:
            self.erro('Aguarde a captura do snapshot terminar antes de fechar.'); return
        self.janela.after_cancel(self.after_id); self.janela.destroy()
