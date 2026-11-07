"""Controles de reprodução embutidos; áudio no Python selecionado para síntese."""
import queue
import tkinter as tk
from tkinter import ttk

from reproducao import ProcessoPlayer


class JanelaPlayer:
    def __init__(self, parent, python, caminho, externo, inicio=0):
        self.player = ProcessoPlayer()
        self.janela = tk.Toplevel(parent)
        self.janela.title('Revisão de áudio')
        self.janela.geometry('590x200')
        self.atualizando = False
        self.posicao = tk.DoubleVar(value=0)
        self.status = tk.StringVar(value='Abrindo áudio…')
        painel = ttk.Frame(self.janela, padding=15); painel.pack(fill='both', expand=True)
        ttk.Label(painel, text=str(caminho), wraplength=550).pack(fill='x')
        self.slider = ttk.Scale(painel, variable=self.posicao, from_=0, to=1, command=self.buscar)
        self.slider.pack(fill='x', pady=10)
        barra = ttk.Frame(painel); barra.pack(fill='x')
        for titulo, acao in [('Reproduzir', 'reproduzir'), ('Pausar', 'pausar'), ('Parar', 'parar')]:
            ttk.Button(barra, text=titulo, command=lambda a=acao: self.enviar(a)).pack(side='left', padx=3)
        ttk.Button(barra, text='Player do sistema', command=lambda: externo(caminho)).pack(side='right')
        ttk.Label(painel, textvariable=self.status, wraplength=550).pack(fill='x', pady=8)
        self.janela.protocol('WM_DELETE_WINDOW', self.fechar)
        try: self.player.iniciar(python, caminho, inicio)
        except (ValueError, OSError) as exc: self.status.set(str(exc))
        self.after_id = self.janela.after(100, self.eventos)

    def enviar(self, acao, **dados):
        try: self.player.enviar(acao, **dados)
        except ValueError as exc: self.status.set(str(exc))

    def buscar(self, valor):
        if not self.atualizando: self.enviar('buscar', segundos=float(valor))

    def eventos(self):
        try:
            while True:
                evento = self.player.eventos.get_nowait()
                if evento.get('tipo') == 'erro': self.status.set(evento['mensagem'])
                elif evento.get('tipo') == 'posicao':
                    self.atualizando = True
                    self.slider.configure(to=evento['duracao'])
                    self.posicao.set(evento['segundos'])
                    self.atualizando = False
                    estado = 'Pausado' if evento['pausado'] else 'Reproduzindo'
                    self.status.set(f"{estado} · {evento['segundos']:.1f}s / {evento['duracao']:.1f}s")
        except queue.Empty: pass
        if self.janela.winfo_exists(): self.after_id = self.janela.after(100, self.eventos)

    def fechar(self):
        self.janela.after_cancel(self.after_id)
        try: self.player.fechar()
        finally: self.janela.destroy()
