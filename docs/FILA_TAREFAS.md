# Fila persistente e supervisão — E3

[README](../README.md) · [Projetos e revisão](PROJETOS_REVISAO.md) · [Roadmap](ROADMAP_0.9.0.md)

A E3 acrescenta uma fila local SQLite, um coordenador único por fila e um guardião independente por tarefa. GUI e API usam a mesma fila quando compartilham a raiz de dados (`TTSBR_HOME`). O coordenador e o guardião não carregam o XTTS: o processamento continua no worker com o Python selecionado.

## Usar pela interface

O menu **Fila de tarefas…** mostra tarefas, estados, tentativas e mensagens de erro. Ele pode ser aberto enquanto a janela principal aguarda uma geração.

1. Abra **Fila de tarefas…** e clique **Adicionar projeto…**.
2. Escolha um projeto salvo e já conferido. A fila captura o roteiro, configurações, glossário e referências daquele momento.
3. Repita para outros projetos. As tarefas são executadas em sequência, na ordem de envio.
4. Use **Interromper** para parar uma tarefa de síntese entre segmentos. A tarefa aguardando pode ser interrompida antes de iniciar.
5. Use **Cancelar à força** quando precisar encerrar o worker e seus filhos. O estado final só é registrado depois da confirmação de encerramento.
6. Use **Retomar** em tarefa interrompida, cancelada ou com falha. O mesmo snapshot e destino são reutilizados; o cache existente é verificado.

Os limites mostrados na janela são aplicados às **novas tarefas adicionadas por ela**. São independentes por etapa. Não alteram tarefas já enviadas. Para experimentar outro orçamento após um timeout, enfileire novamente o projeto com novos limites; o cache do projeto permite reaproveitar falas válidas.

As ações de análise, geração, amostra e validação da janela principal também passam pela fila. Ao fechar a janela durante uma tarefa, é possível aguardar uma interrupção segura ou manter o trabalho em segundo plano. Fechar só a janela da fila não cancela tarefas.

Ao reabrir o aplicativo, consulte a fila para ver os estados persistidos. **Iniciar fila** solicita o coordenador caso ele tenha encerrado. Um coordenador ocioso encerra após cerca de dois segundos; um guardião ativo continua cuidando de sua tarefa mesmo se o coordenador cair.

## Estados e retomada

| Estado | Significado |
|---|---|
| `aguardando` | Snapshot persistido e saída reservada; worker ainda não iniciado |
| `executando` | Tentativa reclamada pelo coordenador, sob controle do guardião |
| `interrupcao_solicitada` | Interrupção ou cancelamento solicitado; recurso ainda pode estar ocupado |
| `interrompida` | Interrupção segura ou recuperação de execução sem confirmação final |
| `concluida` | Worker encerrou e recibo/arquivos foram verificados |
| `falha` | Erro, timeout, encerramento anormal ou conclusão não comprovada |
| `cancelada` | Cancelamento antes de iniciar ou encerramento forçado confirmado |

Retomar não edita o pedido original. Cada tentativa recebe outro diretório de controle, outra flag de interrupção e outro recibo. Depois da primeira tentativa, `refazer` e `refazer_segmentos` são desativados na tentativa de retomada para preservar o trabalho já concluído; os parâmetros de fala e as correções continuam os capturados.

O cache valida os WAVs e seus hashes. Segmentos íntegros são reutilizados; ausentes ou corrompidos são gerados novamente. Validação e métricas são reexecutadas como tarefas completas; elas não possuem retomada incremental do ASR nesta entrega.

Uma saída já reservada por outra tarefa aguardando/executando é recusada. Dois processos independentes também não podem gravar simultaneamente na mesma saída ou cache: há travas de sistema operacional compartilhadas entre fila e CLI avulsa.

## Captura imutável

Antes de publicar a tarefa, a fila grava cópias privadas do texto, das referências de voz, do documento de correções, da trilha e, quando aplicável, do manifesto/segmentos a validar. O glossário efetivo é guardado no pedido. Cada arquivo capturado recebe hash SHA-256.

Referências de personagens, tons e tags de áudio são resolvidas para as cópias por um contexto do worker; as tags originais não precisam ser reescritas, preservando a identidade do plano conferido. Um perfil de voz é conferido e protegido por vínculo enquanto a tarefa estiver ativa. A fila utiliza a cópia capturada da referência, sem depender da permanência do arquivo externo.

