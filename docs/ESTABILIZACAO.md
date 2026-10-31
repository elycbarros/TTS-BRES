# Estabilização — 31/10/2026

[README](../README.md) · [Instalação e GUI](GUI.md) · [Arquitetura](ARQUITETURA.md)

Esta etapa produz um candidato local de estabilização. Não declara a GUI ou o Windows aprovados. A versão de pacote permanece `1.0.0`, já existente no projeto; não foi criada uma release nem uma tag.

## O que foi executado

| Verificação | Resultado |
|---|---|
| Suíte após as correções | 86 testes aprovados no checkout e na instalação por wheel. |
| Suíte original | 78 testes aprovados antes das alterações. |
| Construção original | Falhou por descoberta automática de múltiplos diretórios locais como pacotes. |
| Distribuição corrigida | Wheel e sdist construídos com lista explícita de módulos e recursos públicos. |
| Instalação isolada | Ambiente novo macOS, Python 3.12; dependências resolvidas no índice público. |
| Integridade de dependências | `uv pip check` e `pip check` sem requisitos quebrados. |
| Comandos instalados | `ttsbr --help` e `ttsbr-api --help` funcionaram fora do checkout. Módulo GUI importável, sem Tkinter nesse Python. |
| Isolamento de dados | Versão instalada separa dados graváveis do diretório dos módulos. Recursos da documentação incluídos. |
| Áudio real | Corpus PT/ES gerado em CPU com XTTS, oito segmentos; WAV e MP3. |
| Legendas | SRT e VTT com oito entradas, correspondentes aos segmentos do manifesto. |
| Saída final | WAV mono, 16 bits, 48 kHz, aproximadamente 33,23 s. |
| Cache e interrupção | Reexecução sem nova inferência; interrupção entre segmentos preservou a saída anterior; retomada concluída. |
| Trilha | Mixagem com trilha sintética e auto-ducking manteve a duração. |
| Loudness medido | Alvo −16 LUFS; medidos −16,55 sem trilha e −16,66 com trilha. Variação inferior a 1 LU na amostra. |
| Whisper real | 84 palavras de referência, um erro, WER global de aproximadamente 1,19%; todos os segmentos dentro do limite de 10%. |
| Referências sintéticas | Clonagem PT/ES, mapeamento por personagem, tom e limpeza concluídos com Torch/Torchaudio 2.8. |
| HTTP real | Áudio WAV retornado com HTTP 200; requisição repetida recuperou o cache; velocidade nula retornou 400. |
| HTTP automatizado | Rotas, JSON inválido, tipos inválidos, erros 400/404/500 e recuperação após erro exercitados por servidor local real. |

O resumo público está em [resultado_estabilizacao.json](../avaliacao/resultado_estabilizacao.json). Ele contém o ambiente e as medições, sem roteiros privados ou caminhos da máquina. Os artefatos completos de execução e os áudios são locais e não entram no Git.

A medição de WER não avalia naturalidade, sotaque ou qualidade de clonagem. A divergência observada foi `veintiún` / `veintiuno` após o ASR representar o valor como `21`. As métricas acústicas examinam os segmentos de fala antes de LUFS e trilha; o loudness do arquivo final foi medido separadamente.

## Compatibilidade de leitura de referências

A instalação inicialmente resolvida usou Torch 2.15.0 e Torchaudio 2.11.1. Vozes embutidas, WER e exportação passaram, mas a leitura direta de referências por `torchaudio.load` falhou no TorchCodec por ausência das bibliotecas compartilhadas do FFmpeg. O executável de `imageio-ffmpeg` usado na exportação não supre essas bibliotecas nativas.

A referência alternativa em `constraints/macos-py312.txt` usa o par Torch/Torchaudio 2.8.0, que mantém a leitura por SoundFile nesse ambiente. A leitura real do WAV e a geração de dois trechos clonados PT/ES foram aprovadas, com referências sintéticas produzidas pelo próprio projeto. Também foram exercitados o mapeamento por personagem, o condicionamento por tom e a higienização via FFmpeg. Isso não avalia a qualidade de gravações pessoais nem a fidelidade percebida da clonagem. As versões da primeira resolução ficam separadas em `constraints/macos-py312-recente.txt`, como evidência do diagnóstico; não são a recomendação de instalação para clonagem sem FFmpeg compartilhado.

