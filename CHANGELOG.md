# Histórico de alterações

## Não versionado — 29/10/2026

As entradas abaixo consolidam as três entregas locais. Não representam uma versão publicada nem garantem que todas as alterações já tenham sido incluídas em um commit.

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
