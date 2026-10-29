# 🗺️ Roadmap de Próximas Melhorias — TTSBR

Este documento consolida as sugestões e prioridades planejadas para as próximas iterações do TTSBR, organizadas por impacto e área do pipeline.

---

## 1. 🗣️ Fonética PT-BR e Naturalidade de Prosódia
- [ ] **Expansão do dicionário de IA e tecnologia**:
  - Adicionar termos frequentes com guia de pronúncia: *fine-tuning*, *embeddings*, *pipeline*, *benchmark*, *framework*, *prompt*, *dataset*, *tokenization*, *loss function*, *inference*.
- [ ] **Guia de tonicidade automática para paroxítonas suscetíveis a oxítonas**:
  - Mapear e tratar palavras paroxítonas em que modelos multilíngues (XTTS v2) tendem a deslizar a tonicidade para a última sílaba, aplicando acentuação gráfica auxiliar invisível na camada de fala (a exemplo do que foi implementado com sucesso para `\banos\b` → `ânos`).
- [ ] **Normalização de grandezas e faixas compostas**:
  - Leitura natural de unidades com barra ou expoentes (`km/h`, `MB/s`, `m²`, `°C`).
  - Reconhecimento de intervalos monetários e numéricos (ex.: `R$ 10 a R$ 20`, `5 a 10 dias`).

---

## 2. 🖥️ Interface Gráfica Local (GUI)
- [ ] **Player integrado com forma de onda (waveform)**:
  - Permitir a reprodução do áudio final e de cada segmento individual diretamente pela janela do aplicativo (sem depender de players externos como QuickTime).
- [ ] **Edição rápida e regeração por segmento**:
  - Botão de ação rápida na tabela de segmentos para editar o texto corrigido e acionar `--refazer-segmentos` em 1 clique.
- [ ] **Catálogo visual de vozes e locutores**:
  - Menu seletor com as vozes de estúdio cadastradas (`Luis Moray`, `Sofia Hellen`, `Tammie Ema`, etc.) e botão de prévia (*preview*) auditiva.

---

## 3. 🎙️ Recursos de Estúdio e Áudio Avançado
- [ ] **Biblioteca padrão de vozes clonadas (`vozes/`)**:
  - Fornecer amostras curtas pré-higienizadas (com corte de ruído e normalização LUFS) para estilos específicos: narração neutra, leitura de notícias e podcasts informais.
- [ ] **Expansão das tags de estilo e emoção**:
  - Suporte a novas variações de tom como `[tom:noticia]`, `[tom:narracao]`, `[tom:entusiasmado]`.
- [ ] **Capítulos e metadados ID3**:
  - Inserção automática de marcadores de capítulo no arquivo MP3 com base nos blocos e parágrafos do roteiro, facilitando a navegação em audiolivros e podcasts longos.

---

## 4. ⚡ Integração e Automação (API e Streaming)
- [ ] **Streaming de áudio em tempo real**:
  - Habilitar resposta em *chunked transfer encoding* no servidor local compatível com OpenAI (`servidor_api.py`), permitindo reprodução instantânea com baixa latência em assistentes virtuais e chatbots.
