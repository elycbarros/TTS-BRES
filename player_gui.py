"""Controles de reprodução embutidos com visualização de forma de onda (waveform)."""
import queue
import tkinter as tk
from tkinter import ttk

from reproducao import ProcessoPlayer, calcular_envelope_wav


class JanelaPlayer:
    def __init__(self, parent, python, caminho, externo, inicio=0):
        self.player = ProcessoPlayer()
        self.caminho = caminho
        self.janela = tk.Toplevel(parent)
        self.janela.title('Revisão de áudio')
        self.janela.geometry('600x290')
        self.janela.minsize(480, 240)
        self.atualizando = False
        self.posicao = tk.DoubleVar(value=0)
        self.duracao = 0.0
        self.status = tk.StringVar(value='Abrindo áudio…')
        self.envelope = None
        self.cursor_id = None

        painel = ttk.Frame(self.janela, padding=15)
        painel.pack(fill='both', expand=True)

        ttk.Label(painel, text=str(caminho), wraplength=560).pack(fill='x')

        self.canvas_largura = 560
        self.canvas_altura = 68
        self.canvas = tk.Canvas(painel, height=self.canvas_altura, bg='#1a1b1e',
                                highlightthickness=1, highlightbackground='#343a40', cursor='hand2')
        self.canvas.pack(fill='x', pady=(10, 4))
        self.canvas.bind('<Configure>', self._redimensionar_waveform)
        self.canvas.bind('<Button-1>', self._ao_clicar_waveform)
        self.canvas.bind('<B1-Motion>', self._ao_clicar_waveform)

        self.slider = ttk.Scale(painel, variable=self.posicao, from_=0, to=1, command=self.buscar)
        self.slider.pack(fill='x', pady=(2, 10))

        barra = ttk.Frame(painel)
        barra.pack(fill='x')
        for titulo, acao in [('Reproduzir', 'reproduzir'), ('Pausar', 'pausar'), ('Parar', 'parar')]:
            ttk.Button(barra, text=titulo, command=lambda a=acao: self.enviar(a)).pack(side='left', padx=3)
        ttk.Button(barra, text='Player do sistema', command=lambda: externo(caminho)).pack(side='right')

        ttk.Label(painel, textvariable=self.status, wraplength=560).pack(fill='x', pady=8)

        self.janela.protocol('WM_DELETE_WINDOW', self.fechar)

        try:
            self.envelope = calcular_envelope_wav(caminho, colunas=240)
            self.duracao = self.envelope['duracao_s']
            self.slider.configure(to=self.duracao)
        except Exception:
            self.envelope = None

        try:
            self.player.iniciar(python, caminho, inicio)
        except (ValueError, OSError) as exc:
            self.status.set(str(exc))

        self._desenhar_waveform()
        self.after_id = self.janela.after(100, self.eventos)

    def _desenhar_waveform(self):
        self.canvas.delete('all')
        largura = self.canvas.winfo_width()
        if largura <= 1:
            largura = self.canvas_largura
        altura = self.canvas_altura
        meio_y = altura / 2

        self.canvas.create_line(0, meio_y, largura, meio_y, fill='#2c3036', width=1)

        if self.envelope and self.envelope.get('colunas'):
            cols = self.envelope['colunas']
            n_cols = len(cols)
            dx = largura / n_cols
            bw = max(1.0, dx - 0.5)

            for i, col in enumerate(cols):
                x = i * dx
                pico = col['pico']
                rms = col['rms']
                h_pico = max(2.0, pico * (meio_y - 3))
                h_rms = max(1.0, rms * (meio_y - 3))

                if col['saturado']:
                    cor_pico = '#e05040'
                    cor_rms = '#ff7b72'
                elif col['silencio']:
                    cor_pico = '#3d444d'
                    cor_rms = '#30363d'
                else:
                    cor_pico = '#388bfd'
                    cor_rms = '#79c0ff'

                self.canvas.create_rectangle(x, meio_y - h_pico, x + bw, meio_y + h_pico,
                                            fill=cor_pico, outline='')
                if h_rms < h_pico:
                    self.canvas.create_rectangle(x, meio_y - h_rms, x + bw, meio_y + h_rms,
                                                fill=cor_rms, outline='')

        pos = self.posicao.get()
        cx = (pos / self.duracao * largura) if self.duracao > 0 else 0
        self.cursor_id = self.canvas.create_line(cx, 0, cx, altura, fill='#ff3b30', width=2)

    def _redimensionar_waveform(self, _event=None):
        self._desenhar_waveform()

    def _ao_clicar_waveform(self, event):
        largura = self.canvas.winfo_width()
        if largura > 0 and self.duracao > 0:
            fracao = max(0.0, min(1.0, event.x / largura))
            segundos = fracao * self.duracao
            self.posicao.set(segundos)
            self._atualizar_cursor(segundos)
            self.buscar(segundos)

    def _atualizar_cursor(self, segundos):
        if self.cursor_id and self.duracao > 0:
            largura = self.canvas.winfo_width()
            cx = max(0.0, min(float(largura), (segundos / self.duracao) * largura))
            self.canvas.coords(self.cursor_id, cx, 0, cx, self.canvas_altura)

    def enviar(self, acao, **dados):
        try:
            self.player.enviar(acao, **dados)
        except ValueError as exc:
            self.status.set(str(exc))

    def buscar(self, valor):
        if not self.atualizando:
            seg = float(valor)
            self._atualizar_cursor(seg)
            self.enviar('buscar', segundos=seg)

    def eventos(self):
        try:
            while True:
                evento = self.player.eventos.get_nowait()
                if evento.get('tipo') == 'erro':
                    self.status.set(evento['mensagem'])
                elif evento.get('tipo') == 'posicao':
                    self.atualizando = True
                    self.duracao = evento['duracao']
                    self.slider.configure(to=evento['duracao'])
                    self.posicao.set(evento['segundos'])
                    self._atualizar_cursor(evento['segundos'])
                    self.atualizando = False
                    estado = 'Pausado' if evento['pausado'] else 'Reproduzindo'
                    self.status.set(f"{estado} · {evento['segundos']:.1f}s / {evento['duracao']:.1f}s")
        except queue.Empty:
            pass
        if self.janela.winfo_exists():
            self.after_id = self.janela.after(100, self.eventos)

    def fechar(self):
        self.janela.after_cancel(self.after_id)
        try:
            self.player.fechar()
        finally:
            self.janela.destroy()
