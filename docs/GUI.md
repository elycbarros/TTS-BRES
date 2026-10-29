# Interface gráfica local

[README](../README.md) · [Referência da CLI](REFERENCIA.md) · [Arquitetura](ARQUITETURA.md)

A primeira versão da GUI oferece editor de roteiro, configuração de voz, análise antes da síntese, geração de amostra, progresso por segmento, retomada, interrupção entre trechos e revisão com ferramentas do sistema. O pipeline de síntese é o mesmo usado pela CLI.

Esta é uma versão inicial para uso pessoal, preparada para macOS e Windows. Não é um instalador independente. Os testes automatizados verificam a integração e os processos de trabalho; a janela e o player precisam de verificação no desktop de cada sistema.

## Requisitos e inicialização

A janela requer Python com **Tkinter/Tcl/Tk**. O processamento requer o ambiente Python do TTSBR com as dependências já usadas pela CLI. Eles podem ser o mesmo Python ou instalações diferentes.

No terminal, este comando verifica a disponibilidade de Tkinter abrindo sua janela de demonstração:

```bash
python3 -m tkinter
```

Para abrir o TTSBR:

```bash
python3 gui.py
```

No macOS, também é possível abrir `abrir_gui.command`. No Windows, com o Python Launcher instalado, use `abrir_gui.bat` ou execute:

```powershell
py -3 -m tkinter
py -3 gui.py
```

Se o comando Python não existir, use o caminho completo do executável instalado. A GUI deve ser iniciada em uma sessão gráfica do usuário; uma sessão remota ou restrita pode não permitir abrir janelas.

### Quando o ambiente do TTS não tem Tkinter

Um ambiente pode executar o XTTS normalmente e ainda apresentar `No module named '_tkinter'` ao tentar abrir a GUI. Tkinter é um componente opcional da instalação do Python, não uma dependência resolvida com `pip install tkinter`.

Use uma instalação de Python com Tkinter para abrir `gui.py`. Depois, em **Ajustes avançados → Python do ambiente TTSBR**, selecione o executável do ambiente de síntese:

| Sistema | Exemplo de caminho relativo ao projeto |
|---|---|
| macOS | `.venv/bin/python` |
| Windows | `.venv\Scripts\python.exe` |

O aplicativo procura automaticamente um ambiente `.venv` na pasta do projeto e, depois, um ambiente `ttsbr` em `~/.venvs/`. Se não encontrar, usa o próprio Python da janela. A preferência salva prevalece; ajuste-a quando mover ou recriar o ambiente. O Python da janela precisa apenas da biblioteca padrão; não precisa carregar Torch ou XTTS.

