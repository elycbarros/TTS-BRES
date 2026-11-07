# TTSBR 0.9.0 Preview → 1.1.0

Plano de evolução • 07/11/2026 • Estado: bases E0, E1, E2 e E3 implementadas e testadas automaticamente no macOS; validação visual/auditiva e demais entregas pendentes.

Implementação e evidências: [Base E0 do preview](PREVIEW_0.9.0.md) , [Biblioteca E1](BIBLIOTECA_VOZES.md) , [Projetos E2](PROJETOS_REVISAO.md) e [Fila E3](FILA_TAREFAS.md). A validação Windows e as integrações futuras continuam pendentes.

## Objetivo e sequência de versões

Transformar o TTSBR em um estúdio pessoal de narração PT-BR/ES, com biblioteca de vozes, projetos recuperáveis, revisão de áudio e comparação controlada de motores. A versão **0.9.0 é um preview**. Após cumprir os critérios de validação deste plano, a entrega final será **1.1.0**.

O pacote atual declara `1.0.0`; este documento não altera essa versão. A numeração 0.9.0 é uma convenção deliberada do projeto para o preview, embora ordene abaixo de 1.0.0 para instaladores Python. Ao preparar a entrega, documentar instalação em ambiente separado e seleção explícita da versão, sem depender de `pip install --upgrade` para selecionar o preview. Não sobrescrever uma tag ou release existente. A promoção para 1.1.0 será um novo pacote e uma nova tag, com resultados de teste associados ao commit efetivamente publicado.

Separar versão do aplicativo, versão de esquema de projeto e versão do pipeline/cache. A promoção não deve tornar projetos do preview ilegíveis. Antes de migrar dados, criar backup e testar migração e recuperação. A compatibilidade entre resultados de motores diferentes será explícita, sem prometer igualdade bit a bit.

## Base examinada e limites da análise

- TTSBR: commit `01f470290270636edabae6941ee194428d0ec7f2`; examinados `tts.py`, `audio_persistente.py`, `gui_core.py`, `gui_worker.py`, `servidor_api.py`, `processamento_audio.py`, `vozes.py`, empacotamento e documentação.
- Última suíte registrada: 86 testes aprovados em 01/11/2026. Esse resultado é histórico, não uma execução da futura 0.9.0. Não houve nova inferência, instalação de motores ou ensaio de GUI nesta análise.
- VoiceStudio: árvore e arquivos consultados na revisão `aaabec19e6a36f857d724f56173d13c92caa2b27`. Leitura direcionada de arquitetura, qualidade, motores, projetos, filas, testes e instalação. Não é uma auditoria exaustiva de todos os arquivos nem validação das alegações de desempenho.
- Os números de qualidade e velocidade de outros projetos não serão apresentados como resultados do TTSBR. A página de benchmarks do VoiceStudio consultada não tinha linhas verificadas na tabela agregada; portanto não sustenta um ranking de velocidade.

## O que já existe e deve ser aproveitado

| Base atual | Implicação para o planejamento |
|---|---|
| Normalização PT/ES, glossários e léxico separados | Preservar cobertura e permitir políticas de preparação por motor. |
| Segmentos com hash, WAV verificado e JSON atômico | Estender identidade do cache e do manifesto, sem reconstruir a retomada do zero. |
| GUI com worker em subprocesso e eventos | Acrescentar supervisão e estado persistente; a GUI já tem isolamento básico. |
| Interrupção cooperativa entre segmentos | Diferenciar pausa segura de cancelamento forçado durante inferência. |
| Regeneração seletiva | Acrescentar edição com IDs estáveis, histórico e invalidação correta. |
| API local com bloqueio de síntese | Na base original não havia fila; a E3 acrescentou fila persistente. Autenticação permanece fora do escopo. |
| Montagem incremental em disco | Manter uso de memória limitado em narrativas longas. |
| Cache PCM mono, 16 bits, 24 kHz | Motores com outras saídas precisam de adaptação explícita. Exportar em 24/32 bits após esse cache não recupera precisão perdida. |
| Parâmetro `modelo_precarregado` no pipeline | Ponto possível para extrair o adaptador; não equivale ainda a um contrato completo de motores. |
| Pacote e script de construção pública | Incluir novos módulos, documentos e exemplos na lista explícita; impedir entrada de dados pessoais. |

