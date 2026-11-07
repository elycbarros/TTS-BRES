#!/usr/bin/env python3
"""Janela local do TTSBR. Interface gráfica em Tkinter para narração, revisão e validação."""
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys

from caminhos import recurso
from gui_core import DATA_ROOT, ROOT, ProcessoTrabalho, python_padrao, salvar_pedido

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
    from tkinter.scrolledtext import ScrolledText
    TKINTER_DISPONIVEL = True
except ImportError:
    TKINTER_DISPONIVEL = False


def abrir_no_sistema(caminho: str | Path) -> None:
    """Abre um arquivo ou pasta no gerenciador de arquivos/reprodutor padrão do SO."""
    caminho = Path(caminho).resolve()
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")
    if sys.platform == "win32":
        os.startfile(str(caminho))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(caminho)])
    else:
        subprocess.Popen(["xdg-open", str(caminho)])


if TKINTER_DISPONIVEL:
    class Aplicativo:
        """Interface gráfica principal do TTSBR construída com Tkinter/ttk."""

        def __init__(self, janela: tk.Tk):
            self.root = janela
            janela.title("TTSBR · Narração local")
            janela.geometry("1180x800")
            janela.minsize(980, 700)

            from tarefas import ClienteFila
            self.processo = ClienteFila()
            self.projeto = None
            self.glossario_projeto = None
            self.plano_recebido = None
            self.player_janela = None
            self.rascunho_after = None
            self.ocupado = False
            self.modo = None
            self.origem = None
            self.manifesto = None
            self.arquivos = []
            self.segmentos = {}
            self.fechar_depois = False
            self.dirty = False
            self.preferencias = DATA_ROOT / "local" / "gui" / "preferencias.json"
            self.vars = {}

            defaults = {
                "python": python_padrao(),
                "saida": str(DATA_ROOT / "saida" / "narracao"),
                "preset": "",
                "idioma": "auto",
                "locutor": "Automática",
                "voz": "",
                "perfil_voz": "",
                "vozes_personagens": "",
                "vozes_tons": "",
                "glossario": "",
                "trilha": "",
                "volume_trilha": "-18",
                "titulo": "",
                "autor": "",
                "capa": "",
                "formatos": "mp3,wav",
                "velocidade": "1.1",
                "volume_alvo": "-20",
                "lufs": "",
                "taxa_amostragem": "24000",
                "max_tentativas": "2",
                "dispositivo": "auto",
                "pausa_frase": "600",
                "pausa_reticencias": "850",
                "pausa_ponto_virgula": "420",
                "pausa_virgula": "250",
                "pausa_paragrafo": "1150",
                "pausa_bloco": "500",
                "sem_normalizar": False,
                "sem_corte_silencio": False,
                "limpar_referencia": False,
                "por_capitulo": False,
                "refazer": False,
            }
            self.config_base = dict(defaults)
            try:
                cfg = json.loads(self.preferencias.read_text(encoding="utf-8"))
                defaults.update({k: v for k, v in cfg.items() if k in defaults})
            except (OSError, ValueError, AttributeError):
                pass

            for k, v in defaults.items():
                self.vars[k] = tk.BooleanVar(value=v) if isinstance(v, bool) else tk.StringVar(value=v)
            self.vars['voz'].trace_add('write', lambda *_: self.vars['perfil_voz'].set(''))

            self.status = tk.StringVar(value="Abra um roteiro ou escreva abaixo para começar.")
            self.contagem = tk.StringVar(value="0 palavras")
            self.detalhe = tk.StringVar(value="Selecione um segmento para conferir seu texto.")
            self.resultado_ref = tk.StringVar(value="Nenhum resultado associado. Gere um áudio ou abra um manifesto.")
            self.editaveis = []

            self._estilo()
            self._construir()
            menu = tk.Menu(janela)
            projetos = tk.Menu(menu, tearoff=False)
            for titulo, acao in [('Novo projeto…', self._novo_projeto), ('Abrir projeto…', self._abrir_projeto),
                                 ('Salvar projeto', self._salvar_projeto), ('Exportar pacote…', self._exportar_projeto),
                                 ('Importar pacote…', self._importar_projeto), ('Tomadas A/B…', self._tomadas)]:
                projetos.add_command(label=titulo, command=acao)
            menu.add_cascade(label='Projeto', menu=projetos)
            menu.add_command(label='Fila de tarefas…', command=self._fila)
            janela.configure(menu=menu)
            for nome, variavel in self.vars.items():
                if nome != 'python': variavel.trace_add('write', self._config_alterada)

            janela.protocol("WM_DELETE_WINDOW", self._fechar)
            modificadores = ("Control", "Command") if sys.platform == "darwin" else ("Control",)
            for mod in modificadores:
                janela.bind(f"<{mod}-o>", lambda e: self._abrir())
                janela.bind(f"<{mod}-s>", lambda e: self._salvar())

            janela.after(120, self._eventos)

        def _estilo(self) -> None:
            s = ttk.Style()
            s.theme_use("clam")
            s.configure(".", font=("Helvetica", 11), background="#f3f6fa", foreground="#18283b")
            s.configure("TButton", padding=(10, 7))
            s.configure("Primary.TButton", background="#126c68", foreground="white", padding=(14, 10))
            s.map("Primary.TButton", background=[("active", "#0b5552"), ("disabled", "#b4c5c9")])
            s.configure("Title.TLabel", font=("Helvetica", 24, "bold"))
            s.configure("Sub.TLabel", foreground="#536478")
            s.configure("Section.TLabel", font=("Helvetica", 12, "bold"))
            s.configure("Treeview", rowheight=29, background="white", fieldbackground="white")
            s.configure("TNotebook.Tab", padding=(16, 9))

        def _construir(self) -> None:
            shell = ttk.Frame(self.root, padding=20)
            shell.pack(fill="both", expand=True)

            head = ttk.Frame(shell)
            head.pack(fill="x", pady=(0, 18))
            ttk.Label(head, text="TTSBR", style="Title.TLabel").pack(side="left")
            ttk.Label(head, text="  Roteiro → voz → revisão", style="Sub.TLabel").pack(side="left", padx=16)
            ttk.Button(head, text="Guia", command=lambda: self._abrir_caminho(recurso("docs/GUI.md"))).pack(side="right")

            body = ttk.Frame(shell)
            body.pack(fill="both", expand=True)
            body.columnconfigure(0, weight=1)
            body.rowconfigure(0, weight=1)

            self.tabs = ttk.Notebook(body)
            self.tabs.grid(row=0, column=0, sticky="nsew", padx=(0, 20))

            roteiro = ttk.Frame(self.tabs, padding=12)
            revisao = ttk.Frame(self.tabs, padding=12)
            registro = ttk.Frame(self.tabs, padding=12)

            self.tabs.add(roteiro, text="Roteiro")
            self.tabs.add(revisao, text="Prévia e segmentos")
            self.tabs.add(registro, text="Registro")

            barra = ttk.Frame(roteiro)
            barra.pack(fill="x", pady=(0, 10))
            for texto, acao in [
                ("Abrir .txt", self._abrir),
                ("Salvar", self._salvar),
                ("Pausa", lambda: self._tag("[pausa:800ms]")),
                ("Ênfase", lambda: self._tag("[enfase]")),
                ("Tom", lambda: self._tag("[tom:calmo] ")),
                ("Personagem", lambda: self._tag("[Luis|pt]: ")),
            ]:
                b = ttk.Button(barra, text=texto, command=acao)
                b.pack(side="left", padx=(0, 5))
                self.editaveis.append((b, "normal"))

            self.editor = ScrolledText(
                roteiro,
                wrap="word",
                undo=True,
                font=("Helvetica", 14),
                padx=16,
                pady=16,
                relief="flat",
                background="white",
                foreground="#18283b",
            )
            self.editor.pack(fill="both", expand=True)
            self.editor.bind("<<Modified>>", self._modificado)

            ttk.Label(roteiro, textvariable=self.contagem, style="Sub.TLabel").pack(anchor="w", pady=(8, 0))

            ttk.Label(revisao, text="Texto preparado e progresso por segmento", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
            ttk.Label(revisao, textvariable=self.resultado_ref, style="Sub.TLabel", wraplength=650).pack(anchor="w", pady=(0, 10))

            table = ttk.Frame(revisao)
            table.pack(fill="both", expand=True)

            cols = ("id", "idioma", "inicio", "estado", "texto")
            self.tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="browse")
            for c, titulo, largura in zip(cols, ("#", "Idioma", "Início", "Situação", "Texto"), (36, 50, 65, 120, 320)):
                self.tree.heading(c, text=titulo)
                self.tree.column(c, width=largura, stretch=c == "texto", minwidth=30)

            scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=scroll.set)
            self.tree.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            self.tree.bind("<<TreeviewSelect>>", self._selecionar)
            self.tree.bind('<Double-1>', lambda _e: self._ouvir_no_resultado())

            ttk.Label(revisao, textvariable=self.detalhe, wraplength=650).pack(fill="x", pady=12)

            acoes_trecho = ttk.Frame(revisao)
            acoes_trecho.pack(fill="x")
            ttk.Button(acoes_trecho, text="Ouvir trecho selecionado", command=self._ouvir_trecho).pack(side="left", padx=(0, 6))
            b_regerar = ttk.Button(acoes_trecho, text="Regerar trecho selecionado", command=self._regerar_trecho)
            b_regerar.pack(side="left")
            self.editaveis.append((b_regerar, "normal"))
            b = ttk.Button(acoes_trecho, text='Editar fala…', command=self._editar_segmento)
            b.pack(side='left', padx=6)
            self.editaveis.append((b, 'normal'))

            self.log = ScrolledText(registro, wrap="word", font=("Courier", 10), state="disabled")
            self.log.pack(fill="both", expand=True)

            lateral = ttk.Frame(body, width=280)
            lateral.grid(row=0, column=1, sticky="ns")

            ttk.Label(lateral, text="Configurar a narração", style="Section.TLabel").pack(anchor="w", pady=(0, 12))
            cb_preset = self._campo(lateral, "Preset", "preset", ("", "narracao", "amostra", "revisao"))
            cb_preset.bind("<<ComboboxSelected>>", lambda _e: self._aplicar_preset(self.vars["preset"].get()))
            self._campo(lateral, "Idioma", "idioma", ("auto", "pt", "es"))
            from vozes import listar_vozes_embutidas
            vozes_combo = ("Automática",) + tuple(listar_vozes_embutidas())
            self._campo(
                lateral,
                "Voz embutida",
                "locutor",
                vozes_combo,
                livre=True,
            )
            self._campo(lateral, "Velocidade · 1.0 é a original", "velocidade")
            self._campo(lateral, "Formatos", "formatos", ("mp3,wav", "m4b", "mp3,m4b", "mp3,wav,m4b", "mp3,wav,srt", "mp3,srt", "wav", "mp3", "srt", "vtt"), livre=True)
            self._campo(lateral, "Nome base da saída", "saida")

            b = ttk.Button(lateral, text="Escolher saída…", command=self._escolher_saida)
            b.pack(fill="x", pady=(0, 10))
            self.editaveis.append((b, "normal"))

            self._campo(lateral, "Referência de voz · opcional", "voz")
            b = ttk.Button(
                lateral,
                text="Escolher referência…",
                command=lambda: self._arquivo("voz", [("Áudio", "*.wav *.mp3 *.flac *.m4a"), ("Todos", "*")]),
            )
            b.pack(fill="x", pady=(0, 10))
            self.editaveis.append((b, "normal"))

            b = ttk.Button(lateral, text="Biblioteca de vozes…", command=self._biblioteca)
            b.pack(fill="x", pady=(0, 10))
            self.editaveis.append((b, "normal"))

            b = ttk.Button(lateral, text="Ouvir prévia da voz", command=self._previa_voz)
            b.pack(fill="x", pady=(0, 10))
            self.editaveis.append((b, "normal"))

            b = ttk.Button(lateral, text="Ajustes avançados…", command=self._avancado)
            b.pack(fill="x", pady=(0, 14))
            self.editaveis.append((b, "normal"))

            ttk.Label(
                lateral,
                text="A geração salva cada trecho. Repita com a mesma saída para retomar. Use a aba de revisão para ouvir e validar.",
                style="Sub.TLabel",
                wraplength=260,
            ).pack(anchor="w", pady=10)

            acoes = ttk.Frame(shell)
            acoes.pack(fill="x", pady=(14, 0))

            for texto, modo, estilo in [
                ("Conferir roteiro", "analisar", "TButton"),
                ("Gerar amostra", "amostra", "TButton"),
                ("Gerar / retomar áudio", "gerar", "Primary.TButton"),
            ]:
                b = ttk.Button(acoes, text=texto, style=estilo, command=lambda m=modo: self._iniciar(m))
                b.pack(side="left", padx=(0, 8))
                self.editaveis.append((b, "normal"))

            self.stop = ttk.Button(acoes, text="Interromper após o trecho", command=self._interromper, state="disabled")
            self.stop.pack(side="right")

            revisar = ttk.Frame(revisao)
            revisar.pack(fill="x", pady=(10, 0))

            self.ouvir = ttk.Button(revisar, text="Ouvir resultado", command=self._ouvir, state="disabled")
            self.ouvir.pack(side="left", padx=(0, 6))

            self.validar = ttk.Button(revisar, text="Validar com Whisper", command=lambda: self._iniciar("validar"), state="disabled")
            self.validar.pack(side="left", padx=(0, 6))

            self.metricas = ttk.Button(revisar, text="Métricas", command=lambda: self._iniciar("metricas"), state="disabled")
            self.metricas.pack(side="left", padx=(0, 6))

            self.carregar = ttk.Button(revisar, text="Abrir manifesto…", command=self._carregar_manifesto)
            self.carregar.pack(side="left")
            self.editaveis.append((self.carregar, "normal"))

            foot = ttk.Frame(shell)
            foot.pack(fill="x", pady=(15, 0))

            self.progresso = ttk.Progressbar(foot, mode="determinate", maximum=1)
            self.progresso.pack(fill="x", pady=(0, 7))

            ttk.Label(foot, textvariable=self.status, wraplength=1060).pack(anchor="w")
            ttk.Label(
                foot,
                text=f"XTTS v2 e seus áudios: sujeitos à CPML. Dados locais: {self.preferencias.parent}",
                wraplength=1000,
                style="Sub.TLabel",
            ).pack(anchor="w", pady=(7, 0))

        def _campo(self, pai, rotulo: str, nome: str, valores: tuple | None = None, livre: bool = False):
            ttk.Label(pai, text=rotulo).pack(anchor="w", pady=(0, 3))
            if valores:
                estado = "normal" if livre else "readonly"
                w = ttk.Combobox(pai, textvariable=self.vars[nome], values=valores, state=estado, width=28)
            else:
                estado = "normal"
                w = ttk.Entry(pai, textvariable=self.vars[nome], width=30)
            w.pack(fill="x", pady=(0, 10))
            self.editaveis.append((w, estado))
            return w

        def _avancado(self) -> None:
            if self.ocupado:
                return
            top = tk.Toplevel(self.root)
            top.title("Ajustes avançados")
            top.transient(self.root)
            top.grab_set()

            top.geometry("680x700")
            top.minsize(520, 400)
            area = ttk.Frame(top)
            area.pack(fill="both", expand=True)
            canvas = tk.Canvas(area, highlightthickness=0, background="#f3f6fa")
            rolagem = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=rolagem.set)
            rolagem.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)
            frame = ttk.Frame(canvas, padding=20)
            janela_interna = canvas.create_window((0, 0), window=frame, anchor="nw")
            frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind("<Configure>", lambda e: canvas.itemconfigure(janela_interna, width=e.width))

            def rolar(evento):
                passo = -int(evento.delta / 120) if abs(evento.delta) >= 120 else -int(evento.delta)
                canvas.yview_scroll(passo, "units")
            top.bind("<MouseWheel>", rolar)

            self._campo(frame, "Python do ambiente TTSBR", "python")
            ttk.Button(frame, text="Selecionar Python…", command=lambda: self._arquivo("python", [("Executável Python", "*")])).pack(fill="x", pady=(0, 12))

            self._campo(frame, "Dispositivo", "dispositivo", ("auto", "cpu", "mps", "cuda"))
            self._campo(frame, "Volume alvo · dBFS", "volume_alvo")
            self._campo(frame, "Loudness final · LUFS (ex.: -16, opcional)", "lufs")
            self._campo(frame, "Taxa de amostragem · Hz", "taxa_amostragem", ("24000", "44100", "48000"))
            self._campo(frame, "Máximo de tentativas por trecho", "max_tentativas")
            self._campo(frame, "Vozes por personagem · nome=arquivo.wav", "vozes_personagens")
            self._campo(frame, "Vozes por tom · tom=arquivo.wav", "vozes_tons")
            self._campo(frame, "Trilha de fundo (BGM) · opcional", "trilha")
            ttk.Button(frame, text="Selecionar trilha…", command=lambda: self._arquivo("trilha", [("Áudio", "*.wav *.mp3 *.flac *.m4a"), ("Todos", "*")])).pack(fill="x", pady=(0, 12))
            self._campo(frame, "Volume da trilha · dB (ex.: -18)", "volume_trilha")
            self._campo(frame, "Título da obra (metadado opcional)", "titulo")
            self._campo(frame, "Autor / narrador (metadado opcional)", "autor")
            self._campo(frame, "Capa do audiolivro · JPG ou PNG (opcional)", "capa")
            ttk.Button(frame, text="Selecionar capa…", command=lambda: self._arquivo("capa", [("Imagens", "*.jpg *.jpeg *.png"), ("Todos", "*")])).pack(fill="x", pady=(0, 12))
            self._campo(frame, "Glossário adicional · TXT ou JSON", "glossario")
            ttk.Button(frame, text="Selecionar glossário…", command=lambda: self._arquivo("glossario", [("Glossário", "*.txt *.json")])).pack(fill="x", pady=(0, 12))

            pausas = ttk.LabelFrame(frame, text="Pausas em milissegundos", padding=10)
            pausas.pack(fill="x")
            for i, (nome, titulo) in enumerate((
                ("pausa_frase", "Frase"),
                ("pausa_reticencias", "Reticências"),
                ("pausa_ponto_virgula", "; e :"),
                ("pausa_virgula", "Corte intermediário"),
                ("pausa_paragrafo", "Parágrafo"),
                ("pausa_bloco", "Bloco"),
            )):
                ttk.Label(pausas, text=titulo).grid(row=i, column=0, sticky="w", padx=(0, 20), pady=2)
                ttk.Entry(pausas, textvariable=self.vars[nome], width=12).grid(row=i, column=1, pady=2)

            for nome, titulo in (
                ("sem_normalizar", "Desativar normalização"),
                ("sem_corte_silencio", "Preservar silêncio nas bordas"),
                ("limpar_referencia", "Higienizar áudio de referência via FFmpeg"),
                ("por_capitulo", "Exportar também um arquivo por capítulo (# Título)"),
                ("refazer", "Refazer segmentos, ignorando o cache"),
            ):
                ttk.Checkbutton(frame, text=titulo, variable=self.vars[nome]).pack(anchor="w", pady=4)

            ttk.Button(frame, text="Restaurar padrões", command=self._restaurar_padroes).pack(fill="x", pady=(10, 0))
            ttk.Button(frame, text="Concluir", command=top.destroy).pack(fill="x", pady=(8, 0))
            top.bind("<Destroy>", lambda e: self._limpar_widgets() if e.widget == top else None)

        def _aplicar_preset(self, nome: str) -> None:
            from tts import aplicar_preset_dict
            atuais = {k: v.get() for k, v in self.vars.items()}
            novos = aplicar_preset_dict(atuais, nome)
            for k, val in novos.items():
                if k in self.vars and not isinstance(self.vars[k].get(), bool):
                    self.vars[k].set(val)

        def _restaurar_padroes(self) -> None:
            for k, val in self.config_base.items():
                if k not in ("python", "saida", "voz", "perfil_voz"):
                    self.vars[k].set(val)
            self.status.set("Parâmetros restaurados para os padrões originais.")

        def _limpar_widgets(self) -> None:
            self.editaveis = [(w, s) for w, s in self.editaveis if w.winfo_exists()]

        def _novo_projeto(self):
            if self.ocupado or not self._confirmar_edicao(): return
            titulo = simpledialog.askstring('Novo projeto', 'Título do projeto:', parent=self.root)
            if not titulo: return
            try:
                from projetos import Projeto
                from normalizador import carregar_glossario
                cfg = self._configuracao()
                glossario = carregar_glossario(cfg.get('glossario'), texto_path=self.origem)
                projeto = Projeto.criar(titulo, self.editor.get('1.0', 'end-1c'))
                projeto.atualizar(self.editor.get('1.0', 'end-1c'), cfg, glossario, self.origem)
                self.projeto = projeto
                self.glossario_projeto = glossario
                self.dirty = False
                self.root.title(f'TTSBR · {titulo}')
                self.status.set('Projeto salvo. Confira o roteiro antes da primeira geração.')
            except (OSError, ValueError, sqlite3.Error) as exc: self._erro(str(exc))

        def _fila(self):
            try:
                atual = getattr(self, 'fila_janela', None)
                if atual and atual.janela.winfo_exists():
                    atual.janela.lift(); return
                from fila_gui import JanelaFila
                self.fila_janela = JanelaFila(self.root, self.processo.fila, self.vars['python'].get().strip())
            except (OSError, ValueError, sqlite3.Error) as exc: self._erro(str(exc))

        def _salvar_projeto(self):
            if self.ocupado: return False
            if not self.projeto:
                self._novo_projeto()
                return self.projeto is not None
            try:
                from normalizador import carregar_glossario
                cfg = self._configuracao()
                salvo = self.projeto.configuracao()
                glossario = self.glossario_projeto
                if glossario is None or cfg.get('glossario') != salvo.get('glossario'):
                    glossario = carregar_glossario(cfg.get('glossario'), texto_path=self.origem)
                self.projeto.atualizar(self.editor.get('1.0', 'end-1c'), cfg, glossario, self.origem)
                self.glossario_projeto = glossario
                self.dirty = False
                self.projeto.caminho.with_suffix('.rascunho.json').unlink(missing_ok=True)
                self.status.set(f'Projeto salvo: {self.projeto.caminho}')
                return True
            except (OSError, ValueError, sqlite3.Error) as exc:
                self._erro(str(exc)); return False

        def _exportar_projeto(self):
            if self.ocupado: return
            if not self.projeto:
                self._erro('Salve ou abra um projeto antes de exportar.'); return
            if not self._salvar_projeto(): return
            destino = filedialog.asksaveasfilename(
                parent=self.root, title='Exportar pacote de projeto',
                defaultextension='.json', initialfile=f"{self.projeto.id[:8]}.pacote.json",
                filetypes=[('Pacote de projeto TTSBR', '*.json')],
            )
            if not destino: return
            incluir_ref = messagebox.askyesno(
                'Incluir referência de voz?',
                'Deseja copiar também o WAV de referência (se houver) para uma pasta ao lado do pacote? '
                'Confirme apenas se você tiver autorização para transportar essa gravação.',
                parent=self.root,
            )
            try:
                self.projeto.exportar_pacote(destino, incluir_referencia=incluir_ref)
                self.status.set(f'Pacote exportado: {destino}')
            except (OSError, ValueError, sqlite3.Error) as exc:
                self._erro(str(exc))

        def _importar_projeto(self):
            if self.ocupado or not self._confirmar_edicao(): return
            origem = filedialog.askopenfilename(
                parent=self.root, title='Importar pacote de projeto',
                filetypes=[('Pacote de projeto TTSBR', '*.json')],
            )
            if not origem: return
            try:
                from projetos import Projeto
                projeto = Projeto.importar_pacote(origem)
                self.projeto = projeto
                self.glossario_projeto = projeto.documento['dados']['glossario']
                self.dirty = False
                cfg = projeto.configuracao()
                for chave, var in self.vars.items():
                    if chave not in ('python', 'perfil_voz'):
                        var.set(cfg.get(chave, self.config_base.get(chave, '')))
                self.vars['perfil_voz'].set('')
                self.editor.delete('1.0', 'end'); self.editor.insert('1.0', projeto.documento['dados']['roteiro'])
                self.editor.edit_reset(); self.editor.edit_modified(False)
                self.root.title('TTSBR · ' + projeto.documento['dados']['titulo'])
                self.status.set(f'Pacote importado como novo projeto: {projeto.caminho}')
            except (OSError, ValueError, sqlite3.Error) as exc:
                self._erro(str(exc))

        def _abrir_projeto(self):
            if self.ocupado or not self._confirmar_edicao(): return
            caminho = filedialog.askopenfilename(parent=self.root, title='Abrir projeto',
                                                 filetypes=[('Projeto TTSBR', 'projeto.json'), ('JSON', '*.json')])
            if not caminho: return
            try:
                from projetos import Projeto
                try: projeto = Projeto.abrir(caminho)
                except (OSError, ValueError):
                    if not messagebox.askyesno('Recuperar projeto', 'Não foi possível abrir. Tentar recuperar o backup anterior?', parent=self.root): return
                    projeto = Projeto.abrir(caminho, backup=True)
                    projeto.salvar(recuperar=True)
                self._fechar_player()
                self.projeto = None  # Não produzir rascunho enquanto os campos são restaurados.
                cfg = projeto.configuracao()
                for chave, var in self.vars.items():
                    if chave not in ('python', 'perfil_voz'):
                        var.set(cfg.get(chave, self.config_base.get(chave, '')))
                self.vars['perfil_voz'].set(cfg.get('perfil_voz', ''))
                self.editor.delete('1.0', 'end'); self.editor.insert('1.0', projeto.documento['dados']['roteiro'])
                self.editor.edit_reset(); self.editor.edit_modified(False)
                origem = projeto.estado['origem']
                self.origem = (projeto.caminho.parent / origem).resolve() if origem else None
                self.projeto, self.glossario_projeto = projeto, projeto.documento['dados']['glossario']
                self.dirty = False
                self.tree.delete(*self.tree.get_children()); self.segmentos = {}
                from revisao_segmentos import aplicar_revisao, documento_revisao
                estado = projeto.estado
                for seg in aplicar_revisao(estado['segmentos'], documento_revisao(estado['segmentos'], estado['edicoes'])):
                    self._linha(seg, 'Conferido')
                self.manifesto = None; self.arquivos = []
                self.resultado_ref.set('Projeto reaberto. Resultados anteriores no menu Projeto → Tomadas A/B.')
                self.root.title('TTSBR · ' + projeto.documento['dados']['titulo'])
                rascunho = projeto.ler_rascunho()
                if rascunho and messagebox.askyesno('Rascunho encontrado',
                    f"Recuperar o rascunho da revisão {rascunho['revisao_base']}? O projeto salvo será preservado até salvar novamente.", parent=self.root):
                    for chave, valor in rascunho.get('configuracao', {}).items():
                        if chave in self.vars and chave not in ('python', 'perfil_voz'): self.vars[chave].set(valor)
                    self.vars['perfil_voz'].set(rascunho.get('configuracao', {}).get('perfil_voz', ''))
                    self.editor.delete('1.0', 'end'); self.editor.insert('1.0', rascunho['roteiro'])
                    self.dirty = True
                self._habilitar(True)
                self.status.set(f'Projeto aberto: {projeto.documento["dados"]["titulo"]}')
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc: self._erro(str(exc))

        def _editar_segmento(self):
            if self.ocupado: return
            if not self.projeto:
                self._erro('Crie ou abra um projeto e confira o roteiro antes de editar segmentos.'); return
            selecao = self.tree.selection()
            if not selecao:
                self._erro('Selecione um segmento conferido.'); return
            segmento = self.segmentos[selecao[0]]
            estavel = segmento.get('id_estavel')
            if not estavel:
                self._erro('Confira o roteiro para associar os IDs do projeto.'); return
            texto = simpledialog.askstring('Editar fala preparada',
                'Correção de até 200 caracteres, sem tags. O roteiro e as pausas originais serão preservados:',
                initialvalue=segmento['texto'], parent=self.root)
            if texto is None: return
            try:
                self.projeto.editar_segmento(estavel, texto)
                segmento['texto'] = texto.strip()
                self._linha(segmento, 'Correção salva')
                self.detalhe.set(texto)
            except (ValueError, OSError, sqlite3.Error) as exc: self._erro(str(exc))

        def _tomadas(self):
            if self.ocupado: return
            if not self.projeto:
                self._erro('Abra um projeto primeiro.'); return
            projeto = self.projeto
            top = tk.Toplevel(self.root); top.title('Histórico de tomadas · A/B'); top.geometry('650x380')
            lista = ttk.Treeview(top, columns=('id',), show='headings')
            lista.heading('id', text='Tomada preservada'); lista.pack(fill='both', expand=True, padx=12, pady=12)
            tomadas = {t['id']: t for t in projeto.estado['tomadas']}
            for identidade in tomadas: lista.insert('', 'end', iid=identidade, values=(identidade,))
            escolhidas = {}
            status = tk.StringVar(value='Escolha duas tomadas e alterne a reprodução. Apenas uma toca por vez.')
            def escolher(lado):
                selecao = lista.selection()
                if selecao:
                    escolhidas[lado] = tomadas[selecao[0]]
                    status.set(' · '.join(f'{k}: {v["id"]}' for k, v in escolhidas.items()))
            def tocar(lado):
                if lado not in escolhidas: return
                tomadas_arquivos = escolhidas[lado]['arquivos']
                wav = next((p for p in tomadas_arquivos if p.lower().endswith('.wav')), None)
                if not wav:
                    self._erro('Essa tomada não tem WAV. Gere uma tomada com formato WAV para comparar.'); return
                self._player((projeto.caminho.parent / wav).resolve())
            barra = ttk.Frame(top); barra.pack(fill='x', padx=12)
            for lado in ('A', 'B'):
                ttk.Button(barra, text=f'Escolher {lado}', command=lambda l=lado: escolher(l)).pack(side='left')
                ttk.Button(barra, text=f'Ouvir {lado}', command=lambda l=lado: tocar(l)).pack(side='left')
            ttk.Label(top, textvariable=status, wraplength=600).pack(fill='x', padx=12, pady=10)

        def _player(self, caminho, inicio=0):
            try:
                if not Path(caminho).is_file(): raise ValueError('Arquivo ausente; confira a tomada ou restaure seu backup.')
                self._fechar_player()
                from player_gui import JanelaPlayer
                self.player_janela = JanelaPlayer(self.root, self.vars['python'].get().strip(), caminho, self._abrir_caminho, inicio)
            except (ValueError, OSError) as exc: self._erro(str(exc))

        def _fechar_player(self):
            if self.player_janela and self.player_janela.janela.winfo_exists():
                self.player_janela.fechar()
            self.player_janela = None


        def _biblioteca(self) -> None:
            if self.ocupado:
                return
            try:
                from biblioteca_gui import JanelaBiblioteca
                def selecionar(identidade, caminho):
                    self.vars['voz'].set(str(caminho))
                    self.vars['perfil_voz'].set(identidade)
                    self.status.set('Perfil da biblioteca selecionado; a integridade será conferida ao gerar.')
                self.biblioteca_janela = JanelaBiblioteca(
                    self.root, self.vars['python'].get().strip(), selecionar, abrir_no_sistema)
            except (OSError, ValueError, sqlite3.Error) as exc:
                self._erro(str(exc))

        def _previa_voz(self) -> None:
            if self.ocupado:
                return
            perfil_id = self.vars.get("perfil_voz", tk.StringVar()).get().strip()
            voz_ref = self.vars.get("voz", tk.StringVar()).get().strip()
            if perfil_id:
                try:
                    from biblioteca_vozes import BibliotecaVozes
                    caminho_wav = BibliotecaVozes().resolver(perfil_id)
                    self._player(caminho_wav)
                    return
                except Exception as exc:
                    self._erro(f"Erro ao obter prévia da biblioteca: {exc}")
                    return
            if voz_ref and Path(voz_ref).is_file():
                self._player(Path(voz_ref).resolve())
                return

            locutor = self.vars.get("locutor", tk.StringVar()).get().strip()
            idioma = self.vars.get("idioma", tk.StringVar()).get().strip()
            if not idioma or idioma == "auto":
                idioma = "es" if locutor in ("Alma María", "Xavier Hayasaka", "Ferran Simen", "Claribel Dervla") else "pt"
            if not locutor or locutor == "Automática":
                from vozes import VOZES_PADRAO
                locutor = VOZES_PADRAO.get(idioma, "Luis Moray")

            pasta_previas = DATA_ROOT / "local" / "previas"
            pasta_previas.mkdir(parents=True, exist_ok=True)
            nome_limpo = "".join(c if c.isalnum() else "_" for c in locutor)
            caminho_previa = pasta_previas / f"previa_{idioma}_{nome_limpo}.wav"

            if caminho_previa.is_file():
                self._player(caminho_previa)
                return

            from vozes import TEXTOS_PREVIA
            texto = TEXTOS_PREVIA.get(idioma, TEXTOS_PREVIA["pt"])
            self.status.set(f"Sintetizando prévia de {locutor}…")

            def _gerar():
                try:
                    import subprocess
                    python = self.vars['python'].get().strip() or sys.executable
                    txt_temp = pasta_previas / f"temp_{idioma}_{nome_limpo}.txt"
                    txt_temp.write_text(texto, encoding='utf-8')
                    saida_base = pasta_previas / f"previa_{idioma}_{nome_limpo}"
                    cmd = [
                        python, "-B", str(ROOT / "tts.py"), str(txt_temp),
                        "--locutor", locutor, "--idioma", idioma,
                        "--velocidade", "1.0", "--formatos", "wav",
                        "--saida", str(saida_base), "--preset", "amostra"
                    ]
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if r.returncode == 0 and caminho_previa.is_file():
                        self.root.after(0, lambda: self._player(caminho_previa))
                        self.root.after(0, lambda: self.status.set(f"Prévia de {locutor} pronta."))
                    else:
                        self.root.after(0, lambda: self._erro(f"Falha ao gerar prévia: {r.stderr or r.stdout}"))
                except Exception as exc:
                    self.root.after(0, lambda: self._erro(f"Erro na prévia: {exc}"))

            import threading
            threading.Thread(target=_gerar, daemon=True).start()

        def _configuracao(self) -> dict:
            cfg = {k: v.get() for k, v in self.vars.items()}
            if not cfg["saida"].strip():
                raise ValueError("Informe o nome base da saída.")
            cfg["saida"] = str(Path(cfg["saida"]).expanduser().absolute())
            cfg["locutor"] = "" if cfg["locutor"] == "Automática" else cfg["locutor"]
            for k in ("voz", "glossario", "trilha", "capa"):
                cfg[k] = str(Path(cfg[k]).expanduser().absolute()) if cfg[k].strip() else ""
            return cfg

        def _preferencias_salvar(self) -> None:
            self.preferencias.parent.mkdir(parents=True, exist_ok=True)
            cfg = {k: v.get() for k, v in self.vars.items()}
            self.preferencias.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

        def _arquivo(self, nome: str, tipos: list) -> None:
            caminho = filedialog.askopenfilename(parent=self.root, filetypes=tipos)
            if caminho:
                self.vars[nome].set(caminho)

        def _escolher_saida(self) -> None:
            caminho = filedialog.asksaveasfilename(
                parent=self.root,
                title="Nome base, sem extensão",
                initialfile="narracao",
            )
            if caminho:
                self.vars["saida"].set(caminho)

        def _modificado(self, evento=None) -> None:
            if self.editor.edit_modified():
                self.dirty = True
                total = len(self.editor.get("1.0", "end-1c").split())
                self.contagem.set(f"{total} palavras · alterações não salvas")
                self.editor.edit_modified(False)
                self._agendar_rascunho()

        def _config_alterada(self, *_args):
            if self.projeto and not self.ocupado:
                self.dirty = True
                self._agendar_rascunho()

        def _agendar_rascunho(self):
            if not self.projeto: return
            if self.rascunho_after: self.root.after_cancel(self.rascunho_after)
            self.rascunho_after = self.root.after(1000, self._rascunho)

        def _rascunho(self):
            self.rascunho_after = None
            if self.projeto and self.dirty:
                try:
                    self.projeto.rascunho(self.editor.get('1.0', 'end-1c'),
                                          {k: v.get() for k, v in self.vars.items()})
                except (OSError, ValueError) as exc: self.status.set(f'Falha no rascunho: {exc}')

        def _confirmar_edicao(self) -> bool:
            if not self.dirty:
                return True
            escolha = messagebox.askyesnocancel(
                "Roteiro não salvo",
                "Deseja salvar o roteiro antes de continuar?",
                parent=self.root,
            )
            if escolha is None:
                return False
            return self._salvar() if escolha else True

        def _abrir(self) -> None:
            if self.ocupado or not self._confirmar_edicao():
                return
            caminho = filedialog.askopenfilename(parent=self.root, filetypes=[("Texto UTF-8", "*.txt")])
            if not caminho:
                return
            try:
                texto = Path(caminho).read_text(encoding="utf-8-sig")
                self.projeto = None
                self.glossario_projeto = None
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", texto)
                self.editor.edit_reset()
                self.editor.edit_modified(False)
                self.origem = Path(caminho).resolve()
                self.dirty = False
                self.contagem.set(f"{len(texto.split())} palavras · {self.origem.name}")
            except (OSError, UnicodeError) as exc:
                self._erro(str(exc))

        def _salvar(self) -> bool:
            if self.projeto:
                return self._salvar_projeto()
            if self.ocupado:
                return False
            caminho = str(self.origem) if self.origem else filedialog.asksaveasfilename(
                parent=self.root,
                defaultextension=".txt",
                filetypes=[("Texto", "*.txt")],
            )
            if not caminho:
                return False
            try:
                texto = self.editor.get("1.0", "end-1c")
                Path(caminho).write_text(texto, encoding="utf-8")
                self.origem = Path(caminho).resolve()
                self.dirty = False
                self.editor.edit_modified(False)
                self.contagem.set(f"{len(texto.split())} palavras · {self.origem.name}")
                return True
            except OSError as exc:
                self._erro(str(exc))
                return False

        def _tag(self, texto: str) -> None:
            if not self.ocupado:
                self.editor.insert("insert", texto)
                self.editor.focus_set()

        def _iniciar(self, modo: str, extras_cfg: dict | None = None) -> None:
            if self.ocupado:
                return
            try:
                cfg = self._configuracao()
                if self.projeto and modo in ('analisar', 'gerar', 'amostra'):
                    if not self._salvar_projeto(): return
                    cfg = {**cfg, **self.projeto.configuracao()}
                    if modo == 'gerar':
                        if not self.projeto.estado['segmentos']:
                            raise ValueError('Confira o roteiro para preparar os segmentos do projeto primeiro.')
                        cfg.update(self.projeto.preparar_execucao())
                if extras_cfg:
                    cfg.update(extras_cfg)
                texto = self.editor.get("1.0", "end-1c")
                if modo in ("validar", "metricas"):
                    if not self.manifesto:
                        raise ValueError("Gere um áudio ou abra um manifesto concluído.")
                else:
                    if not texto.strip():
                        raise ValueError("Abra ou escreva um roteiro primeiro.")
                if modo == "amostra":
                    texto = self.editor.get("sel.first", "sel.last") if self.editor.tag_ranges("sel") else texto.strip().split("\n\n")[0]
                    if len(texto) > 1200:
                        raise ValueError("Selecione um trecho de até 1.200 caracteres para a amostra.")
                    cfg["saida"] += ".amostra"
                pedido = salvar_pedido(modo, texto, cfg, self.origem, self.manifesto)
                self._preferencias_salvar()
                self.processo.iniciar(str(Path(self.vars["python"].get().strip()).expanduser()), pedido)
            except (OSError, ValueError, RuntimeError) as exc:
                self._erro(str(exc))
                return

            self.modo = modo
            self.plano_recebido = None
            self.desfecho = "Tarefa concluída."
            self.falhou = False
            self.ocupado = True
            self._habilitar(False)
            self.progresso.configure(value=0, maximum=1)
            self.status.set("Iniciando o processo de trabalho…")
            if modo in ("gerar", "amostra"):
                self.manifesto = None
                self.arquivos = []
                self.resultado_ref.set("Novo resultado em processamento…")
                self.stop.configure(state="normal")
            self.tree.delete(*self.tree.get_children())
            self.segmentos = {}
            self.tabs.select(1)

        def _habilitar(self, habilitar: bool) -> None:
            self._limpar_widgets()
            for w, estado in self.editaveis:
                w.configure(state=estado if habilitar else "disabled")
            self.editor.configure(state="normal" if habilitar else "disabled")
            self.ouvir.configure(state="normal" if habilitar and self.arquivos else "disabled")
            for botao in (self.validar, self.metricas):
                botao.configure(state="normal" if habilitar and self.manifesto else "disabled")
            if habilitar:
                self.stop.configure(state="disabled")

        def _interromper(self) -> None:
            self.processo.interromper_apos_segmento()
            self.stop.configure(state="disabled")
            self.status.set("Interrupção solicitada. O trecho atual será preservado antes de parar.")

        def _linha(self, seg: dict, estado: str) -> None:
            key = str(seg["id"])
            self.segmentos[key] = {**self.segmentos.get(key, {}), **seg}
            inicio = f"{seg['inicio_s']:.2f}s" if seg.get("inicio_s") is not None else "—"
            vals = (seg["id"], seg["idioma"], inicio, estado, seg["texto"])
            if self.tree.exists(key):
                self.tree.item(key, values=vals)
            else:
                self.tree.insert("", "end", iid=key, values=vals)

        def _eventos(self) -> None:
            try:
                for _ in range(200):
                    e = self.processo.eventos.get_nowait()
                    tipo = e["tipo"]
                    if tipo == "log":
                        self._registro(e["texto"])
                    elif tipo == "plano":
                        if self.modo == 'analisar': self.plano_recebido = e['segmentos']
                        for seg in e["segmentos"]:
                            self._linha(seg, "Preparado")
                        self.progresso.configure(maximum=max(1, e["total"]))
                        if self.modo == "analisar":
                            self.desfecho = f"Roteiro conferido: {e['total']} segmentos preparados."
                    elif tipo == "etapa":
                        self.status.set(e["mensagem"])
                        if e.get("etapa") == "montagem":
                            self.stop.configure(state="disabled")
                    elif tipo in ("segmento", "validacao_segmento"):
                        seg = e["segmento"]
                        if tipo == "segmento":
                            estado = "Cache" if seg.get("reutilizado") else "Gerado"
                        else:
                            estado = f"WER {seg['wer']:.1%}" if "wer" in seg else "Métricas"
                            if seg.get('metricas', {}).get('avisos'):
                                estado += f" · {len(seg['metricas']['avisos'])} aviso(s)"
                        self._linha(seg, estado)
                        self.progresso.configure(maximum=max(1, e["total"]), value=e["concluidos"])
                        self.status.set(f"{e['concluidos']} de {e['total']} segmentos · {estado}")
                    elif tipo == "resultado":
                        self.manifesto = Path(e["manifesto"])
                        self.arquivos = e["arquivos"]
                        self.resultado_ref.set(f"Resultado associado: {self.manifesto}")
                        self.desfecho = "Áudio pronto. Você pode ouvir o resultado ou validar os trechos."
                    elif tipo == "resultado_validacao":
                        if e["aprovado"] is None:
                            self.desfecho = "Métricas coletadas; não equivalem a aprovação da fala."
                        else:
                            aprov_txt = "todos os trechos dentro do limite." if e["aprovado"] else "há trechos acima do limite."
                            self.desfecho = f"WER global {e['wer_global']:.1%} · {aprov_txt}"
                        self._registro(f"Relatório: {e['relatorio']}")
                    elif tipo == 'tomada_registrada':
                        self._registro('Tomada preservada no histórico do projeto.')
                    elif tipo == 'estado_fila':
                        if e['estado'] != 'concluida':
                            self.desfecho = e.get('erro') or ('Tarefa ' + e['estado'] + '. Consulte a fila para retomar.')
                            self.falhou = e['estado'] not in ('interrompida',)
                    elif tipo == "interrompido":
                        self.desfecho = f"Interrompido com {e['concluidos']} segmentos concluídos. Gere novamente para retomar."
                    elif tipo == "erro":
                        self.falhou = True
                        self.desfecho = e["mensagem"]
                        self._registro(e["mensagem"])
                        self.tabs.select(2)
                    elif tipo == "processo_encerrado":
                        if e["codigo"] and not self.falhou:
                            self.desfecho = f"O processo encerrou com código {e['codigo']}. Confira o registro e o Python selecionado."
                            self.tabs.select(2)
                        self.ocupado = False
                        if self.projeto and not e['codigo'] and not self.falhou:
                            try:
                                from projetos import Projeto
                                atual = Projeto.abrir(self.projeto.caminho)
                                if not self.projeto.mesmo_conteudo(atual):
                                    raise ValueError('O projeto foi editado em outra sessão durante a tarefa. Reabra para conferir; o resultado anterior está preservado.')
                                self.projeto = atual
                                if self.modo == 'analisar' and self.plano_recebido is not None:
                                    self.projeto.conferir_plano(self.plano_recebido)
                                    from revisao_segmentos import aplicar_revisao, documento_revisao
                                    estado = self.projeto.estado
                                    for seg in aplicar_revisao(estado['segmentos'], documento_revisao(estado['segmentos'], estado['edicoes'])):
                                        self._linha(seg, 'Conferido')
                            except (OSError, ValueError, sqlite3.Error) as exc:
                                self.desfecho = f'Áudio/execução preservado; falha ao atualizar projeto: {exc}'
                        self._habilitar(True)
                        self.status.set(self.desfecho)
                        if self.fechar_depois:
                            self.fechar_depois = False
                            self._fechar()
            except queue.Empty:
                pass
            if self.root.winfo_exists():
                self.root.after(120, self._eventos)

        def _registro(self, texto: str) -> None:
            self.log.configure(state="normal")
            self.log.insert("end", texto + "\n")
            if int(self.log.index("end-1c").split(".")[0]) > 1200:
                self.log.delete("1.0", "201.0")
            self.log.see("end")
            self.log.configure(state="disabled")

        def _carregar_manifesto(self) -> None:
            caminho = filedialog.askopenfilename(
                parent=self.root,
                filetypes=[("Manifesto TTSBR", "*.blocos.json"), ("JSON", "*.json")],
            )
            if not caminho:
                return
            try:
                p = Path(caminho).resolve()
                dados = json.loads(p.read_text(encoding="utf-8"))
                if dados.get("estado") != "concluido" or not dados.get("segmentos"):
                    raise ValueError("Selecione o manifesto de uma síntese concluída.")
                self.tree.delete(*self.tree.get_children())
                self.segmentos = {}
                for seg in dados["segmentos"]:
                    seg = dict(seg)
                    arquivo = Path(seg["arquivo"])
                    seg["arquivo"] = str(arquivo if arquivo.is_absolute() else p.parent / arquivo)
                    self._linha(seg, "Disponível")
                self.manifesto = p
                self.resultado_ref.set(f"Resultado associado: {p}")
                base = str(p).removesuffix(".blocos.json")
                self.arquivos = [f"{base}.{ext}" for ext in ("wav", "mp3", "srt", "vtt") if Path(f"{base}.{ext}").is_file()]
                self.tabs.select(1)
                self._habilitar(True)
                self.status.set("Manifesto carregado. Os segmentos precisam estar disponíveis no disco.")
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                self._erro(str(exc))

        def _selecionar(self, evento=None) -> None:
            selecao = self.tree.selection()
            if selecao:
                s = self.segmentos[selecao[0]]
                self.detalhe.set(s["texto"] + ("\n" + s["arquivo"] if s.get("arquivo") else ""))
                if s.get('metricas'):
                    self.detalhe.set(self.detalhe.get() + '\nAvisos de sinal: ' +
                                     (', '.join(s['metricas']['avisos']) or 'nenhum') +
                                     '. Clique duas vezes para ouvir no resultado a partir deste segmento.')

        def _ouvir_no_resultado(self):
            selecao = self.tree.selection()
            if not selecao: return
            wav = next((p for p in self.arquivos if p.lower().endswith('.wav')), None)
            if wav:
                self._player(wav, inicio=self.segmentos[selecao[0]].get('inicio_s') or 0)
            else:
                self._ouvir_trecho()

        def _ouvir_trecho(self) -> None:
            selecao = self.tree.selection()
            if selecao and self.segmentos[selecao[0]].get("arquivo"):
                self._player(self.segmentos[selecao[0]]["arquivo"])
            else:
                self._erro("Selecione um segmento já gerado para ouvir.")

        def _regerar_trecho(self) -> None:
            selecao = self.tree.selection()
            if not selecao:
                self._erro("Selecione um segmento na tabela para regerar.")
                return
            seg_id = self.segmentos[selecao[0]]["id"]
            self._iniciar("gerar", extras_cfg={"refazer_segmentos": str(seg_id), 'refazer': False})

        def _ouvir(self) -> None:
            if self.arquivos:
                alvo = next(
                    (p for p in self.arquivos if p.endswith(".wav")),
                    next((p for p in self.arquivos if p.endswith(".mp3")), self.arquivos[0]),
                )
                self._player(alvo)

        def _abrir_caminho(self, caminho: str | Path) -> None:
            try:
                abrir_no_sistema(caminho)
            except OSError as exc:
                self._erro(str(exc))

        def _erro(self, mensagem: str) -> None:
            messagebox.showerror("TTSBR", mensagem, parent=self.root)

        def _fechar(self) -> None:
            fila = getattr(self, 'fila_janela', None)
            if fila and fila.janela.winfo_exists() and fila.ocupada:
                fila.janela.lift(); return
            biblioteca = getattr(self, 'biblioteca_janela', None)
            if biblioteca and biblioteca.janela.winfo_exists():
                biblioteca.janela.lift()
                return
            if self.ocupado:
                escolha = messagebox.askyesnocancel('Tarefa na fila',
                    'Sim: interromper com segurança e aguardar antes de fechar. Não: fechar a janela e manter a fila em execução. Cancelar: voltar.', parent=self.root)
                if escolha is True:
                    self.fechar_depois = True
                    if self.modo in ("gerar", "amostra"):
                        self._interromper()
                    else:
                        self.status.set("Aguardando a tarefa terminar para fechar…")
                    return
                if escolha is None: return
                self._fechar_player()
                self._preferencias_salvar()
                self.root.destroy()
                return
            if not self._confirmar_edicao():
                return
            self._fechar_player()
            try:
                self._preferencias_salvar()
            except OSError as exc:
                if not messagebox.askyesno(
                    "Preferências",
                    f"Não foi possível salvar as preferências: {exc}\nFechar mesmo assim?",
                    parent=self.root,
                ):
                    return
            self.root.destroy()


def iniciar_janela() -> int:
    """Inicializa a interface gráfica do TTSBR."""
    if not TKINTER_DISPONIVEL:
        print(
            "Este Python não possui Tkinter. Consulte docs/GUI.md para instalar ou usar outro Python.",
            file=sys.stderr,
        )
        return 1

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Não foi possível abrir uma janela gráfica: {exc}", file=sys.stderr)
        return 1

    Aplicativo(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(iniciar_janela())
