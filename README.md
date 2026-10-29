# TTSBR — Texto para voz em Português (BR) e Espanhol com XTTS v2

Converte arquivos `.txt` em áudio (`.mp3`, opcionalmente `.wav`) usando o modelo **XTTS v2** (Coqui TTS), 100% local. Inclui normalização fonética (números, siglas, termos técnicos em inglês), pausas calibradas pela pontuação, tags de direção de voz e ferramentas para medir e validar o áudio gerado.

## Recursos

- **Idioma automático:** detecta português ou espanhol, por parágrafo, e troca idioma e voz sozinho em textos mistos.
- **Normalização fonética** ([normalizador.py](normalizador.py)):
  - números, porcentagens, decimais e unidades por extenso (PT e ES);
  - siglas e variáveis (`GPU`, `IA`, `API`, `X`, `Y`...);
  - termos técnicos em inglês (`deep learning`, `backpropagation`...);
  - abreviações (`Dr.`, `p. ex.`...).
- **Pausas por pontuação:** ponto, vírgula, `;`, `:`, reticências e parágrafo têm pausas fixas em ms. O silêncio residual do XTTS nas pontas de cada trecho é removido.
- **Tags de direção de voz:** `[pausa:1.5s]`, `[respiro]`, `[enfase]`, `[sussurro]`.
- **Glossário por projeto** para pronúncias próprias.
- **Aceleração automática:** CUDA, MPS (Apple Silicon) ou CPU.
- **Ferramentas de verificação:** transcrição com Whisper (WER) e medição de pausas e volume.

## Instalação

Requer Python 3.10+ e `ffmpeg` (ou o `imageio-ffmpeg` do `requirements.txt`).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Para usar `validar_audio.py` e `medir_audio.py`, instale também as dependências deles:

```bash
pip install transformers librosa soundfile
```

Na primeira execução o modelo XTTS v2 é baixado automaticamente (a licença é aceita via `COQUI_TOS_AGREED=1`, definido no script).

## Uso básico

```bash
# Detecta idioma e voz automaticamente
python tts.py teste1.txt --saida saida/teste1

# Gera também o WAV
python tts.py teste1.txt --saida saida/teste1 --wav

# Força espanhol e escolhe a voz
python tts.py texto.txt --idioma es --locutor "Xavier Hayasaka"
```

Cada execução gera `<saida>.mp3` e `<saida>.blocos.json`, com a divisão em blocos e o texto já normalizado enviado ao modelo.

### Principais opções

| Opção | Padrão | Descrição |
|---|---|---|
| `--idioma` | `auto` | `auto`, `pt` ou `es`. Em `auto` a detecção é por parágrafo. |
| `--locutor` | por idioma | Voz embutida do XTTS. Padrão: `Luis Moray` (PT) e `Alma María` (ES). |
| `--velocidade` | `1.1` | Velocidade da fala (1.0 = original; padrão: 1.1; faixa útil: 0.8 a 1.3). |
| `--voz arquivo.wav` | — | Clona a voz a partir de uma gravação de referência (6 a 30 s). |
| `--dispositivo` | `auto` | `auto`, `cpu`, `cuda` ou `mps`. |
| `--volume-alvo` | `-20.0` | Volume-base em dBFS. A folga permite o efeito de `[enfase]`. |
| `--pausa-frase` | `600` | ms após `.`, `!` e `?`. |
| `--pausa-reticencias` | `850` | ms após reticências. |
| `--pausa-ponto-virgula` | `420` | ms após `;` e `:`. |
| `--pausa-virgula` | `250` | ms em corte forçado de frase longa. |
| `--pausa-paragrafo` | `1150` | ms entre parágrafos. |
| `--pausa-bloco` | `500` | ms extra entre blocos. |
| `--glossario` | — | Arquivo de glossário (veja abaixo). |
| `--sem-normalizar` | — | Desativa a normalização fonética. |
| `--sem-corte-silencio` | — | Não remove o silêncio residual do XTTS. |
| `--formatos` / `--wav` | `mp3` | Formatos de saída. |

Textos acima de 450 palavras são divididos em blocos de até 150 palavras, sempre terminando em fim de frase.

## Tags de direção de voz

Escreva as tags direto no `.txt`:

```text
Ele analisou a arquitetura em silêncio... [pausa:1.5s] e tomou uma decisão firme.

[enfase] Este é o ponto fundamental: [respiro] não podemos abrir mão da segurança.

Ele concluiu: [sussurro] tudo funcionou.
```

| Tag | Efeito |
|---|---|
| `[pausa:1.5s]` / `[pausa:800ms]` | Silêncio exato na posição da tag. Sinônimo: `[silencio]`. Sem parâmetro: 1000 ms. |
| `[respiro]` | Pausa de 400 ms. |
| `[enfase]` | Volume do trecho seguinte **+2,5 dB**. Sinônimo: `[destaque]`. |
| `[sussurro]` | Volume do trecho seguinte **−4 dB**. Sinônimos: `[baixo]`, `[calmo]`. |