## Matriz de aproveitamento do VoiceStudio

As decisões abaixo são propostas para o TTSBR; a existência de uma referência externa não comprova adequação ao nosso ambiente.

| Área observada | Adaptação proposta | Decisão e esforço relativo |
|---|---|---|
| Perfis de voz reutilizáveis | Catálogo privado com amostra, transcrição, idioma, estilo e prévia | Núcleo do preview; médio |
| Biblioteca de projetos e tomadas | Projeto versionado com roteiro, elenco, glossário, configurações e resultados | Núcleo; médio/alto |
| Verificação de sinal com avisos localizados | Mostrar silêncio, clipping, volume e trechos suspeitos; navegar ao tempo do aviso | Núcleo; médio |
| Controles simples e avançados separados | Presets de uso, ajuda contextual e parâmetros compatíveis com o motor | Núcleo; médio |
| Adaptadores de motores e capacidades | XTTS como primeira implementação; outro motor por ambiente isolado | Contrato no núcleo; segundo motor experimental; alto |
| Subprocesso supervisionado | Timeout, encerramento confirmado e recuperação após travamento | Núcleo; médio/alto |
| Um motor residente por vez | Limitar recursos e descarregar após ociosidade quando houver reutilização do worker | Aplicar conforme o ciclo de vida; médio |
| Fila e metadados duráveis | Uma síntese ativa; fila recuperável e estados explícitos | Núcleo; alto |
| Projetos portáveis com hashes | Exportação com lista de arquivos e escolha explícita de incluir referências privadas | Depois de projetos locais; médio/alto |
| Catálogo de modelos e licenças | Diagnóstico, revisão de pesos, tamanho em disco e download solicitado pelo usuário | Versão mínima no núcleo; gerenciador amplo posterior |
| Transcrição de referência | Campo editável e ASR opcional, sem download implícito | Experimental; médio |
| Medições repetíveis | Benchmark frio/quente, RTF, memória e avaliação auditiva cega | Obrigatório para decidir novo motor; médio |
| Instalação desktop e runtimes | Primeira execução orientada, verificação de FFmpeg/Tkinter e dados fora da instalação | Núcleo via Python; instalador independente posterior |
| Dublagem, diarização, tradução e separação musical | Nova cadeia de processamento e novos modelos | Fora de 0.9.0/1.1.0 |
| Ditado global, aplicativo móvel e sincronização | Ampliação de produto e permissões | Fora de 0.9.0/1.1.0 |
| MCP, pastas monitoradas e receitas | Automatizar somente após estabilizar contrato de tarefas | Backlog posterior |
| Marca d'água de áudio | Avaliar algoritmo, resistência, custo e efeitos sobre áudio | Pesquisa posterior; não alegar proteção antifraude |
| Dezenas de motores, ROCm e GGUF/Vulkan | Grande matriz de manutenção e distribuição | Pesquisa posterior; nenhuma compatibilidade presumida |

## Licenças e estratégia de implementação

O aplicativo VoiceStudio declara AGPL-3.0-only; o código do TTSBR é MIT. Implementar as funcionalidades com código próprio a partir dos requisitos. Qualquer incorporação de código externo requer identificar arquivo, licença, avisos e efeitos sobre a distribuição antes de copiar. A AGPL permite usos sob suas condições; este plano não a trata como uma proibição geral nem como uma licença MIT.

O aviso do VoiceStudio distingue o código OmniVoice Apache-2.0 dos pesos identificados como CC-BY-NC e de termos adicionais do tokenizador. Para cada experimento registrar origem e revisão do código, pesos, tokenizador, dependências e condições de uso/redistribuição. Não apresentar uso comercial como autorizado apenas pela licença do aplicativo. Manter o novo motor opcional e separado do ambiente XTTS.

Perfis, vozes e transcrições ficam em dados locais ignorados pelo Git. Uma indicação de autorização preenchida pelo usuário é uma declaração, não uma verificação de identidade. Relatórios públicos só incluem dados agregados revisados; excluir gravações, transcrições privadas, caminhos absolutos, identificadores da máquina e credenciais.

## Arquitetura alvo

Fluxo proposto: **GUI/CLI/API → pedido validado → projeto/fila → worker supervisionado → adaptador → cache → montagem → revisão/exportação**.