Veja a [documentação oficial do Tkinter](https://docs.python.org/3/library/tkinter.html) e as orientações do distribuidor do seu Python para instalar o componente gráfico. Não é necessário reinstalar o ambiente do modelo para escolher um Python diferente para a janela.

## Fluxo de uso

1. **Abrir ou escrever:** carregue um `.txt` em UTF-8 ou escreva na aba Roteiro. Os botões inserem exemplos de pausa, ênfase e personagem na posição do cursor.
2. **Configurar:** escolha idioma, voz, velocidade, formatos e nome base da saída. Referência de voz é opcional e prevalece sobre vozes embutidas e personagens.
3. **Conferir roteiro:** valide as opções e veja os segmentos normalizados, sem carregar XTTS nem criar os arquivos finais. Um snapshot local é salvo para o worker.
4. **Gerar amostra:** selecione um trecho ou use o primeiro parágrafo. O limite da amostra é 1.200 caracteres. A saída usa o nome base acrescido de `.amostra`.
5. **Gerar / retomar:** processe o roteiro completo. A aba de segmentos indica os trechos gerados e os recuperados do cache.
6. **Revisar:** ouça o resultado ou um segmento e, opcionalmente, execute Whisper ou métricas sem transcrição.

A GUI usa um snapshot do roteiro: a geração não exige salvar por cima do arquivo aberto. **Salvar** grava no arquivo aberto ou solicita um caminho quando o roteiro é novo. Ao fechar ou trocar o roteiro, alterações não salvas podem ser salvas, descartadas ou mantidas cancelando a ação.

O glossário automático associado ao arquivo aberto é preservado na preparação do snapshot. Os glossários do diretório de trabalho usam a raiz do projeto, pois é ali que o worker executa.

## Ajustes avançados

- Executável Python do processamento.
- Dispositivo: automático, CPU, MPS ou CUDA.
- Volume alvo em dBFS.
- Glossário adicional em TXT ou JSON.
- Pausas por frase, reticências, ponto e vírgula/dois-pontos, corte intermediário, parágrafo e bloco.
- Desativar normalização, preservar silêncio nas bordas e refazer o cache.

A entrada de voz aceita outros nomes embutidos além das sugestões da lista. A validação das opções é feita pelo pipeline existente; erros e mensagens das bibliotecas aparecem na aba Registro.

## Interrupção e retomada

**Interromper após o trecho** solicita uma parada cooperativa. O trecho em andamento, incluindo eventual carregamento do modelo, precisa terminar antes de a solicitação ser atendida. Segmentos concluídos permanecem no cache. O manifesto passa a `interrompido` e não há exportação final daquela tentativa.

Repita a geração com o mesmo nome de saída para retomar. A interface pode levar algum tempo para responder à solicitação se o modelo estiver carregando ou sintetizando um trecho longo. O botão fica indisponível durante a montagem/exportação e a validação.

Ao fechar durante uma tarefa, a GUI pode aguardar a parada entre trechos ou o término da validação/exportação. Não há botão de encerramento forçado na primeira versão. Se uma biblioteca travar, a parada cooperativa não consegue interrompê-la.

## Revisão e reprodução

A reprodução abre o **player padrão do sistema**. Esta versão não possui player embutido, controle de volume de reprodução nem navegação por forma de onda. Se WAV e MP3 estiverem disponíveis, o botão do resultado prefere WAV.

É possível abrir um manifesto concluído com **Abrir manifesto…**, sem gerar novamente o roteiro. Os arquivos do cache precisam continuar acessíveis. Depois de uma interrupção, gere novamente para retomar antes de validar o manifesto.

A validação usa o idioma de cada segmento e o limite padrão de WER de 10%. O resultado acima do limite é apresentado como reprovação da fala, sem ser confundido com falha operacional do worker. Para outros modelos ou limites de WER, use a CLI nesta versão.

Os relatórios da GUI são gravados ao lado do manifesto:

- Transcrição e WER: `<nome>.blocos.validacao.json`.
- Métricas sem Whisper: `<nome>.blocos.metricas.json`.

No modo de métricas, não há aprovação automática. O manifesto validado é o último resultado gerado ou o arquivo aberto para revisão; editar o roteiro não altera esse resultado anterior.

## Arquivos locais e privacidade

A GUI salva em `local/gui/`, que é ignorado pelo Git:

| Local | Conteúdo |
|---|---|
| `preferencias.json` | Configuração da interface, incluindo caminhos de arquivos e Python. |
| `execucoes/<id>/` | Snapshot do roteiro, pedido de execução, glossário preparado e sinal de interrupção. |
| `numba_cache/` | Cache de processamento para Librosa/Numba, quando necessário. |

Esses arquivos podem conter roteiros e caminhos pessoais. Eles não são criptografados e permanecem no disco; a limpeza é manual, com o aplicativo fechado. O `.gitignore` não impede leitura por outros programas do usuário.

As saídas finais e o cache de fala usam a pasta escolhida. Prefira `saida/` ou outros diretórios privados. As preferências não armazenam o conteúdo do editor, mas os snapshots de execução o armazenam. O histórico de logs exibido na janela é limitado para evitar crescimento contínuo de memória.

## Limites desta versão

- Não há instaladores `.app`/`.exe`, atualização automática ou ambiente Python embutido.
- Não há fila de tarefas; a janela executa um trabalho de cada vez.
- Não há editor visual de diálogos, regeneração seletiva por clique nem controle de emoção.
- Abrir um manifesto não restaura o roteiro original no editor.
- Naturalidade e sotaque continuam exigindo audição.
- Janelas e reprodução no Windows ainda precisam de validação nesse sistema.
- O XTTS v2 e suas saídas permanecem sujeitos à [CPML](https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt); a GUI não altera as condições de uso.

## Arquivos da implementação

| Arquivo | Responsabilidade |
|---|---|
| `gui.py` | Widgets, diálogos, editor e atualização da janela. |
| `gui_core.py` | Snapshots, argumentos e leitura dos eventos do subprocesso em thread. |
| `gui_worker.py` | Execução isolada de análise, síntese e validação. |

Cada tarefa abre um novo worker; o modelo não permanece carregado entre tarefas. Uma amostra e uma geração completa podem carregar o modelo separadamente, a menos que o cache já resolva a geração.

A janela não importa Torch nem XTTS. A comunicação usa eventos JSON identificados no stdout do worker, acompanhados dos logs. O worker chama as mesmas funções da CLI, e os widgets são atualizados somente pelo event loop da janela.
