# Biblioteca privada de vozes — E1

[README](../README.md) · [GUI](GUI.md) · [Roadmap](ROADMAP_0.9.0.md)

A E1 permite cadastrar tomadas de voz, editar dados, ouvir a referência preparada e reutilizar o perfil na narração. A biblioteca é local e não treina um modelo. Cada importação cria um ID independente, mesmo quando duas tomadas têm o mesmo nome ou áudio.

## Usar pela interface

1. Abra `python gui.py` e selecione **Biblioteca de vozes…**, na lateral.
2. Escolha uma gravação, preencha nome, idioma (`pt` ou `es`) e estilo. É possível informar uma transcrição e revisá-la depois.
3. Confirme que tem autorização para gravar e usar a voz. Essa declaração não verifica identidade ou direitos externos.
4. Opcionalmente marque **Criar também cópia limpa**. A limpeza é aplicada somente na importação; mudar a caixa e salvar os dados de um perfil existente não recalcula áudio. Para comparar com e sem limpeza, importe duas tomadas.
5. Clique em **Importar nova tomada**. O áudio é processado no Python selecionado nos ajustes da GUI, sem carregar XTTS ou Whisper. Aguarde concluir antes de fechar a biblioteca.
6. Selecione um perfil para conferir duração, taxa, canais, bits e avisos da referência preparada. Metadados do original aparecem quando o leitor instalado consegue identificá-los.
7. Use **Ouvir referência** para abrir o player padrão ou **Usar na narração** para selecionar o perfil.

Editar manualmente o campo de referência na janela principal desassocia o ID do perfil. Ao usar um perfil, o ID fica nas preferências e é conferido novamente no worker antes da análise/síntese. O idioma do perfil descreve a gravação; selecionar uma voz não muda automaticamente o idioma do roteiro.

A E1 usa o player do sistema; a [E2](PROJETOS_REVISAO.md) acrescentou um player WAV interno opcional. Os controles da janela foram implementados, mas a validação visual e auditiva no desktop e no Windows permanece pendente.

## Usar pela linha de comando

Execute com o Python do ambiente de síntese. Após instalar o pacote atualizado, `ttsbr-vozes` oferece os mesmos comandos de `python biblioteca_vozes.py`.

```bash
python biblioteca_vozes.py importar local/minha_voz.wav --nome "Minha voz neutra" --idioma pt --estilo neutra --autorizada
python biblioteca_vozes.py listar
python biblioteca_vozes.py renomear ID_DO_PERFIL "Minha voz revisada"
python biblioteca_vozes.py resolver ID_DO_PERFIL
python tts.py exemplos/narracao_pt.txt --perfil-voz ID_DO_PERFIL --saida saida/minha_narracao
```

Substitua `ID_DO_PERFIL` pelo `documento.id` retornado na importação/listagem. A opção `--voz` é incompatível com `--perfil-voz`; escolha uma delas. Personagens e tons específicos continuam seguindo a precedência já documentada no pipeline. O estilo cadastrado organiza as amostras e não garante emoção sintetizada.

`--limpar` cria uma derivação filtrada e a seleciona para a síntese. `--transcricao` registra a transcrição; não usa ASR nem faz download. O XTTS atual não recebe esse campo como condicionamento textual: ele fica disponível para revisão e futuros adaptadores.

O parâmetro global `--raiz PASTA` permite abrir uma biblioteca alternativa nos comandos de biblioteca. `tts.py --perfil-voz` usa a biblioteca padrão, determinada por `TTSBR_HOME` ou pela pasta de dados. Para a aplicação inteira usar outra raiz, defina `TTSBR_HOME` antes de abri-la; a biblioteca ficará em `local/vozes` dentro dela. Não publique o JSON desses comandos: ele contém dados privados e transcrições.

## Armazenamento e integridade

No checkout, os arquivos ficam em `local/vozes/`, ignorado pelo Git. Na instalação por pacote, ficam sob a raiz de dados do usuário, também em `local/vozes`. Uma biblioteca contém:

- `biblioteca.sqlite3`: cadastro v1 e vínculos de uso por projeto.
- `referencias/ID/original.ext`: cópia byte a byte da gravação importada.
- `referencias/ID/previa.wav`: referência preparada sem limpeza, mono/16 bits/24 kHz.
- `referencias/ID/limpa.wav`: derivação opcional, no mesmo formato.

O original não é sobrescrito. O hash do original e da referência selecionada é conferido antes do uso. Se algum arquivo desaparecer ou mudar, a síntese com esse perfil é bloqueada; restaure um backup íntegro ou importe outra tomada. Um novo áudio de referência com bytes diferentes muda a identidade do cache do pipeline existente.

