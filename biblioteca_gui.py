"""Janela da biblioteca; importação de áudio no Python de síntese selecionado."""
import queue
import sqlite3
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from biblioteca_vozes import BibliotecaVozes
from gui_core import ROOT, DATA_ROOT, interpretar_linha, salvar_pedido


class JanelaBiblioteca:
    def __init__(self, parent, python, selecionar, abrir):
        self.biblioteca = BibliotecaVozes()
        self.biblioteca.listar()  # Rejeita biblioteca ilegível antes de abrir uma janela modal.
        self.python, self.selecionar, self.abrir = python, selecionar, abrir
        self.janela = tk.Toplevel(parent)
        self.janela.title('Biblioteca privada de vozes')
        self.janela.geometry('850x710')
        self.janela.transient(parent)
        self.janela.grab_set()
        self.janela.protocol('WM_DELETE_WINDOW', self.fechar)
        self.ocupada = False
        self.fila = queue.Queue()
        self.perfis = {}
        self.campos = {k: tk.StringVar(value=v) for k, v in
                       {'nome': '', 'idioma': 'pt', 'estilo': 'neutra', 'arquivo': ''}.items()}
        self.autorizada = tk.BooleanVar(value=False)
        self.limpar = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Cada importação cria uma tomada independente. As vozes ficam fora do Git.')
        painel = ttk.Frame(self.janela, padding=14); painel.pack(fill='both', expand=True)
        self.lista = ttk.Treeview(painel, columns=('nome', 'idioma', 'estilo'), show='headings', height=6)
        for chave in ('nome', 'idioma', 'estilo'):
            self.lista.heading(chave, text=chave.capitalize())
        scroll = ttk.Scrollbar(painel, orient='vertical', command=self.lista.yview)
        self.lista.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); self.lista.pack(fill='both', expand=True)
        self.lista.bind('<<TreeviewSelect>>', self.mostrar)
        form = ttk.Frame(painel); form.pack(fill='x', pady=10)
        for linha, chave in enumerate(('nome', 'idioma', 'estilo', 'arquivo')):
            ttk.Label(form, text=chave.capitalize()).grid(row=linha, column=0, sticky='w', padx=5, pady=2)
            if chave in ('idioma', 'estilo'):
                valores = ('pt', 'es') if chave == 'idioma' else ('neutra', 'expressiva', 'calma')
                entrada = ttk.Combobox(form, textvariable=self.campos[chave], values=valores)
            else:
                entrada = ttk.Entry(form, textvariable=self.campos[chave])
            entrada.grid(row=linha, column=1, sticky='ew', pady=2)
        form.columnconfigure(1, weight=1)
        ttk.Button(form, text='Escolher…', command=self.escolher).grid(row=3, column=2, padx=5)
        ttk.Label(painel, text='Transcrição da referência (opcional, revisável)').pack(anchor='w')
        self.transcricao = tk.Text(painel, height=3, wrap='word'); self.transcricao.pack(fill='x')
        ttk.Checkbutton(painel, text='Tenho autorização para gravar e usar esta voz', variable=self.autorizada).pack(anchor='w')
        ttk.Checkbutton(painel, text='Criar também cópia limpa (original preservado)', variable=self.limpar).pack(anchor='w')
        self.botoes = []
        for itens in ([('Importar nova tomada', self.importar), ('Salvar dados', self.salvar), ('Usar na narração', self.usar)],
                      [('Ouvir referência', self.ouvir), ('Remover perfil', self.remover), ('Backup…', self.backup)]):
            barra = ttk.Frame(painel); barra.pack(fill='x', pady=4)
            for titulo, comando in itens:
                botao = ttk.Button(barra, text=titulo, command=comando); botao.pack(side='left', padx=(0, 5))
                self.botoes.append(botao)
        ttk.Label(painel, textvariable=self.status, wraplength=760).pack(fill='x', pady=8)
        self.atualizar()
        self.janela.after(100, self.eventos)

    def erro(self, erro):
        messagebox.showerror('Biblioteca de vozes', str(erro), parent=self.janela)

    def atualizar(self, identidade=None):
        self.lista.delete(*self.lista.get_children())
        self.perfis = {p['documento']['id']: p for p in self.biblioteca.listar()}
        for chave, perfil in self.perfis.items():
            dados = perfil['documento']['dados']
            self.lista.insert('', 'end', iid=chave, values=tuple(dados[k] for k in ('nome', 'idioma', 'estilo')))
        if identidade in self.perfis:
            self.lista.selection_set(identidade)

    def id_selecionado(self):
        itens = self.lista.selection()
        if not itens: raise ValueError('Selecione um perfil na lista.')
        return itens[0]

    def mostrar(self, _evento=None):
        if self.ocupada: return
        try:
            perfil = self.perfis[self.id_selecionado()]
            dados, audio = perfil['documento']['dados'], perfil['audio']
            for chave in ('nome', 'idioma', 'estilo'): self.campos[chave].set(dados[chave])
            self.transcricao.delete('1.0', 'end'); self.transcricao.insert('1.0', dados['transcricao'])
            self.autorizada.set(dados['autorizacao_declarada'])
            self.limpar.set(audio['limpeza_aplicada'])
            m = audio['metricas']
            fonte = audio.get('original', {})
            original = (f"Original: {fonte['taxa_hz']} Hz · {fonte['canais']} canal(is). "
                        if 'taxa_hz' in fonte else 'Metadados do original indisponíveis. ')
            self.status.set(original + f"Referência preparada: {m['duracao_s']:.1f}s · {m['canais']} canal · "
                            f"{m['taxa_hz']} Hz · {m['bits']} bits. Avisos: {', '.join(m['avisos']) or 'nenhum'}. "
                            'Esses avisos não medem naturalidade nem semelhança da voz.')
        except ValueError:
            pass

    def escolher(self):
        if self.ocupada: return
        caminho = filedialog.askopenfilename(parent=self.janela, filetypes=[('Áudio', '*.wav *.mp3 *.flac *.m4a *.ogg *.aac *.aiff')])
        if caminho: self.campos['arquivo'].set(caminho)

    def executar(self, trabalho, concluir):
        if self.ocupada: return
        self.ocupada = True
        for b in self.botoes: b.configure(state='disabled')
        self.status.set('Processando a biblioteca; aguarde antes de fechar…')
        def rodar():
            try: self.fila.put((concluir, trabalho(), None))
            except Exception as exc: self.fila.put((concluir, None, str(exc)))
        threading.Thread(target=rodar, daemon=True).start()

    def eventos(self):
        try:
            concluir, resultado, erro = self.fila.get_nowait()
            self.ocupada = False
            for b in self.botoes: b.configure(state='normal')
            if erro:
                self.status.set('Operação não concluída. Confira a mensagem.'); self.erro(erro)
            else:
                try: concluir(resultado)
                except (ValueError, OSError, sqlite3.Error) as exc: self.erro(exc)
        except queue.Empty:
            pass
        if self.janela.winfo_exists(): self.janela.after(100, self.eventos)

    def importar(self):
        cfg = {k: v.get() for k, v in self.campos.items()}
        cfg.update(raiz=str(self.biblioteca.raiz), transcricao=self.transcricao.get('1.0', 'end-1c'),
                   autorizacao=self.autorizada.get(), limpar=self.limpar.get())
        if not cfg['autorizacao']:
            self.erro('Confirme a autorização de uso desta voz.'); return
        def trabalho():
            pedido = salvar_pedido('biblioteca_importar', '', cfg, pasta=DATA_ROOT / 'local' / 'gui' / 'biblioteca')
            resposta = subprocess.run([self.python, '-u', str(ROOT / 'gui_worker.py'), str(pedido)],
                                      capture_output=True, text=True, encoding='utf-8', errors='replace',
                                      creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            eventos = [interpretar_linha(linha) for linha in resposta.stdout.splitlines()]
            if resposta.returncode:
                raise ValueError(next((e['mensagem'] for e in eventos if e['tipo'] == 'erro'),
                                      'Falha na importação. Confira o Python selecionado para a síntese.'))
            return next(e['id'] for e in eventos if e['tipo'] == 'perfil_importado')
        self.executar(trabalho, lambda identidade: self.atualizar(identidade))

    def salvar(self):
        try:
            identidade = self.id_selecionado()
            self.biblioteca.atualizar(identidade, nome=self.campos['nome'].get(), idioma=self.campos['idioma'].get(),
                                      estilo=self.campos['estilo'].get(), transcricao=self.transcricao.get('1.0', 'end-1c'))
            self.atualizar(identidade)
        except (ValueError, OSError, sqlite3.Error) as exc: self.erro(exc)

    def usar(self):
        try:
            identidade = self.id_selecionado()
            caminho = self.biblioteca.resolver(identidade)
            self.selecionar(identidade, caminho)
            self.fechar()
        except (ValueError, OSError, sqlite3.Error) as exc: self.erro(exc)

    def ouvir(self):
        try: self.abrir(self.biblioteca.resolver(self.id_selecionado()))
        except (ValueError, OSError, sqlite3.Error) as exc: self.erro(exc)

    def remover(self):
        try:
            identidade = self.id_selecionado()
            if messagebox.askyesno('Remover perfil', 'O perfil sairá da lista. Os arquivos privados serão preservados para recuperação; áudios gerados não serão apagados.', parent=self.janela):
                self.biblioteca.remover(identidade); self.atualizar()
                self.status.set('Perfil removido da lista. Arquivos preservados na biblioteca privada.')
        except (ValueError, OSError, sqlite3.Error) as exc: self.erro(exc)

    def backup(self):
        destino = filedialog.asksaveasfilename(parent=self.janela, title='Novo diretório de backup',
                                              initialdir=str(DATA_ROOT / 'local'), initialfile='backup-vozes')
        if destino:
            self.executar(lambda: str(self.biblioteca.backup(destino)),
                          lambda _resultado: self.status.set('Backup concluído. Ele contém gravações e transcrições privadas.'))

    def fechar(self):
        if self.ocupada:
            self.erro('Aguarde a importação ou o backup terminar antes de fechar.'); return
        self.janela.grab_release(); self.janela.destroy()
