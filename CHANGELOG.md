# Histórico de alterações

## Candidato local de estabilização — 31/10/2026

- Corrigida a construção wheel/sdist com módulos e recursos explícitos e cópia temporária sem metadados AppleDouble.
- Adicionados extra de validação, constraints do ambiente macOS/Python 3.12 e separação de dados da aplicação instalada.
- API rejeita tipos inválidos como erros de entrada, com testes HTTP reais.
- GUI com rolagem nos ajustes avançados e resolução de referências relativa ao roteiro original.
- Manifesto registra hashes dos novos módulos do pipeline.
- Evidências e checklist em `docs/ESTABILIZACAO.md`; GUI visual, Windows e avaliação subjetiva continuam pendentes.

## Refatoração arquitetural, modularização e correções — 31/10/2026

- **Modularização do pipeline (`tts.py`)**: extração de módulos especializados com responsabilidade única:
  - `segmentador.py`: fatiamento de frases, divisão em blocos de até 150 palavras, estimativas e parsing de tags (`[enfase]`, `[pausa:1.5s]`, `[tom:calmo]`).
  - `vozes.py`: catálogo de vozes padrão (`pt`/`es`), mapeamento de apelidos de personagens e resolução de referências de áudio.
  - `processamento_audio.py`: corte de silêncio residual do XTTS, compactação de pausas internas e guardrail de detecção de anomalias acústicas.
- **Desacoplamento léxico (`lexico.py`)**: centralização de tabelas numéricas para extenso, siglas técnicas, unidades de medida e vocabulário técnico de IA em módulo dedicado, simplificando a manutenção e futuras adições.
- **Estruturação da interface gráfica (`gui.py`)**: extração da classe `Aplicativo` para o nível de módulo com tipagem estática e desacoplamento do ciclo de vida do Tkinter.
- **Padronização moderna do pacote (`pyproject.toml`)**: inclusão de manifesto PEP 518/621 com metadados do projeto, dependências, ferramentas de desenvolvimento e pontos de entrada de console (`ttsbr`, `ttsbr-gui`, `ttsbr-api`).
- **Correção fonética em espanhol**: preservação da conjunção "Y" em início de frase, prevenindo conversão indevida para o nome da letra ("ye").
- **Privacidade e ignore**: regras de exclusão de pastas de saída e roteiros pessoais no `.gitignore`.
- **Diretrizes de projeto (`GEMINI.md`)**: diretriz de comandos de terminal com caminhos absolutos completos para o assistente.

## Revisão da documentação — 30/10/2026

- Prioridade de referências de tom, personagem e voz global alinhada ao código.
- README ampliado com uso da API local e seus limites de compatibilidade, concorrência e autenticação.
- Legendas por segmento, processamento LUFS, trilha e falhas persistentes após tentativas automáticas explicados.
- Avaliação inicial identificada como resultado histórico, sem atribuí-la à revisão atual.

## Não versionado — 29/10/2026

As entradas abaixo consolidam as entregas locais. Não representam uma versão publicada nem garantem que todas as alterações já tenham sido incluídas em um commit.

### Evoluções de estúdio, confiabilidade e ecossistema (Fases 1, 2 e 3)

