# Histórico de alterações

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
