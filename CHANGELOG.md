# Histórico de alterações

## 1.2.0 — Waveform, Audiolivros M4B, Léxico de IA/Tonicidade e Streaming HTTP — 07/11/2026

- **Waveform interativo e catálogo de vozes (M1):**
  - Renderização leve do envelope de amplitude no Canvas do `player_gui.py` usando `calcular_envelope_wav()` em blocos (`reproducao.py`), sem alocação desnecessária de memória.
  - Agulha de reprodução vertical sincronizada com o transporte, scrub/seek interativo ao clicar ou arrastar no gráfico e marcadores visuais para picos saturados e silêncios.
  - Catálogo unificado de vozes (`vozes.py`) combinando vozes embutidas do XTTS v2 por idioma com os perfis cadastrados na `BibliotecaVozes` (E1).
  - Botão "Ouvir prévia da voz" na GUI para testar referências gravadas ou amostras nativas sem travar a interface.
- **Audiolivros `.m4b` com capítulos embutidos (M2):**
  - Geração de manifesto `;FFMETADATA1` (`audio_persistente.py`) com escapamento estrito de caracteres especiais e blocos `[CHAPTER]` com base de tempo `1/1000`.
  - Exportação direta para contêiner `.m4b` (áudio AAC mono com `-movflags +faststart`) via flag `--m4b` ou pelo seletor de formatos.
  - Suporte a arte de capa (`--capa <imagem.jpg|png>`) injetada como stream de vídeo estático (`attached_pic`) nos formatos `.m4b` e `.mp3`.
  - Manifesto `.blocos.json` enriquecido com a lista de capítulos navegáveis (`capitulos_embutidos`).
- **Fonética contextual, vocabulário de IA e novos tons (M3):**
  - Guia contextual de tonicidade para o português brasileiro (`GUIA_TONICIDADE_PTBR` em `normalizador.py`), corrigindo deslizes fonéticos comuns em paroxítonas como *recorde*, *rubrica*, *circuito*, *gratuito*, *fluido*, *pudico*, *ibero*, etc., mantendo as legendas `.srt`/`.vtt` ortograficamente puras.
  - Expansão léxica para termos de inteligência artificial e aprendizado de máquina (*tokenization*, *loss function*, *inference*, *checkpoint*, *overfitting*, *underfitting*, *zero-shot*, *few-shot*, *rag*, *latency*, *throughput*) com pronúncias adaptadas para PT-BR e ES.
  - Novos perfis predefinidos de tom de locução nas tags `[tom:...]`: `noticia` (cadência ágil e pausas compactas), `narracao` (ritmo documental equilibrado) e `entusiasmado` (leve ganho de projeção e velocidade).
  - Corpus público de avaliação ampliado de 24 para 30 casos de teste em `avaliacao/corpus_pt_es.txt`.
- **Streaming HTTP de áudio em tempo real (M4):**
  - Endpoint `/v1/audio/speech` compatível com OpenAI atualizado com suporte a `"stream": true` (ou query `?stream=1`) para formatos `wav`, `pcm` e `raw`.
  - Resposta via `Transfer-Encoding: chunked` transmitindo blocos de áudio PCM mono a 24 kHz e pausas em tempo real assim que cada segmento é processado ou recuperado do cache.
  - Cabeçalho WAV streaming de 44 bytes para reprodução direta em clientes de áudio sem espera pelo término da síntese.
  - Tratamento resiliente de desconexão do cliente (`BrokenPipeError`/`ConnectionResetError`): cancelamento imediato e seguro entre segmentos via `should_stop`, liberação de travas e integridade absoluta do cache de segmentos.
- **Estabilização e distribuição (M5):**
  - Suíte de **192 testes** automatizados aprovada com 100% de sucesso no macOS Apple Silicon / Python 3.12.14.
  - Pacote de distribuição `1.2.0` (`wheel` e `sdist`) gerado e validado em caminho com espaços e acentos.

- Ensaio comparativo real XTTS v2 vs. OmniVoice 0.2.1 (`c5fdb5ccb189668d56333f77ba2629f4cd7535f4`) executado em PT-BR e ES (`mps` e `cpu`), com medição de carga fria, síntese quente, RTF, memória RSS, métricas acústicas e WER via Whisper (`0,0%` em ambos os motores).
- Adicionado fallback automático via `soundfile` em `torchaudio.load` dentro de `motores.py` para manter a clonagem XTTS funcional em ambientes com Torchaudio ≥ 2.9 sem `libtorchcodec` nativo.
- Decisão arquitetural da E4 registrada em `docs/MOTORES_E4.md`: XTTS v2 mantido como motor oficial integrado (`RTF ~0,56` em MPS contra `~2,30` do OmniVoice) e OmniVoice preservado no worker/supervisor isolado (`comparar_motores_e4.py`).
- Distribuição promovida para `1.1.0` com **183 testes** aprovados no macOS/Python 3.12.14.

## 1.0.1 — Qualidade, presets e distribuição do preview E0–E6 — 07/11/2026

