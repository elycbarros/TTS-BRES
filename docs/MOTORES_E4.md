# Motores de síntese — E4 concluída

O XTTS está representado por um adaptador com contrato de capacidades (`motores.py`), incluindo fallback via `soundfile` em `torchaudio.load` para ambientes com Torchaudio ≥ 2.9 sem `libtorchcodec` nativo. O manifesto e os parâmetros do cache registram `motor: xtts_v2` e o identificador do modelo. A adição desse campo invalida as chaves antigas: áudios já gerados não são apagados, mas segmentos anteriores precisarão ser gerados novamente para entrar no novo cache.

Em 07/11/2026, 162 testes passaram no macOS/Python 3.12.14, incluindo dois testes novos do contrato e da distinção de chaves. A suíte usa síntese simulada e não comprova qualidade de clonagem nem compatibilidade Windows.

O OmniVoice ainda não está integrado ao pipeline nem foi executado com modelo real. Seu código e seus pesos têm condições distintas: consulte o [repositório upstream](https://github.com/k2-fsa/OmniVoice) e o [cartão do modelo](https://huggingface.co/k2-fsa/OmniVoice) antes de instalar. Faltam o experimento em ambiente separado, verificação das licenças dos artefatos efetivamente usados, conversão explícita de áudio, teste de falhas e comparação auditiva PT/ES. A E4 permanece em andamento.

## Worker experimental isolado

`omnivoice_experimental.py --worker` aceita um pedido JSON pela entrada padrão. Execute-o somente no Python de um ambiente separado, com o pacote `omnivoice` e seus requisitos instalados e um diretório local de pesos já preparado. O worker exige `modelo`, `referencia`, `transcricao`, `texto`, `idioma`, `saida` e, opcionalmente, `dispositivo` (`cpu`, `mps` ou `cuda`). O caminho de saída deve ser temporário e privado: o worker pode sobrescrevê-lo.

A transcrição é obrigatória para evitar o caminho de ASR automático. As variáveis de modo offline do Hugging Face/Transformers são ativadas antes da importação; isso não é um bloqueio de rede de todo o processo. São medidas a carga, a primeira e a segunda síntese e calculado o RTF quente. A saída é convertida para WAV PCM mono/16 bits/24 kHz; isso pode reduzir a precisão do sinal original. O OmniVoice 0.2.1 não expõe semente, que fica registrada como `null`. O relatório inclui o pico de memória residente do processo worker (`memoria_pico_processo_bytes`, via `getrusage`); isso não inclui memória da GPU/MPS não residente nem outros processos.

O worker ainda não está conectado ao XTTS, à fila ou à GUI. Não execute em referências pessoais até verificar a licença dos pesos e tokenizador instalados e as condições de uso aplicáveis. O código upstream descreve a API de clonagem e o uso de `ref_audio` e `ref_text` em sua [documentação](https://github.com/k2-fsa/OmniVoice#python-api). Até executar e ouvir ambos os motores com corpus equivalente, não há conclusão sobre desempenho ou qualidade em PT-BR/ES.

Em 07/11/2026, a suíte completa passou com **165 testes** no macOS/Python 3.12.14. Os três testes do worker usam um motor simulado; não verificam compatibilidade da API com um pacote OmniVoice instalado nem medem áudio real.

## Supervisão e preparação da comparação

`comparar_motores_e4.py` executa o worker OmniVoice em outro Python, limita o tempo, confirma o encerramento dos processos, valida a saída e registra hashes da referência, do texto, da transcrição e do WAV. Antes de iniciar o worker, a revisão informada é **verificada**: cada arquivo do diretório de pesos precisa ter metadados de download do Hugging Face com o mesmo commit, e seu conteúdo precisa corresponder ao ETag registrado (SHA-256 nos arquivos LFS e SHA-1 de blob Git nos demais). Arquivos ausentes, sem registro, de outra revisão ou alterados bloqueiam a execução. O relatório inclui `revisao_verificada`, a quantidade de arquivos conferidos e um SHA-256 do manifesto. Pesos obtidos sem esses metadados (por exemplo, copiados manualmente) não são aceitos. A saída é criada com exclusividade: arquivos existentes são preservados. A cópia final não é uma transação atômica em todos os sistemas; uma queda abrupta durante a cópia pode deixar arquivo parcial.

Exemplo, após instalar as dependências em ambiente separado e preparar os pesos locais:

```bash
python comparar_motores_e4.py \
  --python ~/ttsbr-e4/omni/bin/python \
  --modelo local/modelos/omnivoice \
  --referencia local/referencia.wav \
  --transcricao-arquivo local/transcricao.txt \
  --texto-arquivo local/texto-teste.txt \
  --idioma pt --revisao REVISAO_DOS_PESOS \
  --saida local/omnivoice-teste.wav > local/omnivoice-relatorio.json
```

Para obter uma referência XTTS com o mesmo texto e áudio, usando o ambiente do TTSBR:

```bash
python tts.py local/texto-teste.txt --voz local/referencia.wav \
  --idioma pt --velocidade 1.0 --sem-normalizar --sem-corte-silencio \
  --formatos wav --saida local/xtts-teste
```

O segundo comando é uma preparação manual, não um benchmark equivalente automatizado: o pipeline XTTS aplica seus próprios ajustes de volume e pausas. Compare a audição em volume equivalente e registre essas diferenças. O comparador ainda não mede carga quente do XTTS, memória do XTTS ou da GPU/MPS, WER ou avaliação perceptiva, e não faz comparação automática entre motores.

O worker OmniVoice desativa explicitamente o carregamento de ASR e recusa taxa nativa diferente de 24 kHz, áudio não mono, vazio ou com valores não finitos. O ASR automático permanece desativado; o modo offline é uma configuração de bibliotecas e não substitui restrições de rede do sistema.

Em 07/11/2026, **172 testes** passaram no macOS/Python 3.12.14. Os testes do supervisor usam subprocessos e arquivos sintéticos, incluindo timeout, falha, referência alterada e preservação de saídas. Nenhuma inferência real com OmniVoice foi executada; seu funcionamento, dependências, licença exata dos pesos e avaliação auditiva continuam pendentes.

## Preparação real do ambiente — 07/11/2026

**Volumes exFAT não servem para o ambiente virtual.** No macOS, volumes exFAT recebem arquivos AppleDouble (`._*`) ao lado de cada arquivo com atributos estendidos. Na primeira tentativa, com o ambiente em `work/e4-omni` no volume externo, isso causou duas falhas: o uv recusou o wheel do `numba` porque `._numba` não constava do `RECORD`, e o `import omnivoice` falhou com `UnicodeDecodeError` quando o Transformers tentou ler `._*.py` em `transformers/models`. Crie o ambiente em volume APFS:

```bash
uv venv --python 3.12 ~/ttsbr-e4/omni
uv pip install --python ~/ttsbr-e4/omni/bin/python omnivoice
```

Os pesos podem ficar no volume externo. Remova os `._*` com `dot_clean -m <pasta-dos-pesos>` antes de usar; a verificação de pesos ignora esses arquivos.

**Estado verificado, sem inferência:**

| Item | Resultado |
|---|---|
| Ambiente | Python 3.12.14, `omnivoice` 0.2.1, torch 2.15.0, transformers 5.22.2, MPS disponível (Apple Silicon) |
| Pesos | `k2-fsa/OmniVoice` revisão `c5fdb5ccb189668d56333f77ba2629f4cd7535f4`, 13 arquivos (~3,1 GB) conferidos contra os ETags em cerca de 8 s |
| API do pacote instalado | `from_pretrained(..., load_asr=False)` não carrega Whisper; `generate(text, language, ref_text, ref_audio)` devolve `list[np.ndarray]`; `pt` e `es` constam dos IDs de idioma; não há parâmetro de semente |
| Taxa nativa | 24 kHz (`audio_tokenizer/preprocessor_config.json`) |
| Licenças | código Apache 2.0; pesos CC-BY-NC; tokenizador de áudio sob Boson Higgs Audio 2 Community License (ver [avisos de terceiros](../THIRD_PARTY_NOTICES.md)) |

Observações do código upstream que afetam a medição:

- Com `device_map='mps'`, o tokenizador de áudio Higgs roda **na CPU**, porque não suporta MPS. As medições em MPS são, portanto, mistas.
- Um código de idioma não reconhecido não gera erro: o pacote emite um aviso e passa ao modo sem idioma. O worker valida `pt`/`es` antes de chamar o modelo.
- Se `ref_text` faltar, o pacote tenta carregar o Whisper (`openai/whisper-large-v3-turbo`) sob demanda. O worker sempre envia a transcrição e o supervisor ativa o modo offline, de modo que esse caminho falha em vez de baixar.
- O `ffmpeg` do sistema não foi encontrado pelo pydub do ambiente. Use referências WAV até isso ser avaliado.

A primeira inferência real ainda depende de uma referência autorizada com transcrição exata. Até lá, nada se conclui sobre qualidade, desempenho ou estabilidade em PT-BR/ES. Em 07/11/2026, **175 testes** passaram no macOS/Python 3.12.14, incluindo três novos de verificação de pesos com downloads simulados.

## Ensaio comparativo real XTTS v2 vs. OmniVoice 0.2.1 — 07/11/2026

Executado em macOS Apple Silicon (arm64), Python 3.12.14, comparando o `MotorXTTS` (`coqui-tts`, Torchaudio 2.11 com fallback `soundfile`) e o worker isolado `omnivoice_experimental.py` (`omnivoice` 0.2.1, revisão verificada `c5fdb5ccb189668d56333f77ba2629f4cd7535f4`), com referências WAV mono 24 kHz e transcrições explícitas:

| Motor / Idioma / Dispositivo | Carga (s) | 1ª síntese (s) | Síntese quente (s) | Duração (s) | RTF quente | Pico RSS (GB) | WER Whisper (`whisper-small`) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **XTTS v2** (`pt`, `mps`) | 34,82 | 4,31 | **4,27** | 7,56 | **0,56** | 4,20 | **0,0%** (0/16) |
| **OmniVoice 0.2.1** (`pt`, `mps`) | 1,07 | 20,48 | 16,80 | 7,30 | 2,30 | 3,80 | **0,0%** (0/16) |
| **OmniVoice 0.2.1** (`pt`, `cpu`) | 0,52 | 21,44 | 21,67 | 7,34 | 2,95 | 4,20 | **0,0%** (0/16) |
| **XTTS v2** (`es`, `mps`) | 34,82 | 3,87 | **3,69** | 6,64 | **0,56** | 4,20 | **0,0%** (0/16) |
| **OmniVoice 0.2.1** (`es`, `mps`) | 0,89 | 16,20 | 15,88 | 6,88 | 2,31 | 2,72 | **0,0%** (0/16) |

### Conclusão técnica e decisão da E4

1. **Inteligibilidade e sinal:** ambos os motores atingiram **0,0% de WER** em português e espanhol no `openai/whisper-small`, sem amostras saturadas (`fracao_amostras_saturadas: 0.0`) e sem avisos acústicos (`RMS` entre `-20,17` e `-21,56 dBFS`).
2. **Desempenho de síntese contínua (RTF quente):** no Apple Silicon (`mps`), o **XTTS v2 é ~4,1x mais rápido por segundo de áudio gerado** (`RTF 0,56` vs. `2,30–2,31` do OmniVoice), porque o tokenizador de áudio Higgs do OmniVoice não suporta MPS e executa na CPU.
3. **Requisitos e licenciamento:** o OmniVoice exige transcrição exata da referência (`ref_text`) para não acionar download de ASR, não expõe semente determinística na versão `0.2.1` e combina três regimes de licença (Apache 2.0 no código, CC-BY-NC nos pesos e Boson Higgs Audio 2 Community License no tokenizador).
4. **Decisão arquitetural:** o **XTTS v2 permanece como motor padrão único integrado à CLI, GUI, API e fila** para a linha `1.1.0`. O OmniVoice permanece disponível e suportado exclusivamente por meio do supervisor isolado (`comparar_motores_e4.py` + `omnivoice_experimental.py`) em ambiente virtual separado.