**Limitações:** as tags só alteram pausas e volume. O XTTS não muda o timbre nem a emoção da voz com elas. `[enfase]` e `[sussurro]` valem para o trecho de texto imediatamente seguinte, dentro da mesma frase. Se você usar `--volume-alvo` acima de cerca de `-19`, o teto de pico (−1 dBFS) limita o efeito de `[enfase]`.

## Roteiro com Múltiplos Locutores (Diálogos)

Você pode alternar personagens no mesmo arquivo definindo o nome do locutor no início do parágrafo:

```text
[Narrador]: No laboratório de inteligência artificial, a equipe comemora os novos resultados.

[Luis]: Conseguimos reduzir o tempo de convergência e a perda do modelo.

[Alma]: Excelente noticia. Ahora podemos iniciar las pruebas de validación con los datos de producción.
```

- **Mapeamento automático:** apelidos comuns (`Narrador`, `Luis`, `Alma`, `Marcos`, `Gilberto`, `Ana`, `Sofia`, `Xavier`, etc.) são convertidos para o nome oficial do modelo no XTTS v2.
- **Forçar idioma com o locutor:** você pode combinar personagem e idioma usando pipe, ex: `[Alma|es]: ...` ou simplesmente indicar o idioma `[es]: ...`.
- O rótulo `[Personagem]:` é usado apenas para a direção de cena e é removido da fala enviada ao modelo.

## Glossário

Os glossários são carregados e mesclados nesta ordem, em que o último vence:

1. `glossario.json` ou `glossario.txt` na pasta do projeto;
2. `<nome-do-texto>.glossario.json` ou `.glossario.txt`, ao lado do texto;
3. o arquivo passado em `--glossario`.

Formato texto (`#` inicia comentário):

```text
PostgreSQL = pós-gre-ésse-quê-éle
Kubernetes = cubernetes
```

Formato JSON, com seção opcional por idioma:

```json
{ "Kubernetes": "cubernetes", "es": { "AWS": "a-dobleve-ese" } }
```

Veja [glossario.txt.exemplo](glossario.txt.exemplo).

## Verificação do áudio

**Validar a fala com Whisper** (compara a transcrição com o texto original):

```bash
python validar_audio.py saida/teste1.mp3 teste1.txt
python validar_audio.py saida/teste_es.mp3 teste_es.txt --idioma es
```

Mostra o WER, as palavras trocadas, omitidas ou inseridas, e avisa se "ponto" ou "punto" foi falado. Sai com código 1 se o WER passar do limite (`--limite-wer`, padrão 10%). As tags `[...]` são ignoradas na comparação. Usa `openai/whisper-small`, e os erros do próprio Whisper também entram no WER.

**Medir pausas e volume:**

```bash
python medir_audio.py saida/teste_expressividade.wav
```

Lista cada trecho de fala (duração e dBFS) e cada pausa (ms). Serve para conferir o efeito das tags e da calibração de pausas.

**Comparar vozes:**

```bash
python comparar_vozes.py --idioma es   # gera saida/vozes_es/*.wav
python comparar_vozes.py --idioma pt   # gera saida/vozes/*.wav
python comparar_vozes.py --listar      # lista as vozes do XTTS v2
```

## Testes

```bash
python -m unittest discover -s tests -v
```

Cobrem detecção de idioma, números, siglas, termos, abreviações, glossário, tags, pausas, corte de silêncio e divisão de frases. **Os testes não geram áudio**; para isso use `validar_audio.py` e `medir_audio.py`.

## Observações

- **Vozes padrão:** `Luis Moray` e `Alma María` foram escolhidas durante o desenvolvimento, mas a qualidade e o sotaque de uma voz são subjetivos. Ouça as amostras de `comparar_vozes.py` e troque com `--locutor` se preferir outra.
- **Desempenho:** em um teste isolado no Apple Silicon, a inferência de uma frase levou 3,9 s no MPS contra 5,1 s na CPU. O ganho pode variar por máquina e por texto.
- **Pontuação final:** `limpar_para_voz` remove o `.` final de cada trecho antes de enviar ao XTTS, porque o modelo chega a ler a palavra "ponto". A pausa continua sendo aplicada pela pontuação original.
- **Limite do XTTS:** frases acima de cerca de 200 caracteres são cortadas pelo script, de preferência em vírgulas.
- **Ambientes restritos:** ao rodar em sandbox, o virtualenv precisa estar acessível, inclusive o arquivo `pyvenv.cfg`. Caso contrário o Python falha ao iniciar.

## Estrutura

```text
tts.py              # pipeline principal (CLI)
normalizador.py     # detecção de idioma e normalização fonética PT/ES
validar_audio.py    # transcrição Whisper + WER
medir_audio.py      # pausas e volume por trecho
comparar_vozes.py   # amostras das vozes embutidas
glossario.txt.exemplo
tests/              # testes de unidade
saida/              # áudios gerados
teste*.txt          # textos de exemplo
```