As referências internas devem estar sob a raiz da biblioteca e não podem atravessar links simbólicos. Arquivos temporários não são publicados como perfis até concluir conversão e registro. Uma falha abrupta do processo pode deixar um diretório sem cadastro; ele não é listado como perfil válido. Não faça limpeza manual com a aplicação em execução.

O banco SQLite usa versão própria, independente da versão do aplicativo. Bancos futuros ou não reconhecidos são recusados sem migração silenciosa. A implementação inicial cria um banco novo; não importa preferências ou manifestos antigos automaticamente.

## Formatos e avisos

São aceitas extensões WAV, MP3, FLAC, M4A, OGG, AAC e AIFF, desde que o FFmpeg disponível consiga decodificá-las. FFmpeg pode vir do sistema ou de `imageio-ffmpeg`. A importação tem limite de 100 MiB, duração máxima de 75 segundos e timeout de 90 segundos por conversão. Áudio acima do limite é recusado, sem criar um perfil truncado.

A referência preparada é convertida para PCM mono de 16 bits a 24 kHz para corresponder ao pipeline atual. Essa conversão não cria detalhe ausente no original. Os avisos usam essa referência sem limpeza: amostra curta (menos de seis segundos), longa (mais de trinta), nível muito baixo e amostras próximas da saturação. Uma fração alta de amostras em nível baixo não equivale a detectar pausas contínuas; esses testes não identificam semanticamente a fala.

A limpeza usa filtros de frequência, redução FFT de ruído e normalização de volume. Pode alterar o timbre; compare por audição. As métricas não avaliam semelhança, sotaque, naturalidade ou qualidade de clonagem. Silêncio e avisos não são aprovação da gravação.

## Remover e recuperar

A remoção retira o perfil da lista ativa e bloqueia seu uso pelo ID, preservando os arquivos e áudios já gerados. Isso não é apagamento definitivo de dados pessoais. Vínculos cadastrados com projetos bloqueiam a remoção; a E2 integra esses vínculos aos projetos, e a E3 também protege perfis usados em tarefas ativas.

```bash
python biblioteca_vozes.py remover ID_DO_PERFIL
python biblioteca_vozes.py listar --removidas
python biblioteca_vozes.py restaurar ID_DO_PERFIL
```

A restauração verifica integridade antes de reativar o perfil. Uma preferência da GUI que aponte para um perfil removido deixa de funcionar até selecionar outro perfil ou restaurar o anterior.

## Backup e restauração de biblioteca

```bash
python biblioteca_vozes.py backup local/backup_vozes
```

Escolha um diretório novo, fora da biblioteca. O backup usa a API do SQLite para copiar o banco e copia as referências imutáveis, inclusive as de perfis removidos, verificando os hashes gravados. Não sobrescreve backups existentes e não publica um destino parcial em caso de erro. Um backup contém áudio e texto privados; mantenha-o fora do repositório público.

Para testar restauração sem sobrescrever a biblioteca atual:

1. Feche a aplicação e mantenha a biblioteca original intacta.
2. Execute `python biblioteca_vozes.py --raiz local/backup_vozes listar` e confira os perfis.
3. Para usar o backup como biblioteca principal, copie-o para `local/vozes` sob uma **nova** raiz de dados e defina `TTSBR_HOME` para essa raiz antes de abrir a aplicação.
4. Ouça referências e confira perfis antes de substituir qualquer diretório anterior. Não copie só o arquivo SQLite de um banco aberto.

## Validação desta entrega

Em 07/11/2026: **113 testes aprovados** no macOS arm64/Python 3.12.14, incluindo 17 novos testes da biblioteca. Exercitados seis perfis com nomes/estilos, persistência, WAV/MP3 sintéticos com FFmpeg real, limpeza, referência alterada/ausente, link simbólico, falha de transação, versão futura, remoção/restauração, vínculo com projeto, backup/reabertura, passagem de ID pela GUI e análise CLI/worker sem modelos.

As gravações de teste são sinais sintéticos, não vozes pessoais. Não houve ensaio de fidelidade da clonagem, audição humana nem aprovação da janela/player em macOS ou Windows. Os resultados da suíte não substituem essas verificações.

Wheel e sdist construídos a partir da cópia pública; o novo comando `ttsbr-vozes` foi instalado e executado fora do checkout em ambiente separado sem dependências de síntese. O inventário do wheel foi conferido e não contém gravações ou banco privado. A construção usou diretamente o backend setuptools, como na E0, pois a ferramenta `build` não estava disponível. Isso não equivale a repetir uma instalação completa do XTTS.
