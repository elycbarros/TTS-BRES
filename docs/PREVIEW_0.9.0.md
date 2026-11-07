# Base do preview 0.9.0 — E0

[Roadmap completo](ROADMAP_0.9.0.md) · [README](../README.md)

> Este documento registra a E0 e a preparação da distribuição `1.0.1` (E0–E6). As etapas [E1 — Biblioteca de vozes](BIBLIOTECA_VOZES.md), [E2 — Projetos e revisão](PROJETOS_REVISAO.md), [E3 — Fila e supervisão](FILA_TAREFAS.md), [E4 — Contrato de motores](MOTORES_E4.md), E5 (qualidade PT/ES, presets, loudness final e capítulos) e E6 (pacote portátil de projeto, roteiros públicos de captação no pacote e distribuição `1.0.1` limpa) já possuem código e testes automatizados no macOS.

Implementação iniciada em 07/11/2026 sobre `01f470290270636edabae6941ee194428d0ec7f2`. O `pyproject.toml` está identificado como `1.0.1`.

## Diagnóstico

No checkout, use o mesmo Python do ambiente de síntese:

```bash
python diagnostico.py
python diagnostico.py --dispositivos
python diagnostico.py --dados local
```

Após instalar o pacote atualizado: `ttsbr-diagnostico`.

O JSON só contém campos permitidos: sistema, arquitetura, versão Python, versões de dependências selecionadas, importação Tkinter/Tcl, disponibilidade do FFmpeg, sondagem opcional de CUDA/MPS e espaço livre. O caminho passado em `--dados` serve para medir o volume; não é exportado. A saída padrão pode ser redirecionada para um arquivo local. O comando retorna 0 quando consegue emitir o relatório, inclusive quando encontra dependências ausentes; não é um selo de prontidão.

Não coleta hostname, usuário, endereço de rede, serial, caminho do Python, variáveis de ambiente, roteiros ou áudios. As versões das dependências são consultadas por metadados. Tkinter e o executável FFmpeg são sondados em subprocessos com timeout. `--dispositivos` importa Torch em um subprocesso de até 30 segundos, sem carregar modelos. Nenhum download é solicitado.

Bibliotecas `avcodec`, `avformat` e `avutil` localizáveis não comprovam compatibilidade do TorchCodec. A leitura de referência continua marcada como não validada até o ensaio real. Tkinter importável não comprova funcionamento da janela, áudio ou player. O diagnóstico não certifica que há memória ou disco suficientes para qualquer modelo.

## Contratos v1

`contratos.py` é um módulo independente, ainda sem armazenamento ou interface. `validar(documento)` devolve cópia; `carregar(texto_json)` também rejeita chaves duplicadas. Ambos recusam versão desconhecida, campos inesperados, tipos incorretos, JSON não finito e estrutura excessivamente profunda.

Envelope comum: `formato`, `versao_esquema: 1`, `id` estável e `dados`.

| Formato | Campos de dados | Autoridade futura |
|---|---|---|
| `ttsbr.voz` | nome, idioma PT/ES, estilo, referência relativa, SHA-256, transcrição, autorização declarada | Cadastro local privado da biblioteca |
| `ttsbr.projeto` | título, roteiro original, elenco por ID de voz, glossário, configuração | Projeto editável, independente do áudio gerado |
| `ttsbr.tarefa` | projeto_id, estado, snapshot de projeto, saída relativa, erro | Registro persistente da fila; snapshot não muda durante a execução |

IDs usam letras ASCII, números, `_` e `-` (até 128 caracteres). Referências e saídas são relativas, com `/`, sem caminhos absolutos, drive Windows, UNC ou `..`. Antes de abrir arquivos, E1/E2 também deverão resolver caminhos sob a raiz permitida, verificar links simbólicos e os bytes/hash reais; o contrato sintático sozinho não faz isso.

O validador de tarefa exige que o snapshot seja um projeto com o ID correspondente. Estados reconhecidos: `aguardando`, `executando`, `interrupcao_solicitada`, `interrompida`, `concluida`, `falha`, `cancelada`. Estado `falha` exige mensagem. Transições, publicação atômica de resultados e política de retry serão implementadas em E3; validar um estado não autoriza uma transição.

`configuracao` guarda JSON finito e ainda não valida opções de motor: E4 fornecerá o contrato de capacidades. Validação de vínculos com vozes cadastradas ficará em E1/E2. Autorização declarada não comprova identidade ou permissão externa.

## Persistência e migração decididas

