# Roadmap Técnico — TTSBR v1.2.0

[README](../README.md) · [Roadmap geral](ROADMAP.md) · [Ciclo anterior (0.9.0 → 1.1.0)](ROADMAP_0.9.0.md)

> **Base de partida:** versão `1.1.0` (commit `6b72549`, 183 testes aprovados em macOS Apple Silicon / Python 3.12.14, E0–E6 concluídas).

## Objetivo da v1.2.0

Consolidar a experiência de produção e masterização do estúdio pessoal PT-BR/ES sobre a base arquitetural entregue na `1.1.0`, adicionando **inspeção visual de áudio (waveform)**, **catálogo unificado de vozes com prévia auditiva**, **empacotamento nativo de audiolivros `.m4b` com capítulos embutidos**, **refinamento contextual de tonicidade e estilos de locução** e **streaming HTTP de baixa latência** na API local.

---

## Princípios e restrições mantidos

1. **Compatibilidade estrita com contratos `v1`:** projetos (`ttsbr.projeto`), perfis de voz (`ttsbr.voz`), pacotes portáveis (`ttsbr.pacote_projeto`), revisões (`ttsbr.revisao`) e fila (`ttsbr.tarefa`) criados na `1.1.0` continuam abrindo sem necessidade de migração destrutiva.
2. **Nenhuma dependência pesada obrigatória para a GUI:** a renderização da forma de onda deve usar apenas a biblioteca padrão (`wave` / `array`) ou `numpy` já presente no ambiente de síntese + `tkinter.Canvas`, sem exigir bibliotecas gráficas externas.
3. **Execução offline e privacidade:** prévias de voz, capítulos `.m4b` e streaming local operam 100% offline sobre o cache/modelos locais, sem telemetria nem downloads implícitos.
4. **Volumes externos (`exFAT`) e caminhos com espaços/acentos:** todas as operações de arquivo e empacotamento devem preservar criação/cópia segura sem depender de hardlinks e ignorar metadados AppleDouble (`._*`).

---

## Etapas de Entrega (M1 a M5)

```
M1 (Waveform + Catálogo de Vozes na GUI) ──┐
M2 (Audiolivros .m4b com capítulos FFmpeg) ├─► M5 (Estabilização, Documentação e Release 1.2.0)
M3 (Fonética Contextual PT/ES + Tons)      │
M4 (Streaming HTTP na API Local) ──────────┘
```

| Etapa | Escopo Principal | Módulos Afetados | Tamanho |
|---|---|---|---|
| **M1** | Forma de onda (*waveform*) interativa no player e catálogo visual de vozes com prévia | `player_gui.py`, `reproducao.py`, `gui.py`, `gui_core.py`, `vozes.py` | M |
| **M2** | Exportação de audiolivro `.m4b` em arquivo único com capítulos embutidos (`FFMETADATA1`) e capa opcional | `audio_persistente.py`, `segmentador.py`, `tts.py`, `gui.py`, `gui_core.py` | M |
| **M3** | Guia contextual de tonicidade para paroxítonas críticas, expansão léxica de IA e novas tags `[tom:...]` | `lexico.py`, `normalizador.py`, `segmentador.py`, `vozes.py`, `avaliacao/corpus_pt_es.txt` | P/M |
| **M4** | Streaming de áudio em tempo real (*Chunked Transfer Encoding*) em `/v1/audio/speech` | `servidor_api.py`, `tts.py` | M |
| **M5** | Validação integrada, pacote `1.2.0` (`wheel`/`sdist`) e atualização documental | `pyproject.toml`, `scripts/construir.py`, `docs/*`, `CHANGELOG.md` | P |

---

### M1 — Forma de onda (*Waveform*) no player integrado e catálogo de vozes com prévia

**Motivação:** O player integrado da `1.1.0` (`player_gui.py`) já permite reproduzir, pausar, buscar por tempo, saltar para avisos acústicos e comparar tomadas A/B, mas o usuário ainda não enxerga onde estão os picos, silêncios ou cortes no segmento sem ouvir tudo. Além disso, a escolha entre locutores embutidos (`Luis Moray`, `Sofia Hellen`, `Tammie Ema`, `Alma María`, etc.) e perfis da Biblioteca de Vozes (`E1`) pode ser unificada com audição rápida.

**Entregas:**
- **Extrator leve de envelope de amplitude (`reproducao.py` / `player_gui.py`):**
  - Função pura `calcular_envelope_wav(caminho_wav, colunas=240)` lendo o WAV PCM em blocos sem carregar horas de áudio na memória, retornando valores normalizados `[0.0..1.0]` de pico/RMS por coluna e marcadores de silêncio/saturação.
