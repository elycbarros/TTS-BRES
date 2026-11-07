# Projetos e revisão de tomadas — E2

[README](../README.md) · [GUI](GUI.md) · [Roadmap](ROADMAP_0.9.0.md) · [Biblioteca de vozes](BIBLIOTECA_VOZES.md)

Esta entrega implementa projetos locais, rascunho, correções por segmento, histórico de tomadas e controles de reprodução. A janela e o dispositivo de áudio ainda precisam de validação no desktop; Windows e audição de clonagem seguem pendentes. A forma de onda não faz parte desta entrega.

## Fluxo na interface

1. Abra um roteiro ou escreva no editor. Configure idioma, perfil de voz e parâmetros.
2. No menu **Projeto**, use **Novo projeto…** e dê um título. O texto do editor é salvo como roteiro original; a normalização não o substitui.
3. Clique **Conferir roteiro**. O plano recebe IDs estáveis para permitir revisão.
4. Use **Gerar / retomar áudio**. Para projetos, cada execução recebe uma pasta própria em `local/projetos/ID/tomadas/ID_TOMADA/`. O campo de saída da janela continua sendo usado no fluxo de texto avulso; a geração completa de projeto usa as pastas gerenciadas.
5. Selecione um segmento e use **Editar fala…** para corrigir sua pronúncia/texto preparado. Depois clique **Regerar trecho selecionado**. As falas válidas restantes são recuperadas do cache.
6. No menu **Projeto → Tomadas A/B…**, escolha uma tomada para A e outra para B, alternando **Ouvir A** e **Ouvir B**. Apenas um player é mantido ativo.
7. Use **Salvar projeto** ou o atalho de salvar. **Abrir projeto…** restaura roteiro, configurações, glossário, IDs e histórico. O Python de execução é uma preferência local e não é restaurado do documento.

**Gerar amostra** continua como prévia avulsa; não é registrada no histórico de tomadas completas do projeto. A [E3](FILA_TAREFAS.md) acrescentou fila durável e recuperação coordenada de tarefas. No fluxo da E2, executar outra geração cria nova pasta de tomada e reaproveita o cache; na fila E3, retomar conserva o snapshot e a pasta da tarefa interrompida; uma tomada incompleta não entra no histórico concluído.

## Correção e identidade dos segmentos

O roteiro original, o texto preparado e a correção manual são campos distintos. A correção deve ter até 200 caracteres, sem tags, e é enviada ao motor como fala preparada: não passa novamente pela normalização. A pausa daquele segmento segue a pontuação e as tags do roteiro original. Para alterar estrutura, pausas, personagens ou tags, edite o roteiro e confira novamente.

O documento de revisão guarda o hash do plano completo. Se texto, idioma, locutor ou preparação divergirem, a geração é recusada antes de sobrescrever a saída. Use **Conferir roteiro** para reconciliar o plano.

Subsequências que continuam iguais preservam IDs. Segmentos alterados recebem novos IDs; correções que perderam seu segmento são descartadas do plano atual, mas permanecem nas versões anteriores do projeto. Quando existem frases repetidas e o plano muda, o reconciliador evita transportar IDs/correções para ocorrências ambíguas: confira novamente essas frases.

Cada tomada concluída preserva seu WAV/MP3 e manifesto. Seus segmentos são copiados do cache compartilhado para a pasta da tomada; regenerar com `--refazer-segmentos` não modifica o áudio de uma tomada antiga. Tempos do manifesto e legendas SRT/VTT são recalculados na montagem.

## Player integrado

No Python selecionado para síntese, instale o extra opcional a partir do projeto:

```bash
python -m pip install ".[reproducao]"
```