- Biblioteca e fila usarão SQLite pela biblioteca padrão, com autoridade única para IDs, relações e estados, quando implementadas. E1/E3 deverão definir tabelas, transações e serialização por um coordenador; não compartilhar o banco em volume de rede ou entre escritores sem coordenação.
- Projeto editável terá documento JSON v1 exportável; o banco indexará seus IDs, sem guardar uma segunda cópia editável independente do roteiro. A tarefa conterá snapshot próprio e imutável, pois precisa representar exatamente o trabalho solicitado.
- Manifestos e cache existentes continuam responsáveis pelos segmentos e sua integridade. A fila referencia seus resultados, sem substituir essa verificação.
- Persistência só será habilitada após implementar gravação atômica e backup. Esta etapa não cria banco nem modifica dados existentes.
- Preferências/snapshots atuais e manifestos não são documentos v1. Não tentar convertê-los apenas acrescentando um campo de versão. A importação será explícita e deverá preservar os originais.
- Versão do aplicativo, do documento e do cache são independentes. Uma futura 1.1.0 deverá ler o esquema v1 criado no preview ou oferecer migração transacional testada.

Procedimento obrigatório de migração na futura integração:

1. Encerrar workers e impedir novas tarefas.
2. Copiar documentos e usar a API de backup do SQLite para banco existente; não copiar somente o arquivo principal de um banco aberto em WAL.
3. Verificar a legibilidade e integridade do backup em destino separado.
4. Migrar em transação/cópia temporária, validando esquema e relações. Recusar versões futuras sem regravar o arquivo.
5. Publicar a nova versão de dados só após sucesso; falha preserva o original e informa o caminho local de recuperação.
6. Para voltar ao aplicativo anterior, restaurar a cópia compatível. Não fazer downgrade silencioso de esquema.

Não há migrador executável nesta etapa: ainda não existem dados v1 persistidos para migrar. Testes de migração e restauração serão bloqueadores da integração E1–E3 e da promoção 1.1.0.

## Distribuição e promoção

A sequência acordada é **0.9.0 Preview → 1.1.0 final**. Como o pacote atual usa 1.0.0, criar ambiente dedicado ao preview e instalar sua distribuição explicitamente. Não depender da ordenação automática de versões. Manter os dados de avaliação separados dos dados atuais usando `TTSBR_HOME` antes de iniciar a aplicação.

Exemplo para quando o wheel do preview existir (não é um artefato já publicado):

```bash
python3.12 -m venv .venv-preview
# macOS: source .venv-preview/bin/activate
# Windows: .venv-preview\Scripts\activate
python -m pip install ./dist/ttsbr-0.9.0-py3-none-any.whl
```

Ao empacotar, atualizar a versão para 0.9.0, incluir documentos/módulos, verificar wheel/sdist e registrar o commit testado. Na promoção, criar 1.1.0 e nova tag; não reescrever o preview. A instalação final e a leitura de dados do preview devem ser testadas em cópia descartável antes de uso pessoal.

## Matriz inicial e evidências

| Ambiente | Verificação automática nesta base | Verificação real exigida |
|---|---|---|
| macOS Apple Silicon, Python 3.12, CPU | Contratos, diagnóstico, suíte existente e distribuição | GUI/player, geração PT/ES e audição |
| Windows x64, Python 3.12, CPU | Preparar mesma suíte e smoke test de distribuição | Instalação limpa, GUI/áudio, acentos, espaços e encerramento de filhos |
| MPS no Mac | Sondagem opcional de disponibilidade | Inferência, memória e recuperação; experimental até aprovação |
| CUDA no Windows | Sondagem opcional, quando houver máquina | Inferência e recuperação em GPU real; opcional |

Checklist de conclusão de E0:

- [x] Base por commit identificada; referência existente em `constraints/macos-py312.txt` preservada.
- [x] Diagnóstico público sem carregamento de modelos, com ausência de dependências e timeouts cobertos.
- [x] Contratos v1 e rejeição de versões desconhecidas testados.
- [x] Autoridade de persistência, estratégia de backup/migração e numeração documentadas.
- [x] Suíte completa: 96 testes aprovados em 07/11/2026, Python 3.12.14, macOS arm64; 86 existentes e 10 novos.
- [x] Wheel/sdist construídos pela cópia pública e backend setuptools; wheel instalado sem dependências em ambiente separado. Diagnóstico, importação de contratos e documentos incluídos conferidos fora do checkout.
- [ ] Repetir os testes no Windows quando o ambiente estiver disponível; não declarar essa plataforma aprovada.

As evidências desta base não aprovam a GUI, o áudio de clonagem nem o Windows. Os resultados de 01/11 continuam históricos. Nenhuma funcionalidade futura descrita no roadmap deve ser anunciada como já entregue.

## Resultado local da E0

O ambiente de teste existente usa coqui-tts 0.28.0, Torch/Torchaudio 2.8.0, TorchCodec 0.17.0, pydub 0.25.1 e NumPy 2.5.4. O diagnóstico encontrou o executável de `imageio-ffmpeg` funcional e não localizou as bibliotecas nativas sondadas; Tkinter não ficou importável nesse Python. Não houve nova inferência ou teste de GPU.

O smoke test do wheel usou instalação `--no-deps` para confirmar que diagnóstico e contratos funcionam sem modelos. Não comprova instalação completa da síntese. A ferramenta `build` não estava disponível; a construção usou diretamente `setuptools.build_meta` com os fontes preparados por `scripts/construir.py`.