- Normalizador PT/ES ampliado com unidades compostas (`km/h`, `MB/s`), potências (`m²`, `m³`), temperaturas (`°C`, `°F`, `K`), horários `12h30`, ordinais (`1º`, `2ª`, `1er`, `3er`), intervalos (`10-20`) e `€` posposto. Corpus público expandido para 12 casos por idioma em `avaliacao/corpus_pt_es.txt`.
- Presets `--preset` (`narracao`, `amostra`, `revisao`) com precedência de flags explícitas e botão de restauração de padrões na GUI.
- Medição automática do loudness integrado do arquivo final (`lufs_integrado`, `true_peak_dbtp`, `lra_lu` e duração) no manifesto, separada das métricas por segmento.
- Exportação por capítulo (`--por-capitulo` em cabeçalhos `#`/`##`) e metadados básicos (`--titulo`, `--autor`).
- Exportação e importação de pacote portátil de projeto (`ttsbr.pacote_projeto` v1) com referência WAV opcional validada por tamanho, extensão, caminho relativo e SHA-256.
- Distribuição `1.0.1` limpa (`wheel` e `sdist`) sem arquivos AppleDouble, incluindo os roteiros públicos de captação (`captacao_voz_pt.txt` e `captacao_voz_es.txt`), exercitada fora do checkout em caminho com espaços e acentos. **182 testes** aprovados no macOS/Python 3.12.14.

## Motores E4 — concluída — 07/11/2026

- Adaptador XTTS com contrato inicial, fallback `soundfile` para leitura de referências e identificação do motor no manifesto e cache.
- Worker experimental isolado e supervisor com timeout e proteção de saída.
- Verificação da revisão dos pesos contra os metadados de download do Hugging Face (commit e ETag de cada arquivo) antes de iniciar o worker.
- Ambiente OmniVoice 0.2.1 preparado fora do volume exFAT e exercitado com inferência real em PT-BR e ES (`mps` e `cpu`) ao lado do XTTS v2; licenças dos pesos (CC-BY-NC) e do tokenizador (Boson Higgs Audio 2) registradas.

## Fila e supervisão E3 — 07/11/2026

- Fila SQLite com snapshots privados, tentativas, estados, retenção de eventos e retomada por cache verificado.
- Coordenador compartilhado pela GUI/API e guardião independente por tarefa, com limites por etapa e confirmação de encerramento.
- Interrupção segura, cancelamento forçado, recuperação após queda, recibos de conclusão e travas contra colisão com CLI.
- Reconciliação de vínculos de voz e proteção contra aplicar resultados de análise sobre um projeto editado em outra sessão.
- 160 testes aprovados no macOS; GUI desktop, contenção Windows e inferência longa real continuam pendentes.

## Projetos e revisão E2 — 07/11/2026

- Projetos JSON v1 com configurações, glossário congelado, referências, rascunho, backup e controle de revisão entre sessões.
- IDs estáveis, correções de fala separadas do roteiro, verificação do plano, cache compartilhado e snapshots de tomadas com legendas recalculadas.
- Player WAV opcional em subprocesso, controles de pausa/busca, comparação A/B e navegação ao início de segmentos.
- Suíte com 133 testes aprovados; dispositivo de áudio, GUI desktop, clonagem real e Windows ainda sem aprovação nesta entrega.

## Biblioteca de vozes E1 — 07/11/2026

- Biblioteca privada SQLite com tomadas independentes, original preservado, referência WAV e limpeza opcional em cópia.
- Cadastro e seleção na GUI, importação por worker e CLI `--perfil-voz` com verificação de integridade.
- Metadados revisáveis, avisos acústicos, remoção lógica/restauração, bloqueio por vínculo e backup verificado.
- 113 testes aprovados no macOS, incluindo 17 novos da biblioteca com áudio sintético; validação visual, Windows e audição de clonagem continuam pendentes.

## Base E0 do preview — 07/11/2026

- Adicionados diagnóstico público sem modelos e contratos v1 de voz, projeto e tarefa.
- Documentadas persistência, migração, instalação separada do preview e matriz de validação.
- Suíte com 96 testes aprovados no macOS; wheel/sdist construídos e diagnóstico instalado exercitado fora do checkout.
- Esta base ainda não integra biblioteca, projetos ou fila à interface; Windows e audição continuam pendentes.

## Planejamento — 07/11/2026

- Adicionado roadmap 0.9.0 Preview → 1.1.0 com análise do VoiceStudio, entregas, dependências, testes e critérios de promoção.
- Vinculado o plano ao README e ao roadmap geral e incluído o documento nos recursos do pacote. Nenhuma funcionalidade ou versão de pacote foi alterada nesta etapa.

## Documentação — 01/11/2026

- Registrados o estado do projeto, as limitações conhecidas e a execução de 86 testes no macOS.
- Incluídos roteiros de captação de voz em português e espanhol e atualizada a orientação de publicação na estabilização.

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