- `motores/`: contrato e adaptador XTTS; adaptador experimental em ambiente separado. Capacidades: idiomas, clonagem, transcrição de referência, estilos, seed, taxa e formato nativos. Recusar opções incompatíveis com mensagem clara; não ignorá-las silenciosamente.
- `biblioteca_vozes.py`: perfis versionados, IDs estáveis, hashes das referências e relações com os projetos.
- `projetos.py`: roteiro original, preparação de fala, elenco, glossário, configurações, histórico e referências relativas. Nunca transformar texto normalizado no roteiro original.
- `tarefas.py`: fila serial, estados persistidos e ligação com os manifestos existentes. SQLite é candidato para fila/biblioteca; decidir na primeira entrega. Evitar persistir os mesmos estados em fontes concorrentes sem autoridade definida.
- `supervisor.py`: iniciar, observar e encerrar workers; confirmação de término antes de liberar o recurso ou iniciar substituto. Arquivo temporário incompleto não vira resultado concluído.
- `reproducao.py`: interface de player com implementação multiplataforma selecionada por prova de conceito. Nenhuma dependência de player é escolhida apenas por aparência.
- `benchmark_motores.py`: execução isolada e resultados agregados. Os nomes de módulos são propostas, não arquivos já existentes.

O adaptador retorna áudio, taxa, canais e formato reais. No preview, normalizar explicitamente para o PCM atual de 24 kHz/16 bits antes do cache, preservando opcionalmente o original como artefato separado. Registrar essa conversão no manifesto. Preservação integral de float/48 kHz exige evolução do cache/montador e fica condicionada a uma entrega própria; não oferecer botão de “maior qualidade” baseado apenas em reamostragem.

A chave de cache deverá identificar motor, revisão do modelo, parâmetros efetivos, política de preparação, seed quando suportada, referência e transcrição usadas. Ao mudar esquema, cache antigo continua legível ou é invalidado com mensagem; nunca reutilizar áudio de outro motor por coincidência de texto. A transformação de pontuação atual, criada para XTTS, deve ser medida antes de ser aplicada a outros motores.

## Entregas ordenadas

Os tamanhos P/M/G são comparações de esforço, não prazos. Nenhuma data de lançamento será prometida antes da primeira entrega.

### E0 — Contratos, diagnóstico e plano de migração (M, obrigatória)

**Depende de:** nenhuma.

- Congelar o estado inicial por commit e registrar versões de dependências efetivamente exercitadas.
- Criar diagnóstico local de Python, Tkinter, FFmpeg executável versus bibliotecas nativas, dispositivo e espaço disponível. Exportar somente campos públicos aprovados.
- Definir esquemas de perfil/projeto/tarefa e autoridade de cada estado; documentar backup, migração e recuperação.
- Definir matriz inicial macOS Apple Silicon/CPU e Windows x64/CPU; MPS e CUDA opcionais.
- Definir política de versionamento do preview 0.9.0 e promoção 1.1.0, incluindo instalação explícita e atualização.

**Testes/aceite:** suíte de base repetida; diagnóstico funciona com dependência ausente e sem carregar modelo; esquemas rejeitam versões desconhecidas; plano de instalação não toca no ambiente atual. Gerar checklist por plataforma.

### E1 — Biblioteca privada de vozes (M, obrigatória)

**Depende de:** E0.

- Importar WAV e formatos realmente decodificáveis no ambiente; mostrar duração, canais, taxa e avisos.
- Salvar nome, idioma, estilo, amostra original, transcrição revisável e anotação de autorização. Várias tomadas por pessoa com IDs distintos.
- Ouvir, selecionar, renomear e remover perfis com descrição do efeito nos arquivos e projetos que os usam.
- Qualidade da referência: silêncio, clipping e volume como avisos, sem prometer medir semelhança de voz. Limpeza opcional gera cópia e mantém o original.
- Perfis neutro/expressivo/calmo vinculam-se às amostras, sem prometer emoção que o motor não suporta.

**Testes/aceite:** cadastrar seis tomadas dos roteiros; reabrir sem perder vínculos; referência ausente, arquivo inválido, acentos e espaços tratados; alterar bytes invalida o cache; nenhum áudio ou transcrição privada em artefatos públicos. Audição humana para escolher referências.