Editar o projeto, o texto ou o glossário externo depois de enviar uma tarefa não muda seu snapshot. Em projeto, a tomada registra o ID da tarefa e a revisão de origem; os resultados são anexados ao histórico atual sem substituir seu roteiro. A GUI evita aplicar um plano antigo sobre um projeto cujo conteúdo foi alterado em outra sessão.

O snapshot não congela o código Python, o ambiente de dependências ou os pesos do modelo. O executável Python selecionado precisa continuar disponível. A identidade completa de motores e pesos será tratada na E4; não há promessa de reprodução bit a bit.

## Tempo por etapa

Valores padrão, em segundos:

| Etapa | Limite |
|---|---:|
| Inicialização/importações | 600 |
| Carregamento do modelo | 600 |
| Síntese de um segmento | 600 |
| Montagem/exportação | 600 |
| Validação | 900 |
| Registro da tomada no projeto | 300 |

Um segmento concluído renova o orçamento da síntese. Mensagens de log comuns não renovam o prazo. O limite não é uma duração máxima de toda a narração: várias falas podem ser processadas sequencialmente, cada uma com seu orçamento.

Esses valores são pontos de partida, não garantias de desempenho. Uma CPU lenta pode precisar de orçamento maior. Após timeout, o guardião encerra o grupo de processos antes de permitir outra execução. Caso não consiga confirmar a liberação, conserva o recurso ocupado e aguarda; não inicia outro modelo por cima de um worker incerto.

## Guardião e recuperação

O coordenador usa uma trava do SO para impedir coordenação duplicada. O guardião de cada tarefa mantém outra trava durante a execução. No POSIX, ela é herdada pelo worker; uma queda do coordenador não libera o recurso enquanto a inferência continua. O guardião permanece independente para observar o banco, atender cancelamentos e aplicar timeout.

No macOS/POSIX, os processos são encerrados por grupo, com TERM e depois KILL quando necessário. No Windows, o código usa Job Object com kill-on-close, vincula o worker antes de liberar sua execução e consulta processos ativos antes de concluir o encerramento. **A implementação Windows ainda precisa ser exercitada numa máquina real; não é declarada aprovada.**

A fila não mata um PID antigo lido de um arquivo ao reiniciar. Quando o recurso fica livre, examina tarefas que permaneceram em execução: um recibo válido permite reconciliar a conclusão; sem confirmação, a tarefa vira interrompida e exige retomada explícita. Uma queda adicional do próprio guardião pode exigir intervenção local se um worker continuar retendo o recurso; a fila prioriza bloquear uma nova inferência a liberar sem confirmação.

Arquivos de trava podem continuar no disco depois do processo terminar. A existência do arquivo não significa que o recurso está ocupado. Não remova arquivos de trava para tentar destravar um processo ativo: isso pode permitir acessos concorrentes ao mesmo recurso.

## Confirmação de conclusão

Código de saída zero sozinho não aprova uma tarefa. O worker publica um recibo atômico contendo a tentativa, hash do pedido, eventos finais e hashes dos resultados. O guardião verifica:

- Manifesto concluído e arquivos efetivamente presentes para síntese.
- Registro da tomada no projeto, quando a tarefa é de projeto.
- Relatório produzido para métricas/validação ou plano produzido para análise.
- Integridade dos arquivos declarados no recibo.
- Saída do worker e encerramento dos processos filhos.

Os arquivos de saída são publicados atomicamente por arquivo e o manifesto é concluído por último. Isso não é uma transação de filesystem sobre todos os formatos de uma vez. Uma falha pode deixar artefatos parciais, mas não uma tarefa aprovada; tomadas anteriores têm seus próprios snapshots e são preservadas.

A reconciliação dos vínculos remove vínculos órfãos desta fila sem interferir em filas com outra raiz. Salvar um projeto reconcilia os vínculos daquele projeto com seu documento atual, corrigindo vínculos conservadores deixados por uma gravação que falhou. Apagar diretórios de projetos manualmente não é um mecanismo de remoção de vínculos.

## API local

`POST /v1/audio/speech` continua síncrono: pode aguardar outras tarefas e responde com o arquivo após conclusão comprovada. Ajuste o timeout do cliente ao tamanho da narração e da fila. Desconectar o cliente HTTP não cancela automaticamente o trabalho; consulte a fila para interromper ou cancelar.

Cada pedido HTTP tem sua própria saída e pode compartilhar o cache de fala da API. GUI e API compartilham o coordenador se usam a mesma raiz de dados/fila. Uma configuração explícita de outra raiz cria outra fila; não há coordenação global de GPU entre raízes distintas.

