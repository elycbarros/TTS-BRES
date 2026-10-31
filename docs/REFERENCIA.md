# Referência de comandos e arquivos

[README](../README.md) · [GUI](GUI.md) · [Arquitetura](ARQUITETURA.md) · [Avaliação](../avaliacao/GUIA.md)

Todos os exemplos partem da raiz do projeto, com o ambiente virtual ativado. Caminhos com espaços devem ficar entre aspas.

## Escolher o fluxo de validação

| Objetivo | Comando | Referência usada |
|---|---|---|
| Conferir um áudio final monolíngue | `python validar_audio.py audio.mp3 texto.txt --idioma pt` | Texto original. |
| Conferir um roteiro PT/ES | `python validar_audio.py --manifesto audio.blocos.json` | Texto efetivamente sintetizado, no idioma de cada segmento. |
| Coletar métricas sem Whisper | `python validar_audio.py --manifesto audio.blocos.json --somente-metricas` | WAVs do cache, sem comparação de palavras. |

O modo com manifesto precisa dos WAVs de `<saida>.segmentos/`. Ele não valida a codificação MP3 nem a montagem do arquivo final. O modo com áudio e texto posicionais transcreve o arquivo informado.

## Síntese: `tts.py`

```bash
python tts.py texto.txt --saida saida/aula.v2 --formatos mp3,wav
python tts.py texto.txt --saida saida/aula.v2 --formatos mp3,wav --refazer
python tts.py --help
```

