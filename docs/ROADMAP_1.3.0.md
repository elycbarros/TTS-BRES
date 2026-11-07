# Roadmap Técnico — TTSBR v1.3.0

[README](../README.md) · [Roadmap geral](ROADMAP.md) · [Ciclo 1.2.0](ROADMAP_1.2.0.md)

> **Base de partida:** versão `1.2.0` (commit `79a6a0e`, 192 testes aprovados no macOS Apple Silicon / Python 3.12.14).
> **Referência vocal mestre:** gravação fonética pessoal de alta fidelidade (1m46s, ALAC 48 kHz, RMS -22,4 dBFS) cadastrada na `BibliotecaVozes` sob o perfil `"Ely"` (`4bed390f780d4bc994f42ddce352764e`).

---

## Objetivo da v1.3.0

Evoluir o TTSBR para um **estúdio pessoal completo de clonagem de alta fidelidade**, utilizando a captação vocal real do autor para implementar **condicionamento multi-take por estilo**, **cache persistente de tensores latentes do locutor** (*Speaker Latent Caching*), **clonagem cruzada PT-BR ↔ Espanhol** e **métricas objetivas de similaridade de voz (*Cosine Similarity*)**.

---

## Princípios e Diretrizes

1. **Privacidade absoluta dos dados biométricos de voz:** gravações originais e perfis cadastrados residem exclusivamente em `local/vozes/` e na pasta de dados do usuário (`TTSBR_HOME`), protegidos pelo `.gitignore` e nunca incorporados em pacotes de distribuição pública (`wheel`/`sdist`).
2. **Compatibilidade regressiva de esquemas:** o esquema de perfil de voz `ttsbr.voz` v1 continuará plenamente suportado, expandindo metadados opcionais para múltiplos takes sem quebrar perfis anteriores.
3. **Eficiência computacional na inferência:** pré-computar e armazenar latentes de condicionamento (`gpt_cond_latent` e `speaker_embedding`) para evitar passagens redundantes pelo extrator acústico a cada frase.

---

## Etapas de Entrega (M1 a M5)

```
M1 (Condicionamento Multi-Take por Estilo) ──┐
M2 (Cache de Latentes e Embeddings de Voz)  ├─► M5 (Estabilização, Documentação e Release 1.3.0)
M3 (Clonagem Cruzada PT ↔ ES Calibrada)     │
M4 (Métricas Objetivas de Fidelidade Vocal) ─┘
```

| Etapa | Escopo Principal | Módulos Afetados | Tamanho |
|---|---|---|---|
| **M1** | Perfil com múltiplas tomadas de referência (*multi-take*) vinculadas a tons (`neutra`, `tecnica`, `expressiva`, `noticia`) | `biblioteca_vozes.py`, `vozes.py`, `gui.py`, `tts.py` | M |
| **M2** | Cache em disco dos tensores de condicionamento (`.latents.pt`) para acelerar síntese quente e evitar recomputação | `motores.py`, `audio_persistente.py`, `tts.py` | M |
| **M3** | Calibração de clonagem cruzada de idiomas (referência PT-BR vocalizando ES e vice-versa) com prosódia nativa | `normalizador.py`, `segmentador.py`, `lexico.py` | P/M |
| **M4** | Avaliação objetiva de fidelidade de clonagem via *Cosine Similarity* de *Speaker Embeddings* contra a gravação mestre | `validar_audio.py`, `qualidade_audio.py`, `medir_audio.py` | M |
| **M5** | Validação integrada com suite de testes expandida, documentação e empacotamento da versão `1.3.0` | `pyproject.toml`, `docs/*`, `CHANGELOG.md` | P |

---

### M1 — Condicionamento Multi-Take na Biblioteca de Vozes

**Motivação:** Uma gravação mestre longa (como a captação de 1m46s) contém diferentes entonações: trechos neutros, afirmações técnicas firmes, perguntas reflexivas e cadência de encerramento. Um perfil de voz ganha expressividade superior quando o sistema pode alternar a referência acústica conforme a tag `[tom:...]` do roteiro.

**Entregas:**
- **Extensão do esquema `ttsbr.voz`:** suporte opcional a `takes: { "neutra": "take1.wav", "tecnica": "take2.wav", "expressiva": "take3.wav" }`.
- **Seleção inteligente de tomada:** ao sintetizar um trecho com `[tom:X]`, resolver a tomada mais adequada do perfil cadastrado antes de recorrer ao fallback global.
- **Interface da Biblioteca:** visualização e audição individual de cada take cadastrado no perfil na janela da GUI.

---

### M2 — Cache Persistente de Latentes do Locutor (*Speaker Latent Caching*)

**Motivação:** A cada segmento de fala, o XTTS v2 lê o WAV de referência, calcula o mel-espectrograma e processa o extrator de voz para obter `gpt_cond_latent` e `speaker_embedding`. Em sínteses de textos longos ou streaming HTTP, recomputar esses tensores dezenas de vezes gera consumo desnecessário de CPU/GPU.

**Entregas:**
- **Módulo extrator e serializador:** salvar os tensores pré-computados com chave baseada no hash SHA-256 do áudio e parâmetros de condicionamento (`<sha256>.latents.pt`).
- **Integração no `MotorXTTS`:** carregar diretamente os tensores em memória GPU/MPS quando disponíveis, reduzindo o tempo de processamento por segmento em ~30% a 40%.

---

### M3 — Clonagem Cruzada de Idioma (PT-BR ↔ Espanhol)

**Motivação:** Os ensaios empíricos comprovaram que a voz de Ely captada em português é capaz de vocalizar espanhol com WER baixo (8,3%), mantendo o timbre característico do narrador.

**Entregas:**
- **Calibração de cadência fonética cruzada:** ajustes nas durações de pausas e elisões entre PT e ES para evitar sotaque artificial na troca de idioma.
- **Testes com corpus bilíngue:** ampliação dos casos de teste com a voz clonada em roteiros técnicos em espanhol.

---

### M4 — Métricas Objetivas de Fidelidade Vocal (*Speaker Similarity*)

**Motivação:** Atualmente a validação afere transcrição e WER (Whisper) e níveis acústicos (RMS/pico/LUFS). É essencial mensurar matematicamente o quanto a voz sintetizada se aproxima da voz real captada.

**Entregas:**
- **Cálculo de Cosine Similarity:** extração de vetores de embedding acústico do locutor a partir da referência mestre e do áudio gerado, calculando a similaridade angular `[0.0..1.0]`.
- **Relatório de fidelidade vocal:** inclusão do índice de similaridade do locutor no arquivo `.validacao.json`.

---

### M5 — Estabilização, Documentação e Release `1.3.0`

**Entregas:**
- Bump de versão para `1.3.0` em `pyproject.toml`.
- Atualização documental completa (`README.md`, `CHANGELOG.md`, `docs/BIBLIOTECA_VOZES.md`, `docs/GUI.md`).
- Construção limpa de pacotes e aprovação de 100% da suíte automatizada.