### E2 — Projetos e revisão de segmentos (G, obrigatória)

**Depende de:** E0 e E1.

- Salvar/reabrir roteiro, elenco, glossário, configurações e manifesto relacionado; gravação atômica e recuperação de rascunho.
- Editar texto e regenerar trecho mantendo IDs estáveis e histórico de tomadas. Se mudar a segmentação, reconciliar IDs e invalidar trechos afetados explicitamente.
- Player integrado: reproduzir, pausar, parar e buscar; comparar duas tomadas. Forma de onda é segunda etapa se atrasar o player básico.
- Navegar a avisos acústicos com tempo; distinguir alerta de sinal de avaliação perceptiva.

**Testes/aceite:** salvar/reabrir sem mudança de roteiro; projeto com referência movida orienta religação; regeneração mantém trechos válidos e recalcula tempos e SRT/VTT; teste de interface real com teclado, escala de tela e player no macOS e Windows. Player não bloqueia a janela.

### E3 — Fila durável e supervisão (G, obrigatória)

**Depende de:** E0 e E2.

- Enfileirar projetos com snapshot imutável e diretório de saída próprio; uma síntese ativa por coordenador.
- Estados: aguardando, executando, interrupção solicitada, interrompida, concluída, falha e cancelada. Reinício não deve mostrar tarefa antiga como executando.
- Interrupção entre segmentos; encerramento forçado com confirmação e recuperação a partir do último segmento verificado.
- Limitar histórico/logs e impedir colisões de saída. GUI e API devem compartilhar o coordenador quando operarem sobre a mesma fila; processos CLI independentes precisam detectar colisões.
- Timeout configurável por etapa e orçamento compatível com CPU. Não copiar um timeout de GPU para todas as máquinas.

**Testes/aceite:** três tarefas seriadas; fechar/reabrir; falha de processo; cancelamento em fila e em execução; timeout de worker simulado; falha de disco; nenhuma tarefa marcada concluída antes de publicação atômica. No Windows confirmar encerramento dos filhos; não iniciar substituto enquanto o anterior ainda ocupa o recurso.

### E4 — Contrato de motores e comparação experimental (G, contrato obrigatório)

**Depende de:** E0 e E3; referências de E1.

- Extrair adaptador XTTS preservando CLI e manifesto. Testar capacidades e parâmetros efetivos com motor falso.
- Integrar um único candidato experimental, inicialmente OmniVoice, em ambiente isolado somente após verificar requisitos e licenças. Ausência ou reprovação do candidato não bloqueia a versão final com XTTS.
- Registrar identidade do modelo/cache e preparação por motor. Texto transcrito da referência sempre acompanha o áudio correspondente.
- Proibir downloads implícitos de ASR; mostrar recurso necessário e permitir transcrição manual.
- Medir carga fria, síntese quente, tempo total, memória, duração, RTF e falhas; seeds registradas quando o motor realmente as aplica.

**Testes/aceite:** XTTS sem regressão de contrato; troca de motor nunca reutiliza cache errado; saída nativa em outra taxa convertida explicitamente; worker ausente/erro recuperável; comparação PT/ES completa antes de habilitar candidato na GUI. Se inviável, entregar relatório com motivo e manter experimento desativado.

### E5 — Qualidade PT/ES, presets e exportação (M/G, obrigatória)

**Depende de:** E2 e contrato de E4.

- Expandir corpus de datas, siglas, valores, unidades (`km/h`, `MB/s`, `m²`, `°C`), intervalos, pontuação, diálogo e trechos longos.
- Corrigir regras de tonicidade somente com evidência e contexto; substituições globais podem piorar palavras ou idiomas.
- Presets “narração”, “amostra” e “revisão”, com ajustes avançados e restauração previsível de padrões.
- Medir loudness no arquivo final depois de trilha/LUFS; manter métricas de segmento separadas.
- Exportar capítulo por arquivo e metadados simples; capítulos embutidos/M4B podem ser adiados para proteger o núcleo.

**Testes/aceite:** normalização esperada por idioma; SRT/VTT monotônicos e alinhados; MP3/WAV reproduzíveis nos sistemas alvo; duração e níveis registrados; texto sem tags internas pronunciadas. Não usar WER como nota de naturalidade.