A mudança de backend a partir do Torchaudio 2.9 é descrita na [documentação do Torchaudio 2.8](https://docs.pytorch.org/audio/2.8/generated/torchaudio.load.html). Para usar a linha recente com clonagem, é necessário satisfazer os requisitos nativos do TorchCodec e repetir os testes. Nenhum ambiente preexistente do usuário foi alterado; a comparação foi realizada no ambiente isolado desta etapa.

## Correções aplicadas

- Descoberta de módulos tornada explícita no `pyproject.toml`, evitando incluir diretórios privados e saídas.
- Licença do pacote migrada para a declaração SPDX MIT, preservando os avisos separados de terceiros.
- Extra `validacao` adicionado para instalar as ferramentas opcionais.
- Construção em cópia temporária pública, sem metadados AppleDouble que invalidaram uma instalação do wheel criado diretamente no volume externo.
- A GUI instalada prefere seu próprio Python, sem escolher automaticamente outro ambiente pessoal.
- Caminhos de dados e documentação separados para a versão instalada; `TTSBR_HOME` permite escolher a pasta gravável.
- API passou a rejeitar entradas não textuais, velocidades inválidas e sinalizadores de limpeza não booleanos com erro de entrada.
- Configurações avançadas da GUI passaram a ter rolagem, para que os campos adicionados não dependam da altura da tela.
- Referências de áudio relativas ao roteiro original são preservadas pelo worker, mesmo quando a GUI usa um snapshot.
- Manifesto passou a registrar hashes dos novos módulos do pipeline, além dos três arquivos anteriores. Esses hashes continuam sendo rastreabilidade, não invalidação automática de cache.

## Reproduzir a construção

Use Python 3.12 em um ambiente virtual. Tkinter continua dependendo da instalação do Python e não é instalado pelo extra de validação.

```bash
cd /CAMINHO/DO/TTSBR && python3.12 -m venv .venv
cd /CAMINHO/DO/TTSBR && .venv/bin/python -m pip install build
cd /CAMINHO/DO/TTSBR && .venv/bin/python scripts/construir.py
cd /CAMINHO/DO/TTSBR && .venv/bin/python -m pip install "dist/ttsbr-1.0.0-py3-none-any.whl[validacao]" -c constraints/macos-py312.txt
cd /CAMINHO/DO/TTSBR && .venv/bin/python -m pip check
```

Os comandos acima são para o checkout deste Mac. Não recrie um ambiente já existente sem avaliar seu uso; escolha outro diretório para repetir a instalação limpa. O script de construção precisa de `build`; no Python 3.10 também precisa de `tomli`, disponível no extra `dev`.

A lista em [constraints/macos-py312.txt](../constraints/macos-py312.txt) registra versões resolvidas e exercitadas no ambiente novo. Não é um lockfile universal: não a aplique como prova de compatibilidade Windows, outras arquiteturas ou outras versões de Python. Ela não inclui pesos dos modelos nem garante que esses arquivos estarão sempre disponíveis para download.

A construção usa uma lista pública de módulos, documentação, exemplos e testes. Ela não copia `local/`, `saida/`, `.env`, `GEMINI.md`, ambientes virtuais ou roteiros pessoais. Prefira esse script ao construir no volume externo. Em versões de Python sem Tkinter, testar o módulo GUI não equivale a testar a janela.

## Pendências que exigem outra execução ou avaliação humana

### GUI no macOS

- [ ] Abrir a janela em uma sessão gráfica com Tkinter disponível.
- [ ] Testar abrir/salvar um roteiro, confirmação de alterações não salvas e atalhos.
- [ ] Conferir a rolagem dos ajustes avançados com a resolução e escala reais da tela.
- [ ] Gerar uma amostra e uma narração; observar se a janela permanece responsiva.
- [ ] Interromper após um trecho e retomar com o mesmo nome de saída.
- [ ] Abrir um manifesto, ouvir trechos pelo player padrão e executar a validação.
- [ ] Regerar um segmento mantendo roteiro e configurações correspondentes ao resultado.
- [ ] Fechar durante uma tarefa e conferir o comportamento de espera.

### Audição e gravações de referência

- [ ] Ouvir a amostra PT/ES e registrar pronúncia, naturalidade, sotaque e cortes.
- [ ] Comparar os arquivos com e sem trilha; conferir inteligibilidade e transições de volume.
- [ ] Experimentar referências de voz próprias e autorizadas, incluindo silêncio, ruído e arquivos com espaços no caminho.
- [ ] Avaliar condicionamento por tom e limpeza de referência em gravações representativas. Esses recursos têm cobertura automatizada, mas a qualidade percebida não foi aprovada.

### Windows e outros dispositivos

- [ ] Exercitar o primeiro download de modelos em uma máquina sem cache. Nesta rodada os pesos já estavam disponíveis.
- [ ] Instalar em um Windows real com Python 3.12 e Tkinter, usando um ambiente novo.
- [ ] Construir e instalar o pacote; conferir os três comandos e o iniciador `.bat`.
- [ ] Repetir CLI, GUI, FFmpeg, legendas, API, cache e retomada.
- [ ] Conferir acentos, espaços em nomes de usuário/pastas, permissões e player padrão.
- [ ] Testar CUDA apenas se houver GPU compatível; os ensaios reais desta etapa usaram CPU.
- [ ] Comparar CPU/MPS no Mac se MPS for parte do uso pretendido; MPS não foi validado nesta rodada.

### Antes de publicar como versão estável

- [ ] Resolver falhas graves eventualmente encontradas nas verificações acima.
- [ ] Revisar os dados públicos e os avisos de licença.
- [ ] Criar commit e push das correções. A remoção local de `GEMINI.md` do índice já estava pendente antes desta etapa e foi preservada.
- [ ] Escolher explicitamente o número da release e atualizar os resultados caso o áudio ou o ambiente mudem.

Até concluir essas pendências, a declaração correta é **backend e instalação exercitados no macOS/CPU, com GUI visual e Windows ainda pendentes**.
