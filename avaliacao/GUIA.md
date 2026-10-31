# Avaliação de qualidade PT/ES

[README](../README.md) · [Referência](../docs/REFERENCIA.md) · [Arquitetura](../docs/ARQUITETURA.md)

O corpus fixo `corpus_pt_es.txt` cobre datas, horários, dinheiro, negativos, troca de idioma, ênfase e pausas explícitas. Os rótulos fixam as vozes e o idioma para permitir comparações entre versões.

## Gerar e medir

Na raiz do projeto, com o ambiente virtual ativado:

```bash
# Gera fala real; repita o comando para retomar uma execução interrompida
python tts.py avaliacao/corpus_pt_es.txt --saida saida/avaliacao_pt_es --formatos wav --dispositivo cpu

# Transcreve cada segmento no próprio idioma e grava métricas + WER
python validar_audio.py --manifesto saida/avaliacao_pt_es.blocos.json

# Alternativa sem Whisper: somente duração, RMS, pico e saturação
python validar_audio.py --manifesto saida/avaliacao_pt_es.blocos.json --somente-metricas --relatorio saida/avaliacao_pt_es.metricas.json
```

Em ambientes restritos, se o Numba não conseguir gravar o cache do Librosa, defina `NUMBA_CACHE_DIR` para uma pasta gravável antes da validação, com estes comandos no macOS/Linux:

```bash
mkdir -p saida/.numba_cache
export NUMBA_CACHE_DIR="$PWD/saida/.numba_cache"
```

Para trabalhar sem rede após baixar os modelos, é possível definir `HF_HUB_OFFLINE=1` para o Hugging Face. Isso não baixa dependências nem modelos ausentes.

O relatório padrão fica em `saida/avaliacao_pt_es.blocos.validacao.json`. Use `--relatorio` para preservar relatórios distintos. O modo de métricas não concede aprovação automática da fala e substitui o relatório padrão se o mesmo caminho for usado.

O WER global é ponderado pela quantidade de palavras de referência. O relatório também contém WER por idioma e por segmento, transcrição, divergências e posição de cada fala no WAV final. A aprovação automática exige que **todos os segmentos** respeitem o limite (padrão 10%); portanto, um WER global baixo pode coexistir com reprovação.

O validador lê os WAVs do cache: ele verifica a fala antes da codificação MP3, não a integridade do arquivo final. Tempos se referem à montagem WAV; a codificação MP3 pode introduzir um pequeno deslocamento. Manifestos antigos sem tempos mostram posição indisponível; execute novamente a síntese para atualizar o manifesto usando o cache.

## Resultado inicial registrado

Este resultado é histórico e anterior às alterações posteriores de normalização e processamento. Ele não certifica a qualidade da revisão atual. Para avaliar uma nova revisão, gere outra saída, valide-a e preserve o relatório em um arquivo separado.

A medição em [resultado_inicial.json](resultado_inicial.json) usou o corpus com XTTS v2 e Whisper reais, em CPU:

| Medida | Resultado |
|---|---|
| Segmentos | 8 |
| Palavras de referência | 85: 45 em PT e 40 em ES |
| WER em português | 0% |
| WER em espanhol | 2,5% |
| WER global | Aproximadamente 1,2% |
| Limite por segmento | 10%; todos os trechos passaram |
| Avisos acústicos | Nenhum na amostra |
| Naturalidade e sotaque | Não avaliados por audição |

A única substituição foi `veintiún` / `veintiuno`, no trecho em que o Whisper escreveu `21`. O resultado é uma referência inicial desse ambiente e corpus, não uma garantia para outros textos. O JSON registra resultados agregados; mantenha esse arquivo como resultado histórico e grave novas medições em arquivos separados.

Os áudios e relatórios completos são gerados em `saida/`, que é ignorada pelo Git. Clonar o repositório não inclui esses arquivos: execute os comandos acima para obter uma nova amostra.

## Comparar versões

1. Gere a versão de referência com `--saida saida/qualidade_base`.
2. Após a alteração, gere a candidata com `--saida saida/qualidade_candidata`.
3. Use os mesmos parâmetros e ambiente; registre versão do código, modelo, dispositivo e opções utilizadas.
4. Valide cada manifesto e compare os segmentos, o WER por idioma e as métricas.
5. Ouça os dois WAVs com o mesmo volume de reprodução, alternando a ordem para reduzir preferência pela primeira amostra.

Saídas diferentes usam caches distintos. Se reutilizar o mesmo caminho e quiser outra realização de uma fala, passe `--refazer`: a síntese pode variar entre execuções, e o cache preserva a realização anterior. Não atribua uma pequena diferença de WER apenas à mudança de código sem repetir a comparação.

## Ficha de audição

Copie a tabela para registrar cada avaliação. Deixe as notas em branco até ouvir os áudios; métricas e transcrição não substituem audição.

| Critério | Como avaliar | Nota de 1 a 5 |
|---|---|---|
| Inteligibilidade | Entende-se cada palavra sem consultar o texto? | |
| Pronúncia | Datas, valores e números estão corretos? | |
| Naturalidade | O ritmo e a entonação soam naturais? | |
| Continuidade | Há palavras cortadas, estalos ou mudanças abruptas? | |
| Idioma e sotaque | Cada trecho soa adequado ao idioma pretendido? | |
| Pausas e volume | A pausa de 800 ms e a ênfase ajudam a leitura? | |

Registre também **versão, dispositivo, locutor, segmento, tempo e observação**. Escala: 1 = problema grave; 3 = utilizável com ressalvas; 5 = sem problema perceptível na amostra. Uma avaliação individual não equivale a uma medida padronizada de opinião média.

## Licença dos áudios de avaliação

Os áudios produzidos pelo corpus com XTTS v2 estão sujeitos à [Coqui Public Model License](https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt), e não à MIT do código original. Ao compartilhar as amostras, inclua a referência aos termos aplicáveis. Consulte os [avisos de terceiros](../THIRD_PARTY_NOTICES.md).

## Limites das medições

- O WER inclui erros do Whisper e diferenças de escrita. A referência é o texto enviado à síntese; pronúncias fonéticas do glossário podem divergir da ortografia usada pelo ASR.
- `rms_dbfs` mede energia média, não volume perceptivo padronizado. `pico_dbfs` mede pico de amostra, não pico real entre amostras.
- Amostras com amplitude absoluta a partir de 0,999 são sinalizadas como próximas da saturação. Isso não prova distorção audível.
- RMS abaixo de −60 dBFS recebe um aviso de silêncio ou nível muito baixo. Silêncio digital produz valores `null` para RMS e pico.
- O corpus é uma verificação inicial, não uma avaliação exaustiva de qualidade. Amplie-o com textos representativos do uso real.