### E6 — Distribuição, dados e documentação do preview (M, obrigatória)

**Depende de:** E1–E5, com candidato opcional.

- Construção limpa de wheel/sdist com todos os novos módulos e documentos, sem diretórios privados.
- Incluir os roteiros públicos de captação no pacote: hoje estão no repositório, mas fora da lista de `data-files`.
- Instalação guiada por documentação e diagnóstico; continuar com Python/Tkinter até uma prova de conceito justificar instalador independente.
- Exportação/importação de projeto: primeira versão só com dados necessários e referências opcionais mediante revisão; validar hashes, extensões, tamanho, caminhos relativos e versões. Se atrasar, manter backup local como núcleo e adiar ZIP portável.
- Atualizar README, SOBRE, GUI, REFERENCIA, ARQUITETURA, ESTABILIZACAO e CHANGELOG com resultados reais e limites.

**Testes/aceite:** instalar wheel fora do checkout; executar três comandos; dados graváveis separados; instalação em caminho com acentos/espaços; construção em volume externo sem AppleDouble; inspeção da lista de arquivos do pacote. Migração preview → 1.1.0 em cópia descartável.

## Protocolo de comparação de voz

1. Utilizar somente referências autorizadas. Guardar gravações em pasta privada, separada dos resultados públicos.
2. Fixar corpus público: mínimo inicial de 12 casos por idioma, cobrindo frases curtas, perguntas, unidades, números, nomes, termos técnicos e diálogo, além de uma narração de pelo menos dez minutos. O texto de teste não deve repetir integralmente a referência.
3. Comparar XTTS e candidato com o mesmo roteiro, mesmas referências e preparação documentada. Medir condição original e limpeza opcional separadamente; evitar processamento final diferente que esconda defeitos.
4. Executar ao menos três repetições das condições principais. Separar carga fria de síntese quente e relatar mediana e faixa. Cache de áudio desativado para medir inferência; medir retomada/cache em ensaio próprio.
5. Registrar versão/revisão, dispositivo solicitado e efetivo, parâmetros, duração e falhas. RTF = tempo de síntese / duração do áudio. Memória de subprocesso precisa ser medida no processo certo; GPU e memória unificada não são equivalentes.
6. ASR fixo e normalização de comparação documentada; apresentar WER/CER por idioma e caso, sem misturar idiomas em uma única nota que esconda falhas.
7. Audição com rótulos A/B ocultando o motor, mesma referência para ouvir e ordem alternada. Usuário avalia inteligibilidade, naturalidade, sotaque e semelhança em escala 1–5, registrando palavras omitidas, repetidas e cortes. Uma pessoa avaliando sustenta uma decisão pessoal, não uma alegação geral de superioridade.
8. Aprovação proposta do candidato: completar todos os casos obrigatórios sem travamento/áudio vazio; não piorar a mediana de WER em mais de dois pontos percentuais; ter ganho documentado em pelo menos um objetivo (qualidade percebida, tempo ou memória). Divergências e falhas críticas exigem revisão, mesmo com médias boas. Esses limiares são critérios propostos, não resultados obtidos.

## Matriz de testes e responsabilidades

| Camada | Execução automatizável | Evidência adicional necessária |
|---|---|---|
| Unidade e contratos | Normalização, capacidades, esquemas, cache e estados com fixtures públicas | Revisão de casos linguísticos reais |
| Integração sem modelos | Worker falso, FFmpeg real, cancelamento, falhas e retomada | Nenhuma voz privada necessária |
| Integração real | XTTS PT/ES, cache, formatos, legendas, API e candidato opcional | Downloads e termos verificados; máquina com recursos suficientes |
| GUI macOS | Testes de integração sem display e roteiro de smoke test | Janela real, áudio, teclado, escala, suspensão e fechamento |
| Windows x64/CPU | CI de suíte/empacotamento, se configurada | Instalação limpa e uso da GUI/áudio em máquina real |
| MPS/CUDA | Smoke tests específicos quando hardware disponível | Marcar experimental ou não validado se faltar evidência |
| Qualidade percebida | Preparar comparação e métricas | Audição do usuário com referências autorizadas |
| Privacidade e distribuição | Inventário de pacote e exportação filtrada | Revisão dos relatórios antes de torná-los públicos |