- Normalização fonética natural de moedas em português ("real/reais" e "dólar/dólares", sem a inserção redundante de "brasileiro/americano").
- Garantia de normalização Unicode NFC em todo o pipeline, evitando falhas de pronúncia de caracteres acentuados (como til `~`) no macOS.
- Guia fonético de tonicidade para palavras paroxítonas no XTTS v2 (`\banos\b` → `ânos`) e preservação de cadência em vírgulas terminais de cláusulas.
- Compactação inteligente de micro-silêncios internos gerados pelo modelo antes de pontuações ditadas (ex.: "vírgula").
- Suporte a novos apelidos de locutores de estúdio (`Tammie` e `Ema` mapeados para `Tammie Ema`).
- Exportação nativa de legendas sincronizadas por segmento (`.srt` e `.vtt`) via `--srt`, `--vtt` ou `--formatos` (liberado).
- Masterização final em LUFS (`--lufs`, padrão EBU R128 via FFmpeg) e seleção de taxa de amostragem (`--taxa-amostragem` em 24000, 44100 ou 48000 Hz) (liberado).
- Diálogos com múltiplas vozes clonadas por personagem (`--vozes-personagens` ou `[arquivo.wav|pt]:`), com cache SHA-256 individual por locutor (liberado).
- Guardrail anti-alucinação e silêncio total com repetição automática por segmento (`--max-tentativas`, padrão 2) (liberado).
- Regeneração seletiva de trechos específicos (`--refazer-segmentos` na CLI e botão **Regerar trecho selecionado** na GUI), preservando os demais segmentos do cache (liberado).
- Tags de expressão por tom (`[tom:calmo]`, `[tom:enfatico]`, `[tom:suave]`, `[tom:animado]`, `[tom:serio]`, `[tom:sussurro]`) com presets de cadência/volume (liberado) e condicionamento opcional por amostra de áudio (`--vozes-tons` ou `[tom:arquivo.wav]`, em beta).
- Higienização opcional do áudio de referência (`--limpar-referencia`) com filtros `highpass`, `lowpass`, `afftdn` e `loudnorm` via FFmpeg (beta).
- Mixagem opcional de trilha sonora de fundo (`--trilha` e `--volume-trilha`) com *auto-ducking* (`sidechaincompress`) via FFmpeg (beta).
- Servidor HTTP local compatível com o endpoint OpenAI TTS (`servidor_api.py`, rota `/v1/audio/speech`), compartilhando o cache de segmentos (beta).

### Interface gráfica inicial

- Janela pessoal com Tkinter/ttk para roteiro, configurações, amostra, progresso e revisão.
- Workers isolados com Python configurável e eventos estruturados, reutilizando a CLI.
- Conferência de roteiro com `--analisar`, sem inferência ou arquivos finais.
- Interrupção cooperativa entre segmentos, com cache preservado e retomada.
- Reprodução pelo player do sistema, validação por trecho e métricas pela GUI.
- Preferências e snapshots privados em `local/gui/`; iniciadores para macOS e Windows.
- Testes da integração sem display; validação visual no desktop ainda pendente.

### Arquivos locais e privacidade

- Regras de ignore ampliadas para roteiros locais, referências de voz, credenciais, modelos e artefatos gerados.
- Textos de uso local da raiz retirados do índice, com cópias preservadas no disco.
- Exemplos públicos neutros em `exemplos/` e comandos da documentação atualizados.
- Histórico anterior preservado; a remoção no estado atual não apaga versões já publicadas.

### Licenciamento

- Licença MIT para o código e a documentação originais, com copyright de 2026 de Ely do Carmo Barros.
- Avisos separados para XTTS v2, saídas de áudio e componentes de terceiros.
- Documentação esclarecendo que a MIT não amplia as permissões da CPML do modelo.

### Primeira entrega — validação e preparação

- Validação antecipada de parâmetros, arquivos, texto sem fala, formatos e idiomas de personagem.
- Preservação de pontos nos nomes base de saída.
- Interpretação de tags antes dos cortes de comprimento.
- Erros explícitos para tags desconhecidas, incompletas ou com parâmetros inválidos.
- Plano compartilhado entre texto do manifesto e síntese.

### Segunda entrega — persistência e retomada

- WAV e metadados persistidos por segmento, com verificação de integridade SHA-256.
- Retomada automática e opção `--refazer`.
- Carregamento do XTTS apenas quando há inferência pendente.
- Montagem em disco com buffers limitados e exportação por arquivos temporários.
- Progresso no manifesto e proteção contra ultrapassar o limite WAV RIFF.

### Terceira entrega — normalização e avaliação

- Datas, horários, moedas e sinais negativos em português e espanhol.
- Tempos de início e fim por segmento e metadados de ambiente no manifesto.
- Validação com `--manifesto`, transcrição no idioma de cada trecho e WER por idioma e global.
- Relatório JSON, caminho configurável e modo `--somente-metricas`.
- Métricas de duração, RMS, pico e amostras próximas da saturação.
- Corpus PT/ES, ficha de audição e resultado inicial com XTTS/Whisper reais.

### Correções anteriores

- Importação da normalização espanhola no validador e conversão de números grandes em espanhol.
- Mescla de glossários gerais e por idioma, com prioridade sobre siglas embutidas.
- WER por distância mínima de edição e alinhamento entre manifesto e texto sintetizado.
- README com banner, navegação e referências recolhíveis.