- **Canvas interativo no `PainelPlayer` (`player_gui.py`):**
  - Desenho das barras de amplitude no `tk.Canvas`, cursor vertical sincronizado com a posição de reprodução e clique direto no gráfico para buscar (`seek`) o segundo correspondente.
  - Destaque visual em cor distinta para regiões com aviso acústico (ex.: saturação ou silêncio prolongado).
- **Catálogo unificado e prévia de voz (`gui.py` / `vozes.py`):**
  - Seletor que lista locutores nativos do XTTS por idioma (`pt`/`es`) e perfis ativos da `BibliotecaVozes`, exibindo idioma e estilo.
  - Botão **"Ouvir prévia"**: para perfis da biblioteca, reproduz a referência WAV cadastrada no player integrado; para locutores embutidos, sintetiza (ou reutiliza do cache em `TTSBR_HOME`) uma frase curta padrão de demonstração.

**Critérios de aceite e testes (`tests/test_reproducao.py`, `tests/test_gui.py`):**
- Cálculo de envelope exato para WAVs sintéticos (silêncio, senoide constante, pico saturado) e rejeição limpa de arquivos inválidos.
- Clique na coordenada X do canvas converte proporcionalmente para a posição em segundos `[0, duracao_s]` e aciona `buscar()`.
- Catálogo lista vozes nativas + perfis cadastrados sem duplicar entradas nem bloquear a thread principal da GUI.

---

### M2 — Audiolivros `.m4b` com capítulos navegáveis e metadados embutidos

**Motivação:** Na `1.1.0` (E5), adicionamos `--por-capitulo` (que gera um arquivo separado por capítulo `#` / `##`) e metadados `--titulo` / `--autor`. Para audiolivros longos em players dedicados (Apple Books, VLC, Smart AudioBook Player), o formato ideal é um único arquivo `.m4b` (AAC em contêiner MP4) com índice de capítulos embutido.