É possível preparar código, testes, fixtures e CI sem as suas gravações. Fidelidade de clonagem depende das referências e da sua audição. CI Windows sem dispositivo de áudio não substitui uso real da janela/player. Nunca marcar uma etapa aprovada apenas porque os mocks passaram.

## Critérios para publicar 0.9.0 Preview

- [ ] E0 concluída e decisões de esquema/versionamento registradas.
- [ ] Fluxo importar voz → salvar projeto → gerar → ouvir → corrigir trecho → retomar utilizável no macOS.
- [ ] Nenhuma perda conhecida de roteiro ou publicação de dados privados; backup e recuperação demonstrados.
- [ ] Suíte de base e novos testes aprovados no commit do preview; resultados públicos agregados com data e ambiente.
- [ ] Limitações e problemas conhecidos apresentados, especialmente Windows, MPS e candidato opcional.
- [ ] Construção e instalação em ambiente separado verificadas; pacote identificado como preview.

## Critérios para promover a 1.1.0

- [ ] E0–E6 obrigatórias concluídas; recursos opcionais pendentes explicitamente desativados ou adiados.
- [ ] Matriz mínima macOS Apple Silicon/CPU e Windows x64/CPU aprovada em máquina real, com evidências.
- [ ] Audição PT/ES e de referências pessoais autorizadas concluída; defeitos bloqueadores resolvidos.
- [ ] Teste longo, interrupção, reinício, retomada, regeneração e fila sem corrupção ou sobrescrita indevida.
- [ ] Atualização de dados do preview para a final testada com backup e roteiro de recuperação.
- [ ] Wheel/sdist e documentos coerentes; nenhum dado pessoal incluído; licenças dos componentes usados registradas.
- [ ] Número 1.1.0 aplicado aos metadados e documentação da entrega; nova tag/release vinculada ao commit validado.
- [ ] Commit usa exclusivamente a identidade local do Git (`user.name` e `user.email`). Publicação e push seguem a autorização do usuário.

## Riscos e decisões pendentes

- **Escopo excessivo:** preservar voz/projeto/revisão/recuperação; adiar forma de onda avançada, ZIP e capítulos embutidos se necessário.
- **Dependências conflitantes:** novo motor em ambiente próprio; XTTS permanece funcional sem extras.
- **Memória e travamentos:** uma síntese por vez; timeout supervisionado, liberação confirmada e diagnóstico sem conteúdo privado.
- **Interface multiplataforma:** provar player em ambos os sistemas antes de comprometer uma biblioteca.
- **Migração:** backup e testes de ida; não exigir downgrade destrutivo para voltar ao aplicativo anterior.
- **Qualidade diferente entre idiomas:** resultados separados; uma melhora em PT não aprova automaticamente ES.
- **Licenças e modelos:** não distribuir pesos nem declarar direitos que a evidência não sustenta.
- **Versionamento incomum:** deixar claro que 0.9.0 é preview da linha final 1.1.0, apesar de o pacote atual usar 1.0.0.

## Fontes externas consultadas

Links fixados na revisão examinada para tornar as decisões rastreáveis. A documentação externa descreve o VoiceStudio e não certifica o TTSBR.

- [Avisos e escopo de licenças](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/LICENSE-NOTICE.md).
- [Critérios para integrar motores](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/docs/engine-acceptance.md).
- [Motor OmniVoice e referências](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/docs/engines/omnivoice.md).
- [Isolamento em subprocesso](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/docs/engines/omnivoice-subprocess.md).
- [Política de memória dos motores](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/backend/services/engine_memory.py).
- [Fila serial](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/backend/core/job_queue.py) e [persistência de metadados](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/backend/core/job_store.py). Metadados persistentes não implicam retomada automática de todo trabalho.
- [Projetos na interface](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/docs/electron-projects.md) e [formato de intercâmbio](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/backend/services/project_bundle.py).
- [Qualidade de áudio e comparações](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/docs/audio-quality.md) e [protocolo de benchmarks](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/docs/benchmarks.md).
- [Testes de recuperação de audiolivros](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/backend/tests/test_audiobook_resume_api.py).
- [Instalação Windows e limites de validação](https://github.com/debpalash/VoiceStudio/blob/aaabec19e6a36f857d724f56173d13c92caa2b27/docs/install/windows.md).