A tabela completa de opções de síntese e pausas está no [README](../README.md#opcoes).

- `--analisar` prepara e imprime os segmentos, sem carregar XTTS nem criar manifesto, cache ou áudio. As validações da entrada continuam ativas.
- `--saida` é o nome **base**. `aula.v2` gera `aula.v2.mp3`; `aula.mp3` gera `aula.mp3.mp3` se MP3 estiver selecionado.
- Formatos são convertidos para minúsculas e duplicatas são removidas (`mp3`, `wav`, `srt`, `vtt`). Listas com itens vazios, como `mp3,`, são rejeitadas.
- `--wav`, `--srt` e `--vtt` acrescentam respectivamente `.wav`, `.srt` e `.vtt` à lista; com `--formatos wav`, eles não acrescentam MP3.
- `--refazer` ignora o cache válido e sobrescreve todos os segmentos gerados. `--refazer-segmentos 2,5` regera apenas os IDs indicados e preserva os demais do cache.
- `--lufs` aplica normalização EBU R128 (`loudnorm`) no áudio final (`-70` a `-5`, ex.: `-16` para podcasts); `--taxa-amostragem` seleciona a frequência final (`24000`, `44100` ou `48000` Hz).
- `--trilha` *(beta)* mistura uma trilha de fundo em loop com *auto-ducking* (`sidechaincompress`) e ganho base `--volume-trilha` (padrão `-18.0` dB).
- `--limpar-referencia` *(beta)* filtra áudios de referência com `highpass`, `lowpass`, `afftdn` e `loudnorm` antes da clonagem.
- `--max-tentativas` (padrão `2`) limita o total de tentativas diante de anomalias heurísticas de silêncio ou duração. Se persistirem, o pipeline pode salvar um segmento ainda anômalo e emite aviso; não há garantia de correção.
- `--sem-normalizar` desativa a normalização fonética. As tags, personagens, divisão de trechos e pausas continuam ativos.
- A ordem de prioridade de voz por trecho é: referência de tom (`[tom:...]` / `--vozes-tons`), referência de personagem (`--vozes-personagens` / `[arquivo.wav]:`), gravação global em `--voz`, personagem embutido explícito, `--locutor`, voz padrão do idioma.
- Duração recomendada da referência: 6 a 30 segundos. A CLI verifica a existência do arquivo; não valida previamente sua duração nem a qualidade da gravação.

Entradas inválidas detectadas pela CLI encerram com código `2`. Falhas de síntese, disco ou FFmpeg também podem encerrar com erro; o cache já concluído permite uma nova tentativa. Nem todas as falhas de bibliotecas são convertidas em mensagens curtas.

## Validação: `validar_audio.py`

| Argumento/opção | Padrão | Aplicação |
|---|---|---|
| `audio texto` | — | Par de caminhos obrigatório no modo de áudio final. |
| `--idioma` | `auto` | `auto`, `pt` ou `es` no modo de áudio final; em `auto`, considera o texto inteiro. |
| `--modelo` | `openai/whisper-small` | Modelo ASR usado nos dois modos de transcrição. |
| `--limite-wer` | `0.10` | Limite finito e não negativo; `0.15` significa 15%. |
| `--manifesto` | — | Caminho de uma síntese concluída com lista de segmentos. |
| `--relatorio` | Derivado do manifesto | Caminho do relatório JSON; requer `--manifesto`. |
| `--somente-metricas` | Desativado | Requer `--manifesto`; não carrega o Whisper nem calcula WER. |

Não combine `--manifesto` com áudio/texto posicionais ou um idioma forçado. Cada segmento fornece seu próprio idioma.

```bash
python validar_audio.py --manifesto saida/aula.v2.blocos.json --relatorio saida/aula.v2.asr.json
python validar_audio.py --manifesto saida/aula.v2.blocos.json --somente-metricas --relatorio saida/aula.v2.metricas.json
```

Os caminhos distintos preservam os dois relatórios. Sem `--relatorio`, os dois modos escrevem no mesmo destino: `saida/aula.v2.blocos.validacao.json`.

### Códigos de saída

| Código | Significado |
|---|---|
| `0` | Transcrição dentro do limite, ou coleta de métricas concluída. No segundo caso, não significa aprovação da fala. |
| `1` | WER acima do limite. No modo com manifesto, basta um segmento reprovado. |
| `2` | Erro de argumentos ou erro de manifesto tratado pela CLI. |

Erros de dependências, modelo e transcrição podem produzir outras saídas de erro. Um erro operacional não equivale a reprovação por WER.

### Interpretação do WER

O alinhamento usa distância mínima de edição em palavras. A tokenização remove tags, rótulos, acentos e pontuação, converte para minúsculas e expande números conforme o idioma. O WER pode superar 100% quando há muitas inserções.

O WER global é a soma dos erros dividida pela soma das palavras de referência. Não é a média simples dos percentuais por segmento. O mesmo cálculo é feito separadamente para PT e ES. A aprovação é determinada pelo limite **em cada segmento**, não pelo WER global.

Variações ortográficas e erros do Whisper afetam a medida. Na amostra inicial, `veintiún` e o numeral `21`, expandido para `veintiuno`, produziram uma divergência sem evidência suficiente de erro de pronúncia.

## Manifesto: `<saida>.blocos.json`

| Campo | Conteúdo |
|---|---|
| `analise_previa` | Quantidade estimada de palavras, duração, necessidade de divisão, idioma dominante e voz global. |
| `blocos` | Identificador, palavras, texto e `texto_falado` de cada bloco. |
| `estado` | `sintetizando`, `montando`, `interrompido` ou `concluido`. Pode permanecer na etapa interrompida. |
| `configuracao` | Python, versões de bibliotecas, dispositivo solicitado, velocidade, volume, corte, hash da referência e hashes dos módulos principais do pipeline, incluindo os módulos extraídos. |
| `segmentos` | Falas concluídas na execução, incluindo trechos recuperados do cache. |

Cada entrada em `segmentos` contém `id`, `bloco`, `texto`, `idioma`, `locutor`, `arquivo`, `chave`, `inicio_s`, `fim_s`, `duracao_s` e `reutilizado`. `locutor` é `null` quando há referência de voz. As posições usam a linha do tempo do WAV, incluindo 200 ms de silêncio inicial e as pausas anteriores.

`dispositivo_solicitado` registra a opção da CLI, não confirma o dispositivo efetivamente usado em uma geração anterior. Os hashes de fontes ajudam na rastreabilidade; não fazem parte automaticamente da chave do cache. Alterações manuais no processamento exigem atenção à versão do pipeline ou o uso de `--refazer`.

Novos manifestos registram caminhos absolutos para os WAVs. Ao mover o projeto, gere novamente o manifesto no novo local ou atualize os caminhos. O validador também aceita caminhos relativos ao diretório do manifesto.

## Relatório: `*.validacao.json`

| Campo | Conteúdo |
|---|---|
| `manifesto` | Caminho absoluto do manifesto validado. |
| `modelo_asr` | Modelo Whisper, ou `null` em métricas. |
| `limite_wer` | Limite informado. |
| `somente_metricas` | Indica coleta sem transcrição. |
| `wer_global` | WER ponderado, ou `null` em métricas. |
| `por_idioma` | Palavras, erros e WER por idioma; vazio em métricas. |
| `segmentos` | Referência, idioma, tempos, métricas e, quando aplicável, transcrição e divergências. |
| `aprovado` | Todos os segmentos dentro do limite; `null` em métricas. |

Os campos acústicos são `duracao_s`, `rms_dbfs`, `pico_dbfs`, `fracao_amostras_saturadas` e `avisos`. RMS e pico de silêncio digital são `null`, evitando valores infinitos em JSON. Tempos ausentes em manifestos antigos também aparecem como `null`.

## Outras ferramentas e servidor local

```bash
python medir_audio.py saida/aula.v2.wav --min-pausa-ms 250 --limiar-db -45
python comparar_vozes.py --idioma es --saida saida/comparacao_es
python servidor_api.py --porta 8000
```

`medir_audio.py` apresenta a linha do tempo de fala/silêncio no terminal. `comparar_vozes.py` gera uma seleção de amostras em CPU; `--listar` imprime os nomes disponíveis e continua gerando amostras. `servidor_api.py` *(beta)* expõe a rota `POST /v1/audio/speech` compatível com clientes OpenAI TTS, além de `GET /v1/models`, `GET /v1/voices` e `GET /health`.

## API HTTP: campos e limites

O servidor usa a biblioteca padrão do Python e não necessita de um pacote web adicional. Para iniciá-lo:

```bash
python servidor_api.py --host 127.0.0.1 --porta 8000 --pasta-cache saida/api_cache --dispositivo cpu
```

| Campo JSON | Padrão | Comportamento |
|---|---|---|
| `input` | Obrigatório | Texto a sintetizar; não pode estar vazio. |
| `voice` | Automático | Alias local, nome de locutor ou caminho de referência acessível ao servidor. `iapetus` é Xavier Hayasaka. |
| `language` / `idioma` | `auto` | `auto`, `pt` ou `es`; `language` prevalece se informado. |
| `response_format` | `mp3` | Um de `mp3`, `wav`, `srt` ou `vtt`. |
| `speed` | `1.1` | Número finito de 0,25 a 4. A faixa da API é validada antes da CLI. |
| `lufs` | Desativado | Encaminhado para `--lufs`, com a mesma validação da CLI. |
| `limpar_referencia` | Desativado | Valor booleano para ativar o tratamento da referência. |
| `model` | Não seleciona o motor | Aceito no corpo, mas não interpretado para escolher outro modelo. |

Exemplo no PowerShell, após iniciar o servidor na configuração padrão:

```powershell
$corpo = @{ model = 'tts-1'; input = 'Teste local de voz.'; voice = 'iapetus'; language = 'pt'; response_format = 'wav' } | ConvertTo-Json
Invoke-WebRequest -Uri 'http://127.0.0.1:8000/v1/audio/speech' -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($corpo)) -OutFile 'saida/api_exemplo.wav'
```

O servidor limita o corpo da requisição a 2.000.000 bytes. Respostas de sucesso retornam o arquivo completo com código HTTP 200; erros de entrada tratados retornam 400, e erros internos tratados retornam 500. Isso não é streaming, mesmo quando o cliente envia parâmetros que peçam esse comportamento.

`GET /v1/models` lista identificadores de compatibilidade; `tts-1`, `tts-1-hd` e `xtts_v2` não representam três modelos instalados. `GET /v1/voices` mostra nomes e aliases locais, sem prometer equivalência com vozes de outros serviços.

A síntese é protegida por um bloqueio e ocorre uma requisição por vez. O cache é compartilhado, mas o modelo não é mantido em memória entre chamadas. O arquivo de resposta é lido integralmente para memória. Não há autenticação, fila persistente nem mecanismo de isolamento para usuários distintos; mantenha o uso no endereço local padrão. O servidor é uma integração experimental, não uma reprodução completa da API de outro fornecedor.

Na instalação por wheel, o cache padrão da API usa a pasta de dados do usuário, sem escrever junto aos módulos. No checkout permanece em `saida/api_cache`. `TTSBR_HOME` altera a raiz; `--pasta-cache` escolhe diretamente o diretório da API. Entradas `input` não textuais, `speed` nulo/inválido e `limpar_referencia` não booleano são rejeitadas com erro de entrada.
