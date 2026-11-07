# 🗺️ Roadmap de Próximas Melhorias — TTSBR

> **Plano da próxima entrega:** [Roadmap Técnico v1.2.0](ROADMAP_1.2.0.md) (ciclo anterior concluído: [0.9.0 Preview → 1.1.0](ROADMAP_0.9.0.md)). O plano detalha as etapas **M1 a M5**, módulos afetados, testes e critérios de lançamento da `1.2.0`.

Este documento consolida as sugestões e prioridades planejadas para as próximas iterações do TTSBR, organizadas por impacto e área do pipeline.

---

## 1. 🗣️ Fonética PT-BR e Naturalidade de Prosódia
- [x] **Modularização do léxico e expansão de IA e tecnologia** *(Entregue em `lexico.py` e v1.2.0)*:
  - Dicionário desacoplado com vocabulário técnico de IA (*fine-tuning*, *embeddings*, *pipeline*, *benchmark*, *framework*, *prompt*, *dataset*, *tokenizer*, *dropout*, *backpropagation*, *autoencoder*, *tokenization*, *loss function*, *inference*, *checkpoint*, *overfitting*, *underfitting*, *zero-shot*, *few-shot*, *rag*, *latency*, *throughput*).
- [x] **Guia de tonicidade automática para paroxítonas suscetíveis a oxítonas** *(Entregue na v1.2.0 — M3)*:
  - Mapeamento contextual em `normalizador.py` (`GUIA_TONICIDADE_PTBR`) para paroxítonas críticas onde modelos multilíngues (XTTS v2) tendem a deslizar a tonicidade (`recorde`, `rubrica`, `circuito`, `gratuito`, `fluido`, etc.), aplicando acentuação gráfica auxiliar invisível na camada de fala sem afetar legendas `.srt`/`.vtt`.
- [x] **Normalização de grandezas e faixas compostas** *(Entregue na E5)*:
  - Leitura natural de unidades com barra ou expoentes (`km/h`, `MB/s`, `m²`, `°C`), horários `12h30`, ordinais (`1º`, `2ª`, `1er`, `3er`), intervalos (`10-20`) e `€` posposto.

---

## 2. 🖥️ Interface Gráfica Local (GUI)

- [x] **Player integrado com forma de onda (waveform)** *(Entregue na v1.2.0 — M1)*:
  - Visualização gráfica de envelope de amplitude no Canvas do `player_gui.py` com navegação/scrub interativo e destaque de picos saturados e silêncio.
- [x] **Edição rápida e regeração por segmento** *(E2 do preview)*:
  - Ações na tabela para editar a fala preparada e regerar o segmento, preservando o roteiro e as tomadas anteriores.
- [x] **Catálogo visual de vozes e locutores com prévia** *(Entregue na v1.2.0 — M1)*:
  - Seletor dinâmico com vozes nativas por idioma e perfis cadastrados na `BibliotecaVozes`, com botão de prévia auditiva imediata.

---

## 3. 🎙️ Recursos de Estúdio e Áudio Avançado
- [x] **Expansão das tags de estilo e emoção** *(Entregue na v1.2.0 — M3)*:
  - Suporte a perfis de cadência e tom: `[tom:noticia]`, `[tom:narracao]`, `[tom:entusiasmado]`, além de `[tom:calmo]`, `[enfase]` e `[sussurro]`.
- [x] **Audiolivros `.m4b` com capítulos navegáveis e capa** *(Entregue na v1.2.0 — M2)*:
  - Arquivo único M4B com manifesto `FFMETADATA1` embutido (`--m4b`), capítulos sincronizados com os cabeçalhos do roteiro e arte de capa opcional (`--capa`).
- [x] **Capítulos por arquivo e metadados básicos** *(Entregue na E5)*:
  - Exportação por capítulo (`--por-capitulo` com `#`/`##`) e metadados simples (`--titulo`, `--autor`).

---

## 4. ⚡ Integração e Automação (API e Streaming)
- [x] **Streaming de áudio em tempo real** *(Entregue na v1.2.0 — M4)*:
  - Resposta em *chunked transfer encoding* no endpoint `/v1/audio/speech` (`servidor_api.py`), com envio imediato de cada segmento/pausa para baixa latência em assistentes virtuais e cancelamento seguro em caso de desconexão.
