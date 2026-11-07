# 🗺️ Roadmap de Próximas Melhorias — TTSBR

> **Plano da próxima entrega:** [Roadmap Técnico v1.2.0](ROADMAP_1.2.0.md) (ciclo anterior concluído: [0.9.0 Preview → 1.1.0](ROADMAP_0.9.0.md)). O plano detalha as etapas **M1 a M5**, módulos afetados, testes e critérios de lançamento da `1.2.0`.

Este documento consolida as sugestões e prioridades planejadas para as próximas iterações do TTSBR, organizadas por impacto e área do pipeline.

---

## 1. 🗣️ Fonética PT-BR e Naturalidade de Prosódia
- [x] **Modularização do léxico e expansão de IA e tecnologia** *(Entregue em `lexico.py`)*:
  - Dicionário desacoplado com vocabulário técnico de IA (*fine-tuning*, *embeddings*, *pipeline*, *benchmark*, *framework*, *prompt*, *dataset*, *tokenizer*, *dropout*, *backpropagation*, *autoencoder*).
  - Próximos termos a adicionar: *tokenization*, *loss function*, *inference*.
- [ ] **Guia de tonicidade automática para paroxítonas suscetíveis a oxítonas**:
  - Mapear e tratar palavras paroxítonas em que modelos multilíngues (XTTS v2) tendem a deslizar a tonicidade para a última sílaba, aplicando acentuação gráfica auxiliar invisível na camada de fala (a exemplo do que foi implementado com sucesso para `\banos\b` → `ânos`).
- [x] **Normalização de grandezas e faixas compostas** *(Entregue na E5)*:
  - Leitura natural de unidades com barra ou expoentes (`km/h`, `MB/s`, `m²`, `°C`), horários `12h30`, ordinais (`1º`, `2ª`, `1er`, `3er`), intervalos (`10-20`) e `€` posposto.

---

## 2. 🖥️ Interface Gráfica Local (GUI)

O player básico com pausa/busca foi implementado na E2; a forma de onda permanece planejada.
- [ ] **Player integrado com forma de onda (waveform)**:
  - Permitir a reprodução do áudio final e de cada segmento individual diretamente pela janela do aplicativo (sem depender de players externos como QuickTime).
- [x] **Edição rápida e regeração por segmento** *(E2 do preview)*:
  - Ações na tabela para editar a fala preparada e regerar o segmento, preservando o roteiro e as tomadas anteriores.
- [ ] **Catálogo visual de vozes e locutores**:
  - Menu seletor com as vozes de estúdio cadastradas (`Luis Moray`, `Sofia Hellen`, `Tammie Ema`, etc.) e botão de prévia (*preview*) auditiva.

---

## 3. 🎙️ Recursos de Estúdio e Áudio Avançado
- [ ] **Biblioteca padrão de vozes clonadas (`vozes/`)**:
  - Fornecer amostras curtas pré-higienizadas (com corte de ruído e normalização LUFS) para estilos específicos: narração neutra, leitura de notícias e podcasts informais.
- [ ] **Expansão das tags de estilo e emoção**:
  - Suporte a novas variações de tom como `[tom:noticia]`, `[tom:narracao]`, `[tom:entusiasmado]`.
- [x] **Capítulos por arquivo e metadados básicos** *(Entregue na E5; capítulos embutidos/M4B adiados)*:
  - Exportação por capítulo (`--por-capitulo` com `#`/`##`) e metadados simples (`--titulo`, `--autor`).

---

## 4. ⚡ Integração e Automação (API e Streaming)
- [ ] **Streaming de áudio em tempo real**:
  - Habilitar resposta em *chunked transfer encoding* no servidor local compatível com OpenAI (`servidor_api.py`), permitindo reprodução instantânea com baixa latência em assistentes virtuais e chatbots.
