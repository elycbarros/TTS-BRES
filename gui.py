#!/usr/bin/env python3
"""Janela local do TTSBR. Execute com um Python que tenha Tkinter."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys

from gui_core import ROOT, ProcessoTrabalho, python_padrao, salvar_pedido


def abrir_no_sistema(caminho):
    caminho = Path(caminho).resolve()
    if not caminho.exists():
        raise FileNotFoundError(f'Arquivo não encontrado: {caminho}')
    if sys.platform == 'win32':
        os.startfile(str(caminho))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(caminho)])
    else:
        subprocess.Popen(['xdg-open', str(caminho)])


def iniciar_janela():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
        from tkinter.scrolledtext import ScrolledText
    except ImportError:
        print('Este Python não possui Tkinter. Consulte docs/GUI.md para instalar ou usar outro Python.', file=sys.stderr)
        return 1

    class Aplicativo:
        def __init__(self, janela):
            self.root = janela
            janela.title('TTSBR · Narração local')
            janela.geometry('1180x800')
            janela.minsize(980, 700)
            self.processo = ProcessoTrabalho()
            self.ocupado = False
            self.modo = None
            self.origem = None
            self.manifesto = None
            self.arquivos = []
            self.segmentos = {}
            self.fechar_depois = False
            self.dirty = False
            self.preferencias = ROOT / 'local' / 'gui' / 'preferencias.json'
            self.vars = {}
            defaults = {'python': python_padrao(), 'saida': str(ROOT / 'saida' / 'narracao'),
                        'idioma': 'auto', 'locutor': 'Automática', 'voz': '', 'vozes_personagens': '',
                        'vozes_tons': '', 'glossario': '', 'trilha': '', 'volume_trilha': '-18',
                        'formatos': 'mp3,wav', 'velocidade': '1.1',
                        'volume_alvo': '-20', 'lufs': '', 'taxa_amostragem': '24000', 'max_tentativas': '2',
                        'dispositivo': 'auto', 'pausa_frase': '600', 'pausa_reticencias': '850',
                        'pausa_ponto_virgula': '420', 'pausa_virgula': '250',
                        'pausa_paragrafo': '1150', 'pausa_bloco': '500',
                        'sem_normalizar': False, 'sem_corte_silencio': False,
                        'limpar_referencia': False, 'refazer': False}
            try:
                cfg = json.loads(self.preferencias.read_text(encoding='utf-8'))
                defaults.update({k: v for k, v in cfg.items() if k in defaults})
            except (OSError, ValueError, AttributeError):
                pass
            for k, v in defaults.items():
                self.vars[k] = tk.BooleanVar(value=v) if isinstance(v, bool) else tk.StringVar(value=v)
            self.status = tk.StringVar(value='Abra um roteiro ou escreva abaixo para começar.')
            self.contagem = tk.StringVar(value='0 palavras')
            self.detalhe = tk.StringVar(value='Selecione um segmento para conferir seu texto.')
            self.resultado_ref = tk.StringVar(value='Nenhum resultado associado. Gere um áudio ou abra um manifesto.')
            self.editaveis = []
            self._estilo()
            self._construir()
            janela.protocol('WM_DELETE_WINDOW', self._fechar)
            for mod in ('Control', 'Command') if sys.platform == 'darwin' else ('Control',):
                janela.bind(f'<{mod}-o>', lambda e: self._abrir())
                janela.bind(f'<{mod}-s>', lambda e: self._salvar())
            janela.after(120, self._eventos)

        def _estilo(self):
            s = ttk.Style()
            s.theme_use('clam')
            s.configure('.', font=('Helvetica', 11), background='#f3f6fa', foreground='#18283b')
            s.configure('TButton', padding=(10, 7))
            s.configure('Primary.TButton', background='#126c68', foreground='white', padding=(14, 10))
            s.map('Primary.TButton', background=[('active', '#0b5552'), ('disabled', '#b4c5c9')])
            s.configure('Title.TLabel', font=('Helvetica', 24, 'bold'))
            s.configure('Sub.TLabel', foreground='#536478')
            s.configure('Section.TLabel', font=('Helvetica', 12, 'bold'))
            s.configure('Treeview', rowheight=29, background='white', fieldbackground='white')
            s.configure('TNotebook.Tab', padding=(16, 9))

        def _construir(self):
            shell = ttk.Frame(self.root, padding=20)
            shell.pack(fill='both', expand=True)
            head = ttk.Frame(shell)
            head.pack(fill='x', pady=(0, 18))
            ttk.Label(head, text='TTSBR', style='Title.TLabel').pack(side='left')
            ttk.Label(head, text='  Roteiro → voz → revisão', style='Sub.TLabel').pack(side='left', padx=16)
            ttk.Button(head, text='Guia', command=lambda: self._abrir_caminho(ROOT / 'docs' / 'GUI.md')).pack(side='right')
            body = ttk.Frame(shell)
            body.pack(fill='both', expand=True)
            body.columnconfigure(0, weight=1)
            body.rowconfigure(0, weight=1)
            self.tabs = ttk.Notebook(body)
            self.tabs.grid(row=0, column=0, sticky='nsew', padx=(0, 20))
            roteiro = ttk.Frame(self.tabs, padding=12)
            revisao = ttk.Frame(self.tabs, padding=12)
            registro = ttk.Frame(self.tabs, padding=12)
            self.tabs.add(roteiro, text='Roteiro')
            self.tabs.add(revisao, text='Prévia e segmentos')
            self.tabs.add(registro, text='Registro')
            barra = ttk.Frame(roteiro)
            barra.pack(fill='x', pady=(0, 10))
            for texto, acao in [('Abrir .txt', self._abrir), ('Salvar', self._salvar),
                                ('Pausa', lambda: self._tag('[pausa:800ms]')),
                                ('Ênfase', lambda: self._tag('[enfase]')),
                                ('Tom', lambda: self._tag('[tom:calmo] ')),
                                ('Personagem', lambda: self._tag('[Luis|pt]: '))]:
                b = ttk.Button(barra, text=texto, command=acao)
                b.pack(side='left', padx=(0, 5))
                self.editaveis.append((b, 'normal'))
            self.editor = ScrolledText(roteiro, wrap='word', undo=True, font=('Helvetica', 14),
                                       padx=16, pady=16, relief='flat', background='white', foreground='#18283b')
            self.editor.pack(fill='both', expand=True)
            self.editor.bind('<<Modified>>', self._modificado)
            ttk.Label(roteiro, textvariable=self.contagem, style='Sub.TLabel').pack(anchor='w', pady=(8, 0))
            ttk.Label(revisao, text='Texto preparado e progresso por segmento', style='Section.TLabel').pack(anchor='w', pady=(0, 10))
            ttk.Label(revisao, textvariable=self.resultado_ref, style='Sub.TLabel', wraplength=650).pack(anchor='w', pady=(0, 10))
            table = ttk.Frame(revisao)
            table.pack(fill='both', expand=True)
            cols = ('id', 'idioma', 'inicio', 'estado', 'texto')
            self.tree = ttk.Treeview(table, columns=cols, show='headings', selectmode='browse')
            for c, titulo, largura in zip(cols, ('#', 'Idioma', 'Início', 'Situação', 'Texto'), (36, 50, 65, 120, 320)):
                self.tree.heading(c, text=titulo)
                self.tree.column(c, width=largura, stretch=c == 'texto', minwidth=30)
            scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
            self.tree.configure(yscrollcommand=scroll.set)
            self.tree.pack(side='left', fill='both', expand=True)
            scroll.pack(side='right', fill='y')
            self.tree.bind('<<TreeviewSelect>>', self._selecionar)
            ttk.Label(revisao, textvariable=self.detalhe, wraplength=650).pack(fill='x', pady=12)
            acoes_trecho = ttk.Frame(revisao)
            acoes_trecho.pack(fill='x')
            ttk.Button(acoes_trecho, text='Ouvir trecho selecionado', command=self._ouvir_trecho).pack(side='left', padx=(0, 6))
            b_regerar = ttk.Button(acoes_trecho, text='Regerar trecho selecionado', command=self._regerar_trecho)
            b_regerar.pack(side='left')
            self.editaveis.append((b_regerar, 'normal'))
            self.log = ScrolledText(registro, wrap='word', font=('Courier', 10), state='disabled')
            self.log.pack(fill='both', expand=True)
            lateral = ttk.Frame(body, width=280)
            lateral.grid(row=0, column=1, sticky='ns')
            ttk.Label(lateral, text='Configurar a narração', style='Section.TLabel').pack(anchor='w', pady=(0, 12))
            self._campo(lateral, 'Idioma', 'idioma', ('auto', 'pt', 'es'))
            self._campo(lateral, 'Voz embutida', 'locutor', ('Automática', 'Luis Moray', 'Alma María',
                        'Iapetus (Xavier Hayasaka)', 'Xavier Hayasaka', 'Ferran Simen',
                        'Ana Florence', 'Sofia Hellen', 'Marcos Rudaski'), livre=True)
            self._campo(lateral, 'Velocidade · 1.0 é a original', 'velocidade')
            self._campo(lateral, 'Formatos', 'formatos', ('mp3,wav', 'mp3,wav,srt', 'mp3,srt', 'wav', 'mp3', 'srt', 'vtt'), livre=True)
            self._campo(lateral, 'Nome base da saída', 'saida')
            b = ttk.Button(lateral, text='Escolher saída…', command=self._escolher_saida)
            b.pack(fill='x', pady=(0, 10)); self.editaveis.append((b, 'normal'))
            self._campo(lateral, 'Referência de voz · opcional', 'voz')
            b = ttk.Button(lateral, text='Escolher referência…', command=lambda: self._arquivo('voz', [('Áudio', '*.wav *.mp3 *.flac *.m4a'), ('Todos', '*')]))
            b.pack(fill='x', pady=(0, 10)); self.editaveis.append((b, 'normal'))
            b = ttk.Button(lateral, text='Ajustes avançados…', command=self._avancado)
            b.pack(fill='x', pady=(0, 14)); self.editaveis.append((b, 'normal'))
            ttk.Label(lateral, text='A geração salva cada trecho. Repita com a mesma saída para retomar. Use a aba de revisão para ouvir e validar.',
                      style='Sub.TLabel', wraplength=260).pack(anchor='w', pady=10)
            acoes = ttk.Frame(shell)
            acoes.pack(fill='x', pady=(14, 0))
            for texto, modo, estilo in [('Conferir roteiro', 'analisar', 'TButton'),
                                        ('Gerar amostra', 'amostra', 'TButton'),
                                        ('Gerar / retomar áudio', 'gerar', 'Primary.TButton')]:
                b = ttk.Button(acoes, text=texto, style=estilo, command=lambda m=modo: self._iniciar(m))
                b.pack(side='left', padx=(0, 8)); self.editaveis.append((b, 'normal'))
            self.stop = ttk.Button(acoes, text='Interromper após o trecho', command=self._interromper, state='disabled')
            self.stop.pack(side='right')
            revisar = ttk.Frame(revisao)
            revisar.pack(fill='x', pady=(10, 0))
            self.ouvir = ttk.Button(revisar, text='Ouvir resultado', command=self._ouvir, state='disabled')
            self.ouvir.pack(side='left', padx=(0, 6))
            self.validar = ttk.Button(revisar, text='Validar com Whisper', command=lambda: self._iniciar('validar'), state='disabled')
            self.validar.pack(side='left', padx=(0, 6))
            self.metricas = ttk.Button(revisar, text='Métricas', command=lambda: self._iniciar('metricas'), state='disabled')
            self.metricas.pack(side='left', padx=(0, 6))
            self.carregar = ttk.Button(revisar, text='Abrir manifesto…', command=self._carregar_manifesto)
            self.carregar.pack(side='left'); self.editaveis.append((self.carregar, 'normal'))
            foot = ttk.Frame(shell)
            foot.pack(fill='x', pady=(15, 0))
            self.progresso = ttk.Progressbar(foot, mode='determinate', maximum=1)
            self.progresso.pack(fill='x', pady=(0, 7))
            ttk.Label(foot, textvariable=self.status, wraplength=1060).pack(anchor='w')
            ttk.Label(foot, text='XTTS v2 e seus áudios: uso sujeito à CPML, com restrição comercial. Arquivos da GUI ficam em local/gui/.',
                      style='Sub.TLabel').pack(anchor='w', pady=(7, 0))

        def _campo(self, pai, rotulo, nome, valores=None, livre=False):
            ttk.Label(pai, text=rotulo).pack(anchor='w', pady=(0, 3))
            if valores:
                estado = 'normal' if livre else 'readonly'
                w = ttk.Combobox(pai, textvariable=self.vars[nome], values=valores, state=estado, width=28)
            else:
                estado = 'normal'
                w = ttk.Entry(pai, textvariable=self.vars[nome], width=30)
            w.pack(fill='x', pady=(0, 10))
            self.editaveis.append((w, estado))
            return w

        def _avancado(self):
            if self.ocupado: return
            top = tk.Toplevel(self.root)
            top.title('Ajustes avançados')
            top.transient(self.root)
            top.grab_set()
            frame = ttk.Frame(top, padding=20)
            frame.pack(fill='both', expand=True)
            self._campo(frame, 'Python do ambiente TTSBR', 'python')
            ttk.Button(frame, text='Selecionar Python…', command=lambda: self._arquivo('python', [('Executável Python', '*')])).pack(fill='x', pady=(0, 12))
            self._campo(frame, 'Dispositivo', 'dispositivo', ('auto', 'cpu', 'mps', 'cuda'))
            self._campo(frame, 'Volume alvo · dBFS', 'volume_alvo')
            self._campo(frame, 'Loudness final · LUFS (ex.: -16, opcional)', 'lufs')
            self._campo(frame, 'Taxa de amostragem · Hz', 'taxa_amostragem', ('24000', '44100', '48000'))
            self._campo(frame, 'Máximo de tentativas por trecho', 'max_tentativas')
            self._campo(frame, 'Vozes por personagem · nome=arquivo.wav', 'vozes_personagens')
            self._campo(frame, 'Vozes por tom · tom=arquivo.wav', 'vozes_tons')
            self._campo(frame, 'Trilha de fundo (BGM) · opcional', 'trilha')
            ttk.Button(frame, text='Selecionar trilha…', command=lambda: self._arquivo('trilha', [('Áudio', '*.wav *.mp3 *.flac *.m4a'), ('Todos', '*')])).pack(fill='x', pady=(0, 12))
            self._campo(frame, 'Volume da trilha · dB (ex.: -18)', 'volume_trilha')
            self._campo(frame, 'Glossário adicional · TXT ou JSON', 'glossario')
            ttk.Button(frame, text='Selecionar glossário…', command=lambda: self._arquivo('glossario', [('Glossário', '*.txt *.json')])).pack(fill='x', pady=(0, 12))
            pausas = ttk.LabelFrame(frame, text='Pausas em milissegundos', padding=10)
            pausas.pack(fill='x')
            for i, (nome, titulo) in enumerate((('pausa_frase', 'Frase'), ('pausa_reticencias', 'Reticências'),
                        ('pausa_ponto_virgula', '; e :'), ('pausa_virgula', 'Corte intermediário'),
                        ('pausa_paragrafo', 'Parágrafo'), ('pausa_bloco', 'Bloco'))):
                ttk.Label(pausas, text=titulo).grid(row=i, column=0, sticky='w', padx=(0, 20), pady=2)
                ttk.Entry(pausas, textvariable=self.vars[nome], width=12).grid(row=i, column=1, pady=2)
            for nome, titulo in (('sem_normalizar', 'Desativar normalização'),
                                ('sem_corte_silencio', 'Preservar silêncio nas bordas'),
                                ('limpar_referencia', 'Higienizar áudio de referência via FFmpeg'),
                                ('refazer', 'Refazer segmentos, ignorando o cache')):
                ttk.Checkbutton(frame, text=titulo, variable=self.vars[nome]).pack(anchor='w', pady=4)
            ttk.Button(frame, text='Concluir', command=top.destroy).pack(fill='x', pady=(12, 0))
            # Campos de diálogos destruídos não devem receber mudanças de estado.
            top.bind('<Destroy>', lambda e: self._limpar_widgets() if e.widget == top else None)

        def _limpar_widgets(self):
            self.editaveis = [(w, s) for w, s in self.editaveis if w.winfo_exists()]

        def _configuracao(self):
            cfg = {k: v.get() for k, v in self.vars.items()}
            if not cfg['saida'].strip(): raise ValueError('Informe o nome base da saída.')
            cfg['saida'] = str(Path(cfg['saida']).expanduser().absolute())
            cfg['locutor'] = '' if cfg['locutor'] == 'Automática' else cfg['locutor']
            for k in ('voz', 'glossario', 'trilha'):
                cfg[k] = str(Path(cfg[k]).expanduser().absolute()) if cfg[k].strip() else ''
            return cfg

        def _preferencias_salvar(self):
            self.preferencias.parent.mkdir(parents=True, exist_ok=True)
            cfg = {k: v.get() for k, v in self.vars.items()}
            self.preferencias.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')

        def _arquivo(self, nome, tipos):
            caminho = filedialog.askopenfilename(parent=self.root, filetypes=tipos)
            if caminho: self.vars[nome].set(caminho)

        def _escolher_saida(self):
            caminho = filedialog.asksaveasfilename(parent=self.root, title='Nome base, sem extensão', initialfile='narracao')
            if caminho: self.vars['saida'].set(caminho)

        def _modificado(self, evento=None):
            if self.editor.edit_modified():
                self.dirty = True
                self.contagem.set(f"{len(self.editor.get('1.0', 'end-1c').split())} palavras · alterações não salvas")
                self.editor.edit_modified(False)

        def _confirmar_edicao(self):
            if not self.dirty: return True
            escolha = messagebox.askyesnocancel('Roteiro não salvo', 'Deseja salvar o roteiro antes de continuar?', parent=self.root)
            if escolha is None: return False
            return self._salvar() if escolha else True

        def _abrir(self):
            if self.ocupado or not self._confirmar_edicao(): return
            caminho = filedialog.askopenfilename(parent=self.root, filetypes=[('Texto UTF-8', '*.txt')])
            if not caminho: return
            try:
                texto = Path(caminho).read_text(encoding='utf-8-sig')
                self.editor.delete('1.0', 'end'); self.editor.insert('1.0', texto)
                self.editor.edit_reset(); self.editor.edit_modified(False)
                self.origem = Path(caminho).resolve(); self.dirty = False
                self.contagem.set(f'{len(texto.split())} palavras · {self.origem.name}')
            except (OSError, UnicodeError) as exc: self._erro(str(exc))

        def _salvar(self):
            if self.ocupado: return False
            caminho = str(self.origem) if self.origem else filedialog.asksaveasfilename(parent=self.root, defaultextension='.txt', filetypes=[('Texto', '*.txt')])
            if not caminho: return False
            try:
                texto = self.editor.get('1.0', 'end-1c')
                Path(caminho).write_text(texto, encoding='utf-8')
                self.origem = Path(caminho).resolve(); self.dirty = False
                self.editor.edit_modified(False)
                self.contagem.set(f'{len(texto.split())} palavras · {self.origem.name}')
                return True
            except OSError as exc: self._erro(str(exc)); return False

        def _tag(self, texto):
            if not self.ocupado:
                self.editor.insert('insert', texto)
                self.editor.focus_set()

        def _iniciar(self, modo, extras_cfg=None):
            if self.ocupado: return
            try:
                cfg = self._configuracao()
                if extras_cfg:
                    cfg.update(extras_cfg)
                texto = self.editor.get('1.0', 'end-1c')
                if modo in ('validar', 'metricas'):
                    if not self.manifesto: raise ValueError('Gere um áudio ou abra um manifesto concluído.')
                else:
                    if not texto.strip(): raise ValueError('Abra ou escreva um roteiro primeiro.')
                if modo == 'amostra':
                    texto = self.editor.get('sel.first', 'sel.last') if self.editor.tag_ranges('sel') else texto.strip().split('\n\n')[0]
                    if len(texto) > 1200:
                        raise ValueError('Selecione um trecho de até 1.200 caracteres para a amostra.')
                    cfg['saida'] += '.amostra'
                pedido = salvar_pedido(modo, texto, cfg, self.origem, self.manifesto)
                self._preferencias_salvar()
                self.processo.iniciar(str(Path(self.vars['python'].get().strip()).expanduser()), pedido)
            except (OSError, ValueError, RuntimeError) as exc:
                self._erro(str(exc)); return
            self.modo = modo
            self.desfecho = 'Tarefa concluída.'
            self.falhou = False
            self.ocupado = True
            self._habilitar(False)
            self.progresso.configure(value=0, maximum=1)
            self.status.set('Iniciando o processo de trabalho…')
            if modo in ('gerar', 'amostra'):
                self.manifesto = None; self.arquivos = []
                self.resultado_ref.set('Novo resultado em processamento…')
                self.stop.configure(state='normal')
            self.tree.delete(*self.tree.get_children()); self.segmentos = {}
            self.tabs.select(1)

        def _habilitar(self, habilitar):
            self._limpar_widgets()
            for w, estado in self.editaveis:
                w.configure(state=estado if habilitar else 'disabled')
            self.editor.configure(state='normal' if habilitar else 'disabled')
            self.ouvir.configure(state='normal' if habilitar and self.arquivos else 'disabled')
            for botao in (self.validar, self.metricas):
                botao.configure(state='normal' if habilitar and self.manifesto else 'disabled')
            if habilitar: self.stop.configure(state='disabled')

        def _interromper(self):
            self.processo.interromper_apos_segmento()
            self.stop.configure(state='disabled')
            self.status.set('Interrupção solicitada. O trecho atual será preservado antes de parar.')

        def _linha(self, seg, estado):
            key = str(seg['id'])
            self.segmentos[key] = {**self.segmentos.get(key, {}), **seg}
            inicio = f"{seg['inicio_s']:.2f}s" if seg.get('inicio_s') is not None else '—'
            vals = (seg['id'], seg['idioma'], inicio, estado, seg['texto'])
            if self.tree.exists(key): self.tree.item(key, values=vals)
            else: self.tree.insert('', 'end', iid=key, values=vals)

        def _eventos(self):
            try:
                for _ in range(200):
                    e = self.processo.eventos.get_nowait()
                    tipo = e['tipo']
                    if tipo == 'log': self._registro(e['texto'])
                    elif tipo == 'plano':
                        for seg in e['segmentos']: self._linha(seg, 'Preparado')
                        self.progresso.configure(maximum=max(1, e['total']))
                        if self.modo == 'analisar': self.desfecho = f"Roteiro conferido: {e['total']} segmentos preparados."
                    elif tipo == 'etapa':
                        self.status.set(e['mensagem'])
                        if e.get('etapa') == 'montagem': self.stop.configure(state='disabled')
                    elif tipo in ('segmento', 'validacao_segmento'):
                        seg = e['segmento']
                        estado = ('Cache' if seg.get('reutilizado') else 'Gerado') if tipo == 'segmento' else (f"WER {seg['wer']:.1%}" if 'wer' in seg else 'Métricas')
                        self._linha(seg, estado)
                        self.progresso.configure(maximum=max(1, e['total']), value=e['concluidos'])
                        self.status.set(f"{e['concluidos']} de {e['total']} segmentos · {estado}")
                    elif tipo == 'resultado':
                        self.manifesto = Path(e['manifesto']); self.arquivos = e['arquivos']
                        self.resultado_ref.set('Resultado associado: ' + str(self.manifesto))
                        self.desfecho = 'Áudio pronto. Você pode ouvir o resultado ou validar os trechos.'
                    elif tipo == 'resultado_validacao':
                        self.desfecho = ('Métricas coletadas; não equivalem a aprovação da fala.' if e['aprovado'] is None
                                         else f"WER global {e['wer_global']:.1%} · " + ('todos os trechos dentro do limite.' if e['aprovado'] else 'há trechos acima do limite.'))
                        self._registro('Relatório: ' + e['relatorio'])
                    elif tipo == 'interrompido':
                        self.desfecho = f"Interrompido com {e['concluidos']} segmentos concluídos. Gere novamente para retomar."
                    elif tipo == 'erro':
                        self.falhou = True; self.desfecho = e['mensagem']; self._registro(e['mensagem'])
                        self.tabs.select(2)
                    elif tipo == 'processo_encerrado':
                        if e['codigo'] and not self.falhou:
                            self.desfecho = f"O processo encerrou com código {e['codigo']}. Confira o registro e o Python selecionado."
                            self.tabs.select(2)
                        self.ocupado = False
                        self._habilitar(True)
                        self.status.set(self.desfecho)
                        if self.fechar_depois:
                            self.fechar_depois = False
                            self._fechar()
            except queue.Empty:
                pass
            if self.root.winfo_exists(): self.root.after(120, self._eventos)

        def _registro(self, texto):
            self.log.configure(state='normal')
            self.log.insert('end', texto + '\n')
            if int(self.log.index('end-1c').split('.')[0]) > 1200:
                self.log.delete('1.0', '201.0')
            self.log.see('end'); self.log.configure(state='disabled')

        def _carregar_manifesto(self):
            caminho = filedialog.askopenfilename(parent=self.root, filetypes=[('Manifesto TTSBR', '*.blocos.json'), ('JSON', '*.json')])
            if not caminho: return
            try:
                p = Path(caminho).resolve()
                dados = json.loads(p.read_text(encoding='utf-8'))
                if dados.get('estado') != 'concluido' or not dados.get('segmentos'):
                    raise ValueError('Selecione o manifesto de uma síntese concluída.')
                self.tree.delete(*self.tree.get_children()); self.segmentos = {}
                for seg in dados['segmentos']:
                    seg = dict(seg)
                    arquivo = Path(seg['arquivo'])
                    seg['arquivo'] = str(arquivo if arquivo.is_absolute() else p.parent / arquivo)
                    self._linha(seg, 'Disponível')
                self.manifesto = p
                self.resultado_ref.set('Resultado associado: ' + str(p))
                base = str(p).removesuffix('.blocos.json')
                self.arquivos = [base + '.' + ext for ext in ('wav', 'mp3', 'srt', 'vtt') if Path(base + '.' + ext).is_file()]
                self.tabs.select(1); self._habilitar(True)
                self.status.set('Manifesto carregado. Os segmentos precisam estar disponíveis no disco.')
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc: self._erro(str(exc))

        def _selecionar(self, evento=None):
            selecao = self.tree.selection()
            if selecao:
                s = self.segmentos[selecao[0]]
                self.detalhe.set(s['texto'] + ('\n' + s['arquivo'] if s.get('arquivo') else ''))

        def _ouvir_trecho(self):
            selecao = self.tree.selection()
            if selecao and self.segmentos[selecao[0]].get('arquivo'):
                self._abrir_caminho(self.segmentos[selecao[0]]['arquivo'])
            else: self._erro('Selecione um segmento já gerado para ouvir.')

        def _regerar_trecho(self):
            selecao = self.tree.selection()
            if not selecao:
                self._erro('Selecione um segmento na tabela para regerar.')
                return
            seg_id = self.segmentos[selecao[0]]['id']
            self._iniciar('gerar', extras_cfg={'refazer_segmentos': str(seg_id)})

        def _ouvir(self):
            if self.arquivos:
                alvo = next((p for p in self.arquivos if p.endswith('.wav')),
                            next((p for p in self.arquivos if p.endswith('.mp3')), self.arquivos[0]))
                self._abrir_caminho(alvo)

        def _abrir_caminho(self, caminho):
            try: abrir_no_sistema(caminho)
            except OSError as exc: self._erro(str(exc))

        def _erro(self, mensagem):
            messagebox.showerror('TTSBR', mensagem, parent=self.root)

        def _fechar(self):
            if self.ocupado:
                if messagebox.askyesno('Tarefa em execução', 'Aguardar a tarefa parar e fechar? A síntese para após o trecho atual; validação e exportação precisam terminar.', parent=self.root):
                    self.fechar_depois = True
                    if self.modo in ('gerar', 'amostra'): self._interromper()
                    else: self.status.set('Aguardando a tarefa terminar para fechar…')
                return
            if not self._confirmar_edicao(): return
            try: self._preferencias_salvar()
            except OSError as exc:
                if not messagebox.askyesno('Preferências', f'Não foi possível salvar as preferências: {exc}\nFechar mesmo assim?', parent=self.root): return
            self.root.destroy()

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f'Não foi possível abrir uma janela gráfica: {exc}', file=sys.stderr)
        return 1
    Aplicativo(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(iniciar_janela())
