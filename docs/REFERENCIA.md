# Referência de comandos e arquivos

[README](../README.md) · [Arquitetura](ARQUITETURA.md) · [Avaliação](../avaliacao/GUIA.md)

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

- `--saida` é o nome **base**. `aula.v2` gera `aula.v2.mp3`; `aula.mp3` gera `aula.mp3.mp3` se MP3 estiver selecionado.
- Formatos são convertidos para minúsculas e duplicatas são removidas. Listas com itens vazios, como `mp3,`, são rejeitadas.
- `--wav` acrescenta WAV à lista; com `--formatos wav`, ele não acrescenta MP3.
- `--refazer` ignora o cache válido e sobrescreve os segmentos gerados. Não elimina entradas antigas que deixaram de ser usadas pelo texto.
- `--sem-normalizar` desativa a normalização fonética. As tags, personagens, divisão de trechos e pausas continuam ativos.
- A ordem de voz é: gravação em `--voz`, personagem explícito, `--locutor`, voz padrão do idioma.
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
| `estado` | `sintetizando`, `montando` ou `concluido`. Pode permanecer na etapa interrompida. |
| `configuracao` | Python, versões de bibliotecas, dispositivo solicitado, velocidade, volume, corte, hash da referência e hashes de três arquivos do pipeline. |
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

## Outras ferramentas

```bash
python medir_audio.py saida/aula.v2.wav --min-pausa-ms 250 --limiar-db -45
python comparar_vozes.py --idioma es --saida saida/comparacao_es
```

`medir_audio.py` apresenta a linha do tempo de fala/silêncio no terminal. `comparar_vozes.py` gera uma seleção de amostras em CPU; `--listar` imprime os nomes disponíveis e continua gerando amostras.