A CLI avulsa `tts.py` continua independente da ordem da fila, mas detecta colisões de saída/cache. Para obter execução serial, utilize a GUI, a API ou envie pedidos à fila. A E3 não acrescenta streaming, autenticação nem uso multiusuário; mantenha a API no endereço local padrão.

## Linha de comando e integração Python

```bash
python tarefas.py listar
python tarefas.py rodar
python tarefas.py interromper ID_DA_TAREFA
python tarefas.py cancelar ID_DA_TAREFA
python tarefas.py retomar ID_DA_TAREFA
```

Substitua `ID_DA_TAREFA` pelo ID exibido na fila. O parâmetro global `--raiz PASTA` seleciona uma fila alternativa. Depois de instalar o pacote atualizado, `ttsbr-fila` oferece os mesmos comandos.

Para ferramentas que já produzem pedidos da GUI:

```bash
python tarefas.py adicionar local/pedido.json --python .venv/bin/python
```

No Windows, use o executável de síntese correspondente, por exemplo `.venv\Scripts\python.exe`. O pedido deve seguir o formato gerado por `gui_core.salvar_pedido`; a fila captura os arquivos antes de executá-lo. Não use um JSON de terceiros como uma promessa de segurança de execução.

Na integração Python, `Fila.enfileirar(python, pedido, limites={"sintese": 900})` permite personalizar os prazos conhecidos. Os valores devem ser números positivos e finitos. `Fila.iniciar_coordenador()` solicita execução em segundo plano. As ferramentas da fila são locais e suas listagens contêm dados privados.

## Persistência, limites e backup

A pasta padrão é `local/fila/`, sob a raiz de dados da aplicação. Ela contém `fila.sqlite3`, snapshots em `tarefas/ID/`, controles por tentativa e arquivos de trava. Pedidos auxiliares e dados de execução ficam em pastas locais ignoradas pelo Git.

São mantidos até mil eventos recentes por tarefa e até duzentos registros recentes de tarefas concluídas/canceladas. Logs individuais são limitados a 16 mil caracteres. Tarefas aguardando, interrompidas ou com falha não são descartadas automaticamente. A poda de metadados não apaga áudios, projetos ou snapshots do disco; faça manutenção de armazenamento com a aplicação parada.

O banco tem versão própria e recusa versões futuras ou bancos sem esquema reconhecido. Não copia nem migra tarefas de formatos desconhecidos silenciosamente. O estado da fila é separado das versões do aplicativo e dos documentos de projeto.

Para backup manual consistente, interrompa as tarefas, aguarde os processos e o coordenador encerrarem, e preserve juntos a pasta da fila, os projetos e o backup da biblioteca de vozes. Áudios, transcrições, roteiros, paths de execução e relatórios são privados e não devem ser enviados ao Git. SQLite e as travas desta versão são destinados a disco local, não a uma fila distribuída em pasta de rede.

## Validação desta entrega

Os testes usam subprocessos reais e workers sintéticos, sem baixar modelos ou usar gravações pessoais. Exercitam fila serial de três tarefas, coordenadores concorrentes, captura de referências, cancelamento, timeout, encerramento de filhos, queda do coordenador e cancelamento posterior, recuperação de estados, verificação de recibos, falha de disco, versões futuras, retenção, vínculos, colisão com CLI, cliente de GUI sem display e API HTTP real compartilhando a fila.

As rotas HTTP e os processos são reais; a geração dos áudios nesses testes é simulada. A suíte anterior conserva seus testes com FFmpeg real. A validação de sinais de processo no macOS precisou de execução fora do sandbox, que bloqueava sinais a grupos de processos filhos.

A janela no desktop, a contenção de processos Windows, uma inferência longa real, o comportamento em suspensão/reinício do sistema e a audição ainda precisam de avaliação. Esses limites permanecem bloqueadores da promoção para 1.1.0.

Rodada de 07/11/2026, macOS arm64/Python 3.12.14: **160 testes aprovados**, incluindo os 133 anteriores e 27 novos da fila/supervisão. Inicialização simultânea de bancos novos também foi exercitada. Não houve inferência com modelo real nessa rodada.

Wheel e sdist foram construídos por cópia pública e backend setuptools. O comando `ttsbr-fila` instalado foi exercitado fora do checkout em um ambiente separado, sem dependências de síntese; os módulos do coordenador/guardião foram importados sem Torch ou TTS. O inventário do pacote foi conferido para excluir gravações e bancos privados. Isso não substitui uma instalação completa de síntese ou os testes de desktop.