**Entregas:**
- **Gerador de manifesto `FFMETADATA1` (`audio_persistente.py`):**
  - Função `gerar_ffmetadata(titulo, autor, capitulos)` que produz o cabeçalho `;FFMETADATA1` com `title`, `artist`/`author` e blocos `[CHAPTER]` (`TIMEBASE=1/1000`, `START`, `END`, `title`) calculados a partir dos tempos reais acumulados de cada capítulo no manifesto.
  - Escapamento seguro de caracteres especiais (`=`, `;`, `#`, `\`, quebras de linha) conforme especificação do FFmpeg.
- **Exportação `.m4b` e capa opcional (`audio_persistente.py`, `tts.py`, `gui.py`):**
  - Inclusão de `m4b` entre os formatos aceitos em `--formatos` (e flag de atalho `--m4b`), codificando áudio AAC mono com `-movflags +faststart` e injetando o arquivo temporário `ffmetadata` via FFmpeg.
  - Suporte opcional a `--capa <imagem.jpg|png>` para embutir arte de capa (*cover art* `attached_pic`) no `.m4b` e `.mp3`.
  - Registro dos capítulos com tempos de início/fim (`capitulos: [{id, titulo, inicio_s, fim_s}]`) dentro do manifesto `.blocos.json`.

**Critérios de aceite e testes (`tests/test_cli.py`, `tests/test_audio_pipeline.py`):**
- Roteiro com múltiplos capítulos `# Capítulo 1` / `## Parte 2` gera arquivo `.m4b` íntegro.
- Inspeção via `ffmpeg -i` / `ffprobe` (ou parser do manifesto `FFMETADATA1`) comprova a presença dos capítulos com `START`/`END` monotônicos e títulos preservados, inclusive com acentos e símbolos escapados.

---

### M3 — Fonética contextual PT-BR/ES, vocabulário técnico e novas tags de estilo

**Motivação:** O XTTS v2 ocasionalmente desloca a sílaba tônica de certas paroxítonas em português ou pronuncia termos técnicos estrangeiros de forma literal. Além disso, roteiros de notícias e narração documental se beneficiam de perfis de cadência predefinidos nas tags `[tom:...]`.

**Entregas:**
- **Expansão do léxico técnico (`lexico.py`):**
  - Inclusão dos termos pendentes do backlog de IA/computação (*tokenization*, *loss function*, *inference*, *checkpoint*, *overfitting*, *underfitting*, *zero-shot*, *few-shot*, *rag*, *latency*, *throughput*) com adaptações fonéticas testadas para PT-BR e ES.
- **Guia contextual de tonicidade (`normalizador.py`, `lexico.py`):**
  - Mapa auditado de paroxítonas críticas em PT-BR onde o modelo desliza a tonicidade, aplicado apenas na camada fonética limpa e com fronteiras de palavra (`\b...\b`), garantindo zero interferência no espanhol e nos arquivos `.srt`/`.vtt` (que usam o texto original sem truques fonéticos).
- **Novos perfis de tom embutidos (`segmentador.py`, `vozes.py`):**
  - Expansão dos tons reconhecidos por `[tom:...]` para incluir `noticia` (levemente mais ágil, pausas enxutas), `narracao` (cadência equilibrada) e `entusiasmado` (leve ganho de projeção e ritmo), mantendo total compatibilidade com `--vozes-tons` para quem quiser associar WAVs de referência específicos a cada tom.
- **Ampliação do corpus público (`avaliacao/corpus_pt_es.txt`):**
  - Novos casos cobrindo os termos técnicos adicionados e as tags `[tom:noticia]`, `[tom:narracao]` e `[tom:entusiasmado]`.

**Critérios de aceite e testes (`tests/test_normalizador.py`, `tests/test_cli.py`):**
- Testes unitários de cada termo novo em PT e ES sem falsos positivos em palavras parciais.
- Legendas `.srt` e `.vtt` continuam livres de tags `[tom:...]` e preservam a grafia ortográfica padrão.

---

### M4 — Streaming HTTP de áudio em tempo real na API local

**Motivação:** Atualmente, `POST /v1/audio/speech` em `servidor_api.py` aguarda a síntese de todos os segmentos e a exportação completa antes de devolver o arquivo inteiro. Para assistentes de voz locais, leitores de tela e integrações interativas, enviar o áudio segmento a segmento reduz drasticamente o tempo até o primeiro áudio (*Time-To-First-Byte*).

**Entregas:**
- **Modo streaming opcional em `/v1/audio/speech` (`servidor_api.py`):**
  - Aceitar `"stream": true` no corpo JSON (ou `"stream_format": "audio"` / query `?stream=1`), mantendo o comportamento síncrono padrão quando omitido para não quebrar clientes existentes.
  - Em modo streaming com formato `wav` ou `pcm`, responder com `Transfer-Encoding: chunked` (ou fluxo contínuo de blocos PCM mono 16 bits / 24 kHz) enviando cada segmento + pausa imediatamente após sua geração/recuperação do cache.
- **Cancelamento limpo por desconexão do cliente:**
  - Se o cliente HTTP fechar o socket (`BrokenPipeError` / `ConnectionResetError`) no meio da geração, interromper a síntese entre segmentos sem derrubar o servidor nem corromper o cache de segmentos já concluídos.

**Critérios de aceite e testes (`tests/test_estabilizacao.py`):**
- Teste HTTP real verificando que no modo `"stream": true` o primeiro bloco de bytes chega antes do término do último segmento e que a concatenação dos blocos corresponde a um sinal PCM/WAV válido.
- Desconexão forçada do cliente no primeiro segmento encerra a requisição limpiamente e a requisição seguinte responde `200 OK`.

---

### M5 — Estabilização, Empacotamento e Release `1.2.0`

**Entregas:**
- Atualização da versão para `1.2.0` em `pyproject.toml` e `tests/test_estabilizacao.py`.
- Atualização de `README.md`, `docs/GUI.md`, `docs/REFERENCIA.md`, `docs/ARQUITETURA.md`, `docs/ROADMAP.md` e `CHANGELOG.md`.
- Construção limpa (`scripts/construir.py`) gerando `dist/ttsbr-1.2.0-py3-none-any.whl` e `dist/ttsbr-1.2.0.tar.gz`, validada fora do checkout em caminho com espaços e acentos.

---

## Resumo de Critérios para Publicar a `v1.2.0`

- [ ] **M1:** Waveform interativo no player da GUI e catálogo unificado de vozes com prévia testados.
- [ ] **M2:** Exportação `.m4b` com capítulos `FFMETADATA1` e capa opcional validada com FFmpeg real.
- [ ] **M3:** Novos termos técnicos de IA, ajustes de tonicidade PT-BR e tags `[tom:noticia]`, `[tom:narracao]`, `[tom:entusiasmado]` cobertos por testes.
- [ ] **M4:** Streaming HTTP em `/v1/audio/speech` com desconexão segura de cliente testado em servidor local real.
- [ ] **M5:** 100% da suíte automatizada passando no macOS e pacotes `1.2.0` gerados sem artefatos privados ou arquivos AppleDouble.
