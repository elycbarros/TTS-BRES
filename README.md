<div align="center">

<img src="docs/assets/ttsbr-banner.svg" alt="TTSBR — Texto ganha voz. Síntese local em PT-BR e espanhol com XTTS v2." width="100%">

# TTSBR

**Texto para voz em português brasileiro e espanhol.**

`XTTS v2` · `Python` · `Síntese local` · `MP3 / WAV`

[Interface gráfica](#gui) · [Começar](#instalacao) · [Exemplos](#primeiros-passos) · [Vozes](#idiomas) · [Glossários](#glossarios) · [Retomada](#retomada) · [Referência CLI](#opcoes)

</div>

Converta arquivos `.txt` em MP3 ou WAV com normalização de números, siglas e termos técnicos, controle de pausas e alternância de locutores. A síntese é executada localmente; o primeiro uso requer acesso à internet para baixar o modelo.

> **Do texto ao áudio**
> Arquivo `.txt` → validação e pronúncia → síntese ou cache → montagem em disco → MP3 / WAV

### Documentação

| Para… | Consulte |
|---|---|
| Entender os recursos, usos e limitações | [Sobre o TTSBR](docs/SOBRE.md) |
| Usar a janela local no macOS ou Windows | [Guia da GUI](docs/GUI.md) |
| Instalar e gerar o primeiro áudio | [Primeiros passos](#primeiros-passos) |
| Consultar argumentos, códigos de saída e campos JSON | [Referência de comandos e arquivos](docs/REFERENCIA.md) |
| Entender persistência, montagem e recuperação | [Arquitetura do pipeline](docs/ARQUITETURA.md) |
| Comparar versões e avaliar amostras PT/ES | [Guia de avaliação](avaliacao/GUIA.md) |
| Entender as licenças do código e do modelo | [Licença](#licenca) e [componentes de terceiros](THIRD_PARTY_NOTICES.md) |
| Consultar as três entregas | [Histórico de alterações](CHANGELOG.md) |

<details>
<summary><strong>Explorar a documentação</strong></summary>

- [Recursos](#recursos)
- [Instalação](#instalacao)
- [Interface gráfica](#gui)
- [Primeiros passos](#primeiros-passos)
- [Retomada e cache](#retomada)
- [Idiomas e vozes](#idiomas)
- [Normalização de números](#normalizacao)
- [Pausas e direção de voz](#pausas)
- [Glossários de pronúncia](#glossarios)
- [Opções de síntese](#opcoes)
- [Conferir o resultado](#conferencia)
- [Testes](#testes)
- [Limitações e solução de problemas](#problemas)
- [Arquivos locais e privacidade](#arquivos-locais)
- [Licença e componentes de terceiros](#licenca)
- [Estrutura do projeto](#estrutura)

</details>

---

<a id="recursos"></a>

## ✨ Recursos

| Texto e pronúncia | Voz e áudio | Conferência |
|:---|:---|:---|
| Detecção de PT-BR e espanhol | Múltiplos locutores no roteiro | Transcrição com Whisper |
| Números, siglas e unidades por extenso | Tags de pausa e volume | WER por distância de edição |
| Glossários por arquivo e idioma | Exportação MP3 e WAV | Medição de pausas e volume |
| Pronúncia de termos técnicos | CUDA, MPS ou CPU | Comparação de vozes |
| Datas, horários, moedas e negativos | Cache e retomada automática | Relatórios JSON por idioma e trecho |

---

<a id="instalacao"></a>

## 🚀 Instalação

Execute os comandos a partir da pasta do projeto. Use uma versão de Python compatível com as dependências do `requirements.txt`; a sintaxe do projeto requer Python 3.10 ou superior.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

No Windows, ative o ambiente com `.venv\Scripts\activate`.

A avaliação inicial foi executada com Python 3.12; as dependências atuais não estão fixadas por versão. Essa medição não garante compatibilidade com todas as versões de Python. O ambiente registrado pode ser consultado em [resultado_inicial.json](avaliacao/resultado_inicial.json).

A exportação MP3 usa o `ffmpeg` do sistema. Quando ele não está disponível, o pipeline tenta usar o executável fornecido por `imageio-ffmpeg`, incluído nas dependências.

Para usar as ferramentas auxiliares de validação, medição e comparação de vozes:

```bash
python -m pip install transformers librosa soundfile
```

> **Primeira execução**
> O XTTS v2 é baixado automaticamente. Os scripts de síntese definem `COQUI_TOS_AGREED=1`, sinalizando aceite dos termos do modelo. Consulte esses termos antes de usar o modelo.

<a id="gui"></a>

## 🖥️ Interface gráfica local

A primeira GUI oferece editor, configurações, conferência do texto normalizado, amostra de voz, progresso, retomada e revisão de segmentos. A reprodução abre o player padrão do sistema.

```bash
python3 gui.py
```

No Windows, use `py -3 gui.py`. Há também os iniciadores `abrir_gui.command` e `abrir_gui.bat`. A janela precisa de Python com Tkinter; o Python do ambiente de síntese pode ser selecionado em **Ajustes avançados**. Preferências e snapshots ficam em `local/gui/`, fora do Git.

Esta é uma versão inicial para uso pessoal, sem instalador. A integração com o pipeline é testada automaticamente; a janela precisa de validação no desktop do usuário, incluindo Windows. Consulte [requisitos, uso e limitações da GUI](docs/GUI.md).

<a id="primeiros-passos"></a>

## ▶️ Primeiros passos

Gere um áudio a partir de um dos textos de exemplo:

```bash
python tts.py exemplos/narracao_pt.txt --saida saida/narracao_pt
```

Esse comando detecta o idioma por parágrafo e grava:

| Arquivo | Conteúdo |
|---|---|
| `saida/narracao_pt.mp3` | Áudio final. |
| `saida/narracao_pt.segmentos/` | Cache persistente de WAVs e metadados para retomada. |
| `saida/narracao_pt.blocos.json` | Estimativa de duração, divisão em blocos, texto de cada bloco e `texto_falado` após normalização, remoção de tags e limpeza para síntese. |

A pasta de saída é criada automaticamente. Arquivos com o mesmo nome podem ser sobrescritos. Pontos no nome base são preservados: `--saida saida/aula.v2` gera `aula.v2.mp3` e `aula.v2.blocos.json`.

```bash
# MP3 e WAV na mesma execução
python tts.py exemplos/narracao_pt.txt --saida saida/narracao_pt --wav

# Apenas WAV
python tts.py exemplos/narracao_pt.txt --saida saida/narracao_pt --formatos wav

# Espanhol com voz específica
python tts.py exemplos/narracao_es.txt --idioma es --locutor "Xavier Hayasaka" --saida saida/narracao_es

# Voz de referência para clonagem
python tts.py exemplos/narracao_pt.txt --voz referencia.wav --saida saida/voz_referencia

# Execução em CPU
python tts.py exemplos/narracao_pt.txt --dispositivo cpu --saida saida/teste_cpu
```

Use arquivos de texto em UTF-8. Separe os parágrafos com uma linha em branco. Para consultar a ajuda completa:

```bash
python tts.py --help
```

<a id="retomada"></a>

## 💾 Retomada e cache

Cada trecho de fala é salvo em `<saida>.segmentos/` assim que sua síntese termina. Se a execução for interrompida, repita o comando com o mesmo caminho de saída:

```bash
python tts.py exemplos/narracao_pt.txt --saida saida/narracao_pt --wav

# Após uma interrupção, execute novamente o mesmo comando
python tts.py exemplos/narracao_pt.txt --saida saida/narracao_pt --wav

# Para gerar novas versões de todos os trechos
python tts.py exemplos/narracao_pt.txt --saida saida/narracao_pt --wav --refazer
```

A retomada é automática. Cada segmento tem uma chave calculada a partir do texto enviado à síntese, idioma, voz ou conteúdo da referência, velocidade, volume, corte de silêncio, dispositivo solicitado, versão do pipeline e versões das dependências. Antes de reutilizar o WAV, o programa verifica seu formato e hash SHA-256. Segmentos ausentes, incompletos ou corrompidos são gerados novamente.

- **Mudança de pausas ou formato de saída:** reutiliza a fala e refaz a montagem.
- **Mudança de texto, voz ou parâmetros de síntese:** gera os segmentos que não têm uma correspondência válida no cache.
- **Cache completo:** monta e exporta sem carregar o XTTS.
- **Modelo substituído manualmente:** use `--refazer`; a chave inclui o nome do modelo e versões das bibliotecas, mas não o hash dos pesos do XTTS.

O manifesto `.blocos.json` registra os segmentos já processados, sua duração, localização no cache, tempos na montagem e se foram reutilizados. Também registra versões de bibliotecas e hashes das fontes para rastreabilidade; esses hashes não invalidam o cache automaticamente. O campo `estado` indica `sintetizando`, `montando`, `interrompido` ou `concluido`; após uma interrupção, ele pode permanecer na etapa em andamento. A retomada verifica os arquivos do cache, sem depender de o manifesto estar completo.

Os caminhos de segmentos nos novos manifestos são absolutos. Se mover o projeto, execute novamente a síntese no novo local para atualizar o manifesto. Consulte os [detalhes de recuperação e armazenamento](docs/ARQUITETURA.md).

### Montagem com memória limitada

O áudio final é montado em um WAV temporário, copiando segmentos e escrevendo silêncios em blocos pequenos. Para MP3, o FFmpeg converte esse arquivo em disco. Cada saída só substitui o arquivo anterior após sua exportação terminar; uma falha mantém os segmentos para a próxima tentativa.

A montagem não acumula todo o áudio na memória. O modelo XTTS e o segmento em geração ainda consomem memória. Reserve espaço em disco para o cache, o WAV temporário e as saídas. A montagem usa WAV RIFF convencional, com limite aproximado de 4 GB.

O cache permanece após a conclusão. Para liberar espaço, remova a pasta `<saida>.segmentos/` quando não precisar mais da retomada nem da validação por manifesto; isso não remove os áudios finais. Use caminhos de saída diferentes para execuções simultâneas.

<a id="idiomas"></a>

## 🗣️ Idiomas e vozes

Em `--idioma auto`, cada parágrafo recebe uma detecção independente. As vozes padrão são:

| Idioma | Código | Locutor |
|---|---|---|
| Português brasileiro | `pt` | `Luis Moray` |
| Espanhol | `es` | `Alma María` |

A detecção usa regras e vocabulário. Para textos curtos ou ambíguos, informe `--idioma pt` ou `--idioma es`, ou use um rótulo de idioma no parágrafo.

`--locutor` define a voz dos trechos sem personagem explícito. `--voz` usa uma gravação de referência para todos os trechos e tem prioridade sobre as vozes embutidas; a orientação de uso é uma referência de 6 a 30 segundos.

### Diálogos com múltiplos locutores

Coloque o personagem no início de cada parágrafo:

```text
[Narrador]: No laboratório, a equipe compara os resultados.

[Luis|pt]: Conseguimos reduzir o erro para menos de 1%.

[Alma|es]: Excelente noticia. Ahora podemos iniciar las pruebas.
```

Os rótulos são removidos antes da síntese. Apelidos como `Narrador`, `Luis`, `Alma`, `Marcos`, `Gilberto`, `Ana`, `Sofia` e `Xavier` são convertidos para nomes de vozes embutidas. Também é possível informar o nome completo de um locutor.

- `[Alma|es]:` escolhe a personagem e força espanhol naquele parágrafo.
- `[es]:` força espanhol e usa a voz selecionada pelas opções do comando ou pelo idioma.
- `[Alma]:` escolhe a voz; o idioma continua sujeito à detecção ou à opção `--idioma`.

<a id="normalizacao"></a>

## 🔢 Normalização de números

A normalização PT/ES reconhece números, porcentagens, unidades e os formatos contextuais abaixo:

| Entrada | Leitura em português |
|---|---|
| `29/10/2026` ou `29-10-2026` | vinte e nove de outubro de dois mil e vinte e seis |
| `10:30` | dez horas e trinta minutos |
| `02:01:05` | duas horas e um minuto e cinco segundos |
| `R$ 12,50` | doze reais brasileiros e cinquenta centavos |
| `EUR 21,50` | vinte e um euros e cinquenta centavos |
| `-5` e `-0,5%` | menos cinco e menos zero vírgula cinco por cento |

As mesmas regras produzem palavras em espanhol quando o idioma do trecho é `es`. Datas usam **dia/mês/ano com quatro dígitos no ano**; datas impossíveis são rejeitadas. Horários usam **24 horas**, com minutos e segundos de dois dígitos; valores fora de faixa são rejeitados.

Valores monetários usam vírgula decimal e ponto para milhares, como `R$ 1.234,50`. São aceitos os prefixos `R$`, `BRL`, `US$`, `USD`, `$`, `EUR` e `€`; `$` é interpretado como dólar americano. Valores inteiros podem ser usados sem centavos. Os formatos monetários com ponto decimal ou símbolo após o valor não têm tratamento específico.

O sinal de negativo é reconhecido antes do número, separado da palavra anterior, como `temperatura -5`. Hífens entre números, como `5-10`, não são interpretados como sinal negativo. Expressões com aparência de data ou horário são tratadas como tal; para proporções, referências de capítulos ou formatos ambíguos, escreva a leitura desejada ou use `--sem-normalizar`.

<a id="pausas"></a>

## 🎛️ Pausas e direção de voz

Insira as tags diretamente no texto:

```text
Ele analisou os resultados [pausa:1.5s] e tomou uma decisão.

[enfase] Este é o ponto fundamental: [respiro] precisamos conferir os dados.

Ele concluiu: [sussurro] tudo funcionou.
```

| Tag | Efeito | Sinônimos |
|---|---|---|
| `[pausa:1.5s]` ou `[pausa:800ms]` | Insere silêncio na posição da tag. Sem parâmetro, usa 1000 ms. | `[silencio:1.5s]` |
| `[respiro]` | Insere uma pausa de 400 ms; não gera som de respiração. | `[respiracao]` |
| `[enfase]` | Eleva o volume alvo do próximo trecho em 2,5 dB. | `[destaque]` |
| `[sussurro]` | Reduz o volume alvo do próximo trecho em 4 dB. | `[baixo]`, `[calmo]` |

**Validação das tags:** elas são interpretadas antes da divisão dos trechos, inclusive quando usam espaços como `[pausa: 1500ms]`. Tags desconhecidas, colchetes incompletos e durações inválidas interrompem a execução com uma mensagem de erro antes do carregamento do modelo. Use durações não negativas; `[pausa:0s]` é aceito.

As tags de volume afetam o próximo segmento dentro do trecho dividido para síntese. Elas alteram o volume, sem controlar timbre ou emoção. O ganho aplicado também depende do teto de pico e dos limites de normalização.

As pausas das tags podem se somar às pausas de pontuação e de parágrafo. Por exemplo, `Fim. [pausa:1s]` inclui a pausa correspondente ao ponto, além do silêncio solicitado. Para uma pausa explícita entre palavras, use `antes [pausa:1s] depois`.

<a id="glossarios"></a>

## 📖 Glossários de pronúncia

Use um glossário para ajustar nomes, termos técnicos e siglas. As entradas personalizadas têm prioridade sobre as pronúncias embutidas.

### Formato texto

Crie um arquivo como `meu_glossario.txt`:

```text
# Comentários começam com #
PostgreSQL = pós-gre-ésse-quê-éle
Kubernetes = cubernetes
GPU = placa gráfica
```

```bash
python tts.py exemplos/narracao_pt.txt --glossario meu_glossario.txt --saida saida/narracao_pt
```

Veja também [glossario.txt.exemplo](glossario.txt.exemplo).

### Formato JSON e idiomas

```json
{
  "Kubernetes": "cubernetes",
  "GPU": "placa gráfica",
  "pt": {
    "AWS": "á-dáblio-ésse"
  },
  "es": {
    "AWS": "a-dobleve-ese"
  }
}
```

As entradas gerais são combinadas com a seção do idioma. Quando o mesmo termo aparece nas duas, a seção do idioma prevalece. A pronúncia substituída não passa novamente pela substituição de termos técnicos.

### Ordem de carregamento

Os arquivos são mesclados nesta ordem; para a mesma chave, o último valor vence:

1. `glossario.json` e depois `glossario.txt` no **diretório de trabalho atual**.
2. `<nome-do-texto>.glossario.json` e depois `<nome-do-texto>.glossario.txt`, ao lado do arquivo de entrada.
3. O arquivo indicado em `--glossario`.

As seções por idioma também são mescladas, preservando entradas que não foram sobrescritas. Por exemplo, para `roteiro.txt`, o glossário associado pode se chamar `roteiro.glossario.json`.

<a id="opcoes"></a>

## ⚙️ Opções de síntese

<details>
<summary><strong>Ver parâmetros, valores padrão e ajustes de pausa</strong></summary>

| Opção | Padrão | Uso |
|---|---|---|
| `--saida` | `audio` | Caminho base dos arquivos, sem extensão. |
| `--idioma` | `auto` | `auto`, `pt` ou `es`. |
| `--locutor` | Por idioma | Nome de uma voz embutida. |
| `--voz` | — | Caminho do áudio de referência para clonagem. |
| `--velocidade` | `1.1` | Velocidade de fala; `1.0` corresponde à velocidade original. |
| `--dispositivo` | `auto` | `auto`, `cpu`, `cuda` ou `mps`. |
| `--volume-alvo` | `-20.0` | Volume alvo em dBFS, sujeito aos limites de ganho e pico. |
| `--glossario` | — | Glossário adicional em TXT ou JSON. |
| `--formatos` | `mp3` | Formatos aceitos: `mp3`, `wav` ou `mp3,wav`. |
| `--analisar` | Desativado | Mostra o plano normalizado sem inferência nem saídas finais. |
| `--refazer` | Desativado | Regenera segmentos mesmo quando existe cache válido. |
| `--wav` | Desativado | Acrescenta WAV aos formatos escolhidos. |
| `--sem-normalizar` | Desativado | Desativa a normalização fonética; as tags continuam sendo interpretadas. |
| `--sem-corte-silencio` | Desativado | Preserva o silêncio residual nas bordas dos trechos. |

**Validação antes da síntese:** texto vazio ou sem fala, arquivos de entrada ou referência inexistentes, formatos inválidos e idiomas de parágrafo diferentes de `pt`/`es` são rejeitados. A velocidade deve ser finita e maior que zero; o volume alvo deve ser finito e menor ou igual a zero dBFS; as pausas devem ser inteiros não negativos.

Para conferir o plano sem carregar o XTTS nem gravar saídas, use `python tts.py exemplos/narracao_pt.txt --analisar`.

### Ajustes de pausa

Todos os valores abaixo são informados em milissegundos:

| Opção | Padrão | Aplicação |
|---|---|---|
| `--pausa-frase` | `600` | Após `.`, `!` ou `?`. |
| `--pausa-reticencias` | `850` | Após `...` ou `…`. |
| `--pausa-ponto-virgula` | `420` | Após `;` ou `:`. |
| `--pausa-virgula` | `250` | Cortes intermediários, inclusive de frases longas. |
| `--pausa-paragrafo` | `1150` | Ao final do parágrafo; prevalece sobre a pausa da pontuação. |
| `--pausa-bloco` | `500` | Silêncio adicional entre blocos. |

Vírgulas dentro de um trecho não recebem necessariamente um silêncio inserido pelo script: o modelo interpreta a pontuação interna. O ajuste de vírgula é aplicado quando há divisão em segmentos.

</details>

<a id="conferencia"></a>

## 🎧 Conferir o resultado

Para comparar os modos de validação, argumentos, códigos de saída e campos dos relatórios, consulte a [referência completa](docs/REFERENCIA.md).

### Validar a fala com Whisper

```bash
python validar_audio.py saida/narracao_pt.mp3 exemplos/narracao_pt.txt
python validar_audio.py saida/narracao_es.mp3 exemplos/narracao_es.txt --idioma es

# Aceitar até 15% de erro de palavras
python validar_audio.py saida/narracao_pt.mp3 exemplos/narracao_pt.txt --limite-wer 0.15
```

A ferramenta transcreve o áudio com `openai/whisper-small` e compara a transcrição com o texto de referência. O primeiro uso pode baixar o modelo Whisper. É possível escolher outro modelo com `--modelo`.

O **WER** é calculado por distância mínima de edição:

```text
WER = (substituições + omissões + inserções) / palavras da referência
```

A comparação ignora acentos, pontuação, rótulos de personagem e tags, e expande números conforme o idioma escolhido. Exibe as divergências e alerta para inserções ou substituições contendo `ponto` ou `punto`.

- Código de saída `0`: WER dentro do limite, cujo padrão é `0.10` (10%).
- Código de saída `1`: WER acima do limite.

**Interpretação:** erros do próprio Whisper entram na medida. A validação com áudio e texto posicionais não aplica o glossário fonético completo usado na síntese e trabalha com um único idioma por execução; termos personalizados e roteiros mistos podem gerar divergências mesmo quando a fala está correta. Ouça os trechos sinalizados antes de concluir que houve falha de síntese.

### Validar trechos bilíngues e localizar problemas

Use o manifesto de uma síntese concluída:

```bash
python validar_audio.py --manifesto saida/narracao_pt.blocos.json

# Coletar métricas acústicas sem carregar Whisper
python validar_audio.py --manifesto saida/narracao_pt.blocos.json --somente-metricas

# Escolher o relatório e o limite de WER por trecho
python validar_audio.py --manifesto saida/narracao_pt.blocos.json --relatorio saida/revisao.json --limite-wer 0.15
```

Cada WAV do cache é transcrito no idioma registrado no manifesto. O relatório JSON inclui transcrição, divergências, WER por segmento e por idioma, WER global ponderado, duração, RMS, pico e fração de amostras próximas da saturação. O Whisper é carregado uma vez e reutilizado entre os trechos.

`inicio_s` e `fim_s` localizam cada fala na montagem WAV, incluindo pausas anteriores. Esses campos são registrados nas novas execuções; repetir uma execução antiga atualiza o manifesto usando o cache. A validação por manifesto lê os segmentos salvos, sem verificar a codificação do áudio final.

O relatório padrão é `<nome-do-manifesto-sem-.json>.validacao.json`. Na validação com transcrição, a aprovação exige que **todos os segmentos** respeitem o limite; o código de saída é `1` se qualquer trecho ultrapassá-lo. `--somente-metricas` não atribui aprovação da fala e retorna `0` após coletar as métricas com sucesso.

Para esse modo, use `--manifesto` sem os argumentos posicionais e sem `--idioma`, pois o idioma pertence a cada trecho. A referência é o texto efetivamente enviado à síntese: grafias fonéticas de glossários podem aumentar o WER quando o ASR escolhe a grafia convencional.

### Avaliar a qualidade com amostras reais

O [corpus bilíngue](avaliacao/corpus_pt_es.txt) exercita datas, horários, dinheiro, negativos, ênfase e pausas. O [guia de avaliação](avaliacao/GUIA.md) descreve a geração, as medições e uma ficha de audição para comparar versões. O [resultado inicial](avaliacao/resultado_inicial.json) registra a medição com XTTS e Whisper reais: oito segmentos, WER global de aproximadamente 1,2%, sem avisos acústicos. Esse resultado é específico da amostra e do ambiente registrados.

```bash
python tts.py avaliacao/corpus_pt_es.txt --saida saida/avaliacao_pt_es --formatos wav --dispositivo cpu
python validar_audio.py --manifesto saida/avaliacao_pt_es.blocos.json
```

WER e métricas acústicas ajudam a localizar problemas; naturalidade, sotaque e continuidade precisam de avaliação por audição. O relatório não atribui notas subjetivas automaticamente.

### Medir pausas e volume

```bash
python tts.py exemplos/expressividade.txt --saida saida/expressividade --wav
python medir_audio.py saida/expressividade.wav

# Ajustar a detecção de silêncio
python medir_audio.py saida/expressividade.wav --min-pausa-ms 250 --limiar-db -45
```

A medição lista início, duração e volume RMS dos trechos de fala, além da duração das pausas detectadas. Os resultados dependem do limiar e da duração mínima escolhidos.

### Comparar vozes

```bash
python comparar_vozes.py --idioma pt  # amostras em saida/vozes/
python comparar_vozes.py --idioma es  # amostras em saida/vozes_es/
python comparar_vozes.py --listar
```

O script de comparação usa CPU. A opção `--listar` imprime as vozes disponíveis **e continua gerando as amostras** da seleção definida no script.

<a id="testes"></a>

## 🧪 Testes

Na pasta do projeto, com o ambiente virtual ativado:

```bash
python -m unittest discover -s tests -v
```

A suíte cobre detecção de idioma, números PT/ES, siglas, termos técnicos, abreviações, precedência e mescla de glossários, tags, pausas, corte de silêncio, divisão de frases, validação antecipada da CLI, nomes de saída com pontos e cálculo do WER.

Os testes de integração verificam manifesto, retomada após interrupção, integridade e invalidação do cache, preservação das saídas em falhas e montagem com memória limitada. Exportam WAV e MP3 temporários com sinal simulado; a exportação MP3 usa FFmpeg real, disponível no sistema ou pelo `imageio-ffmpeg`. A suíte também verifica números contextuais, tempos dos segmentos, seleção de idioma na validação e relatórios JSON. **Os testes não carregam o XTTS nem o Whisper e não avaliam a qualidade da voz real.**

<a id="problemas"></a>

## 🔧 Limitações e solução de problemas

| Situação | Orientação |
|---|---|
| `ModuleNotFoundError` | Ative o ambiente virtual e instale as dependências com o mesmo `python` usado para executar o script. |
| Falha na exportação MP3 | Confira a instalação de `ffmpeg` ou `imageio-ffmpeg`; use `--formatos wav` para verificar a exportação WAV. |
| Idioma detectado incorretamente | Use `--idioma pt`, `--idioma es` ou um rótulo como `[Alma\|es]:`. |
| Falha ou desempenho inadequado na GPU | Execute com `--dispositivo cpu` e compare o resultado. O desempenho depende do equipamento e do texto. |
| Ambiente virtual inacessível em sandbox | Verifique o acesso ao executável Python, às dependências e ao arquivo `pyvenv.cfg`. |
| WER alto com termos técnicos | Confira a transcrição e as pronúncias personalizadas; o WER não mede naturalidade nem timbre. |
| Cache do Numba/Librosa sem permissão de escrita | Crie uma pasta gravável e defina `NUMBA_CACHE_DIR`; veja o [guia](avaliacao/GUIA.md). |
| Segmento ausente na validação por manifesto | Preserve o cache; se ele foi removido ou movido, repita a síntese para gerar os arquivos e atualizar os caminhos. |
| Manifesto com estado incompleto | Repita o comando de síntese. O programa verifica o cache e retoma o trabalho. |
| WER global baixo, mas resultado reprovado | Confira cada trecho: o limite de aprovação é aplicado individualmente. |
| Áudio acima do limite WAV RIFF | Divida o texto em saídas menores; a montagem intermediária usa WAV mesmo para exportar apenas MP3. |

Textos com mais de 450 palavras são agrupados em blocos com alvo de até 150 palavras, preservando frases completas. Uma frase isolada pode ultrapassar esse alvo; antes da síntese, os trechos normalizados são divididos para respeitar o limite de 200 caracteres adotado pelo script, preferindo cortes em vírgulas.

O pipeline remove pontos e outras marcas finais de cada segmento para reduzir a leitura literal da pontuação. As pausas são calculadas antes dessa limpeza. A escolha de voz e a qualidade do sotaque devem ser avaliadas por audição.

<a id="arquivos-locais"></a>

## 🗂️ Arquivos locais e privacidade

Os roteiros públicos estão em `exemplos/`. Para seus próprios textos, glossários, referências de voz e relatórios, use `local/`, `entradas/`, `referencias/` ou `privado/`, diretórios ignorados pelo Git.

```bash
mkdir -p local
# Salve seu roteiro como local/roteiro.txt antes de executar:
python tts.py local/roteiro.txt --saida saida/roteiro --wav
```

O `.gitignore` também cobre saídas de áudio, caches, modelos, arquivos `.env`, chaves em formatos comuns e preferências de editores. Glossários locais da raiz e os associados a textos (`*.glossario.txt` / `*.glossario.json`) ficam fora do versionamento. O modelo público `glossario.txt.exemplo` permanece disponível.

**O Git não usa o `.gitignore` como detector de dados pessoais.** Arquivos já rastreados precisam ser retirados do índice, e dados publicados em commits anteriores continuam no histórico. Antes de publicar, confira `git status` e `git diff --cached`. Não use `git add -f` em arquivos privados.

Manifestos e relatórios podem conter o roteiro, transcrições, nomes de vozes e caminhos absolutos da máquina. Mantenha-os nas pastas ignoradas. O resultado agregado de referência em `avaliacao/resultado_inicial.json` é um artefato público revisado, sem caminhos locais, credenciais ou gravações pessoais.

<a id="licenca"></a>

## 📄 Licença e componentes de terceiros

O código e a documentação originais do TTSBR são disponibilizados sob a [licença MIT](LICENSE), com copyright de 2026 de Ely do Carmo Barros. A MIT permite reutilização, modificação e distribuição, inclusive comercial, do código original, preservados os avisos exigidos.

**O XTTS v2 e os áudios gerados por ele seguem a [Coqui Public Model License](https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt), que restringe o uso a finalidades não comerciais conforme seus termos.** A licença MIT deste repositório não amplia essas permissões nem relicencia o modelo ou suas saídas.

Dependências, modelos e conteúdos de terceiros permanecem sujeitos às respectivas licenças. Consulte os [avisos de terceiros](THIRD_PARTY_NOTICES.md), incluindo a orientação de acompanhar áudios compartilhados com a referência à licença aplicável. Os scripts definem `COQUI_TOS_AGREED=1`; isso não substitui a leitura dos termos nem concede direitos adicionais.

<a id="estrutura"></a>

## 📁 Estrutura do projeto

<details>
<summary><strong>Ver arquivos e responsabilidades</strong></summary>

```text
TTSBR/
├── gui.py                   # janela local com Tkinter/ttk
├── gui_core.py              # snapshots e comunicação com subprocessos
├── gui_worker.py            # processo de análise, síntese e validação
├── abrir_gui.command        # iniciador macOS
├── abrir_gui.bat            # iniciador Windows
├── tts.py                   # CLI, síntese e exportação
├── audio_persistente.py     # cache verificável e montagem em disco
├── normalizador.py          # idioma, números e pronúncias PT/ES
├── validar_audio.py         # transcrição Whisper e WER por idioma/trecho
├── qualidade_audio.py       # métricas acústicas dos segmentos
├── avaliacao/               # corpus PT/ES e protocolo de audição
├── medir_audio.py           # pausas e volume RMS
├── comparar_vozes.py        # amostras de vozes embutidas
├── docs/                    # referência, arquitetura e banner
├── LICENSE                  # MIT para código e documentação originais
├── THIRD_PARTY_NOTICES.md    # condições do modelo e de terceiros
├── CHANGELOG.md             # histórico das três entregas
├── requirements.txt         # dependências da síntese
├── glossario.txt.exemplo    # modelo de glossário
├── exemplos/                # roteiros públicos e neutros
├── tests/                   # testes de unidade e integração simulada
└── saida/                   # saídas dos exemplos; ignorada pelo Git
```

</details>

---

<div align="center">

[Voltar ao início](#ttsbr)

</div>