Ao instalar um wheel, use o caminho do wheel com o extra, conforme a versão construída. O componente usa `sounddevice`/PortAudio em um subprocesso; a janela não precisa importar as dependências de síntese. A API de buffers utilizada é documentada em [sounddevice RawOutputStream](https://python-sounddevice.readthedocs.io/en/latest/api/raw-streams.html).

- Suporta **WAV PCM de 16 bits**, com a taxa e quantidade de canais do arquivo. Para revisão interna, gere uma saída WAV.
- Oferece reproduzir, pausar, parar e buscar por tempo. A leitura é feita em blocos, sem carregar toda a narração em memória.
- MP3, WAV com outra precisão ou ausência de dispositivo produzem uma mensagem; **Player do sistema** continua disponível como alternativa.
- Abrir outro áudio encerra o player anterior. Fechar a aplicação encerra seu processo de reprodução.
- A posição representa os frames entregues ao dispositivo, sujeita ao buffer/latência da saída; não é uma medição de sincronização audiovisual.

A E2 foi testada automaticamente com um stream simulado. O sounddevice 0.5.6 foi instalado em ambiente isolado e importado; a sondagem não encontrou saídas de áudio acessíveis nesta execução. **Nenhum áudio foi reproduzido para validação auditiva**. A reprodução física, escolha do dispositivo do sistema e comportamento de pausa/busca precisam de ensaio em macOS e Windows.

## Avisos e navegação

Use **Métricas** para examinar os segmentos de uma tomada concluída. Os avisos aparecem na situação e nos detalhes do segmento. Dê dois cliques na linha para abrir o WAV final no início desse segmento; sem WAV final, a interface tenta o WAV individual.

Os tempos são os limites dos segmentos, não a localização exata de cada amostra saturada. Os avisos acústicos existentes não detectam todos os defeitos e não medem semelhança da voz, naturalidade ou sotaque. A revisão por audição continua necessária.

## Arquivos e persistência

Os projetos ficam em `local/projetos/`, sob a raiz de dados da aplicação ou `TTSBR_HOME`, fora do Git. O documento principal usa o contrato `ttsbr.projeto` v1; a configuração `_estudio` tem versão interna própria.

| Arquivo/pasta | Função |
|---|---|
| `projeto.json` | Autoridade do roteiro original, configurações e histórico |
| `projeto.backup.json` | Versão salva anterior |
| `projeto.rascunho.json` | Roteiro e ajustes não salvos, após um segundo sem alterações |
| `indice.sqlite3` | Índice e coordenação de gravação; não é uma segunda cópia do roteiro |
| `cache.segmentos/` | Cache compartilhado entre execuções do projeto |
| `tomadas/` | Resultados e snapshots de segmentos por execução |

Uma revisão numérica impede que duas sessões sobrescrevam silenciosamente o mesmo projeto: se outra sessão salvar, reabra antes de salvar suas alterações. A publicação do JSON é atômica; uma falha antes da publicação preserva o documento anterior. O backup anterior é atualizado antes de publicar a próxima versão.

Os caminhos conhecidos de arquivos são armazenados relativamente à pasta do projeto e resolvidos ao reabrir. Referências externas e perfis da biblioteca não são incorporados automaticamente ao projeto. Mover apenas o JSON não torna o projeto portátil. O pacote ZIP e uma exportação com referências embutidas continuam fora desta entrega.

O glossário efetivo é capturado no projeto, inclusive mapas por idioma. Reabrir e gerar usa esse snapshot; alterações posteriores em glossários externos não devem mudar silenciosamente o resultado. Selecionar outro arquivo de glossário nos ajustes recaptura o glossário ao salvar. As referências de personagens/tons continuam relativas à origem do roteiro, quando ela está definida.

## Recuperação e referências ausentes

Se o documento principal estiver corrompido, **Abrir projeto…** oferece recuperar o backup anterior. Uma cópia do arquivo corrompido é preservada antes da recuperação. Documentos com versão futura são recusados; para usar um backup anterior, restaure-o em outra pasta, sem regravar o formato futuro.

Ao reabrir, um rascunho encontrado pode ser recuperado mediante confirmação; o roteiro salvo não muda até salvar. A revisão de origem do rascunho é mostrada para permitir avaliar sua atualidade. A gravação automática tem uma janela de até um segundo; ela não substitui salvar deliberadamente.

Se um perfil ou arquivo de referência estiver ausente, o projeto ainda pode ser aberto. A geração com aquele perfil é bloqueada. Restaure o backup da biblioteca, selecione outro perfil pela **Biblioteca de vozes…**, ou escolha manualmente outra referência e salve. Salvar atualiza os vínculos da biblioteca; um perfil associado a projeto não pode ser removido pela E1.

Os vínculos são registrados antes da publicação do JSON para evitar que uma falha deixe uma voz em uso sem proteção. Uma falha abrupta pode deixar vínculo conservador excedente; não apague o banco manualmente para contornar isso. A [E3](FILA_TAREFAS.md) acrescentou supervisão, reconciliação dos vínculos da fila e reparação dos vínculos ao salvar novamente um projeto.

Para backup completo, feche a aplicação e copie a pasta do projeto e a biblioteca de vozes usando o backup da E1. Não copie somente um banco aberto. As pastas contêm roteiro, referências, caminhos locais e áudios privados; não publique seus manifestos ou projetos sem revisão.

## Uso técnico

O fluxo avulso existente permanece disponível. A CLI também aceita:

```bash
python tts.py local/roteiro.txt --revisao-segmentos local/revisao.json --cache-segmentos local/cache.segmentos --saida saida/tomada --wav
```

O documento de revisão é produzido pelo projeto e deve corresponder exatamente ao plano conferido. Não é uma edição do manifesto de áudio concluído. `--cache-segmentos` escolhe uma pasta compartilhada; fora do gerenciamento por projetos, cabe ao chamador separar saídas e preservar históricos.

## Validação

A suíte desta entrega cobre projetos, backup/corrupção, falha de gravação, rascunho, conflito entre sessões, vínculos e referência ausente/religada, versões futuras, reconciliação com frases repetidas, bloqueio de revisão obsoleta, glossário congelado no worker e síntese simulada com regeneração seletiva, cache, preservação de tomadas e atualização de legendas. O transporte PCM é exercitado com stream simulado, incluindo pausa, busca, EOF e falha de dispositivo.

Esses testes não aprovam a GUI no desktop nem substituem inferência com XTTS real, audição, teste longo com player físico ou validação Windows. As evidências serão ampliadas antes da promoção 1.1.0.

Em 07/11/2026: **133 testes aprovados** no macOS arm64/Python 3.12.14 — 113 anteriores e 20 novos de E2. Nenhuma inferência real foi necessária nesses testes. O ensaio de instalação de sounddevice 0.5.6 foi isolado e não alterou os ambientes pessoais.

Wheel e sdist foram construídos pela cópia pública e backend setuptools. O wheel instalado em ambiente isolado criou e reabriu um projeto fora do checkout sem importar Torch. Seu inventário inclui módulos e documentação da E2 e não inclui gravações ou banco privado.
