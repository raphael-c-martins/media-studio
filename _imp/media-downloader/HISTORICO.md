# Diário de Decisões e Histórico de Desenvolvimento (HISTORICO.md)

Este documento registra a evolução arquitetural, decisões técnicas e diretrizes mandatórias de manutenção do projeto **MediaDownloader Pro**.

---

## 🛡️ Diretrizes Críticas de Preservação e Segurança

> [!CAUTION]
> **PRESERVAÇÃO ABSOLUTA DE DADOS E LOGS:**
> 1. É estritamente proibido resetar, truncar, recriar do zero ou apagar o banco de dados do projeto (`media_downloader.db`).
> 2. Qualquer evolução estrutural do esquema do banco de dados deve ser executada exclusivamente por meio de migrações incrementais e seguras.
> 3. Nunca apague arquivos ou pastas de logs persistentes em `/logs/` ou `/logs/logs-cmd/`. Os registros são vitais para auditoria operacional e diagnóstico de incidentes.
> 4. As operações de I/O (disco, rede e banco de dados) devem sempre utilizar chamadas assíncronas (`async/await`) para evitar bloqueio da interface e do loop de eventos.

---

## 🚀 Linha do Tempo de Atualizações

### [2026-09-08] - Correção do Formato de Saída no Navegador (Nomes/Extensões), Cancelamento da Fila e Blindagem contra Lives

- **Contexto e Causa Raiz:**
  1. **Nomes de Arquivos Salvos como UUID no Navegador:** Ao concluir o download de um vídeo ou clicar para baixar a thumbnail, o navegador salvava o arquivo com o identificador interno em UUID (ex: `99483c4f-609e-4229-9054-e03d8912ce3b`) sem qualquer extensão (`.mp4`, `.jpg`), em vez do título limpo da mídia. As causas principais foram:
     - Uso de transliteração ASCII com substituição (`.encode('ascii', 'replace')`), que convertia caracteres acentuados (como `Ç` ou `Ã`) em pontos de interrogação (`?`). No Windows NT, `?` é um caractere estritamente proibido em nomes de arquivos (`\ / : * ? " < > |`), fazendo o Chromium descartar o `Content-Disposition` e recorrer ao ID temporário.
     - As rotas de arquivo e thumbnail terminavam sem o nome do arquivo no segmento final do caminho da URL (ex: `/api/history/{id}/file`), induzindo o navegador a usar o UUID como nome padrão caso o cabeçalho fosse sanitizado.
  2. **Travamento da Fila por Transmissões ao Vivo (Lives):** A inserção de URLs de transmissões ao vivo em andamento bloqueava indefinidamente o worker do `QueueManager`, pois o stream contínuo impedia o encerramento do download.
  3. **Ausência de Cancelamento de Itens da Fila:** Não havia mecanismo na interface gráfica (nem na barra de progresso inline, nem no widget flutuante) para que o usuário pudesse abortar um download em execução ou pendente, e a chamada de cancelamento no backend corria o risco de interromper o loop contínuo do próprio worker.

- **Soluções Implementadas:**
  1. **Sanitização Resiliente e Nomes Canônicos com Extensão (`routes_history.py` e `routes_info.py`):**
     - A função `clean_filename_for_browser` foi reformulada para utilizar `unicodedata.normalize('NFKD', s).encode('ascii', 'ignore')`, convertendo acentos em letras equivalentes (`Ç` -> `C`, `Ã` -> `A`) sem jamais gerar `?`.
     - Todos os caracteres proibidos pelo sistema de arquivos do Windows (`\ / : * ? " < > |`, controles de quebra de linha e ponto e vírgula) são estritamente filtrados.
     - Garantida a injeção obrigatória da extensão da mídia (`.mp4`, `.jpg`, `.webp`, `.png`) tanto no nome ASCII quanto no nome UTF-8.
     - Suporte nas rotas da API para inclusão explícita do nome no path da URL:
       - `GET /api/history/{id}/file/{filename}`
       - `GET /api/info/download-thumbnail/{filename}`
     - Cabeçalho duplo `Content-Disposition: attachment; filename="{safe_ascii}"; filename*=UTF-8''{encoded_utf8}` para máxima conformidade com a RFC 5987.
  2. **Disparo de Download no Frontend com Tag `<a>` e Atributo `download` (`main.js`):**
     - O método `triggerBrowserDownload` utiliza âncoras nativas com o atributo `download="nome.ext"`, apontando para rotas com os nomes já codificados na URL, assegurando que o navegador aplique o nome correto em 100% dos cenários.
     - Atualizados os disparos no evento `download_completed`, no botão "Salvar no PC" do histórico e no download da capa.
  3. **Controle de Cancelamento na Interface e Isolamento do Worker (`queue_manager.py`, `index.html`, `style.css`, `main.js`):**
     - Adicionado botão de cancelamento inline (`#btn-cancel-inline-download`) na barra de progresso principal.
     - Adicionado botão de cancelamento individual (`.btn-cancel-queue-item`) no cabeçalho de cada item do widget de fila flutuante.
     - No backend, o processamento de cada download pelo worker é isolado em uma `asyncio.Task` filha, permitindo cancelar a tarefa específica sem afetar a continuidade do loop do worker.
     - Adicionada trava contra transmissões ao vivo no frontend e no backend (`is_live`), impedindo o enfileiramento de streams ativos que poderiam congestionar os workers.

- **Contexto e Causa Raiz:**
  1. **Falha de Fusão de Vídeo/Áudio (Crash 100%):** Downloads de vídeos em alta resolução (1080p, 4K) alcançavam 100% mas falhavam na etapa final de merge do `yt-dlp` com erro de binário ausente. O pacote `imageio-ffmpeg` empacotava exclusivamente o `ffmpeg`, faltando o utilitário auxiliar `ffprobe`.
  2. **Caminho Corrompido no Histórico (Fragmentos Temporários):** O hook de progresso capturava o nome do arquivo no evento `"finished"`, que em downloads particionados correspondia ao fragmento intermediário (ex: `.f251-1.webm`) que é deletado pelo `yt-dlp` imediatamente após o merge. Isso deixava o banco apontando para arquivos inexistentes.
  3. **Download no Navegador com UUID e Sobrecarga de RAM:** O disparo de download via JavaScript `fetch() + blob` tentava alocar arquivos inteiros (centenas de megabytes ou gigabytes) na memória RAM do navegador e perdia o cabeçalho original de nome do arquivo devido ao CORS entre as portas `3030` e `8800`.
  4. **Dispersão de Pastas de Armazenamento:** Com o processo do Uvicorn rodando no subdiretório `backend/`, arquivos baixados com caminhos relativos caíam dentro de `backend/downloads/` em vez da pasta raiz `./downloads`.

- **Soluções Implementadas:**
  1. **Integração Completa com `static-ffmpeg` (`ffmpeg_helper.py`):**
     - O módulo foi reestruturado para utilizar o `static-ffmpeg` como fonte primária, provendo tanto o `ffmpeg` quanto o `ffprobe`.
     - Implementado cache em memória (`_cached_ffmpeg_dir`) para evitar chamadas de sistema repetidas.
     - O `yt-dlp` agora recebe o diretório base dos binários em `ffmpeg_location`, localizando ambos os executáveis automaticamente.
     - Adicionada verificação de prontidão do `ffprobe` no endpoint `/health`.
  2. **Captura Fidedigna do Arquivo Final (`queue_manager.py`):**
     - Remoção da captura prematura no `progress_hook`.
     - Inclusão do `postprocessor_hook` registrando o caminho absoluto do arquivo após a finalização de todos os pós-processadores de merge e metadados.
     - Fallback multinível com varredura por glob e resolução de caminho canônico (`Path.resolve()`).
  3. **Download Seguro no Navegador via Iframe Oculto e RFC 5987 (`routes_history.py` e `main.js`):**
     - Substituição do `blob` por um elemento `<iframe>` oculto descartável, que inicia o download nativo do navegador sem consumir memória RAM local.
     - Implementação no backend de cabeçalho `Content-Disposition: attachment; filename="..." filename*=UTF-8''...` para conformidade com a RFC 5987, preservando acentos, caracteres especiais e espaços nos títulos originais dos vídeos.
     - Adicionado decorator `@router.head()` para validação prévia de requisições de cabeçalho.
  4. **Unificação e Normalização do Diretório de Downloads:**
     - Garantida a resolução absoluta de `target_folder` contra `BASE_DIR` em `queue_manager.py` e `routes_settings.py`.
     - Migração física de todas as mídias salvas em `backend/downloads/` para o diretório raiz `downloads/`.
     - Atualização da chave `download_folder` no banco SQLite para o caminho absoluto oficial.
  5. **Saneamento e Limpeza do Banco de Dados:**
     - Criação de backup preventivo `media_downloader.db.bak` (ignorado no Git).
     - Remoção de registros órfãos que continham erros de testes ou arquivos inexistentes, preservando 100% dos registros válidos com seus novos caminhos normalizados.
  6. **Download Direto de Thumbnail/Capa ao Passar o Mouse (`routes_info.py`, `index.html`, `style.css` e `main.js`):**
     - Adicionado efeito de hover na miniatura do vídeo com escurecimento suave (`brightness(0.7)`), zoom dinâmico e botão centralizado **"Baixar Capa"** com ícone de download.
     - Criada rota dedicada `GET /api/info/download-thumbnail` com suporte a proxy seguro e cabeçalho `Content-Disposition: attachment; filename*=UTF-8''...` (RFC 5987), garantindo o download imediato da imagem em alta resolução sem bloqueios de CORS e com nome padronizado.
     - Disparo instantâneo com toast notification de feedback no frontend.

### [2026-09-01] - Criação e Arquitetura Inicial do MediaDownloader Pro

- **Contexto e Motivação:**
  Necessidade de um baixador e processador universal de mídias para YouTube, Instagram, Twitter/X, TikTok e mais de 1.800 sites, combinando os pontos fortes dos projetos open-source analisados (`OmniGet`, `YouWee`, `Instaloader` e `DeepSeek Harness`).

- **Decisões Arquiteturais:**
  1. **Separação Frontend/Backend:** Frontend independente com Vite na porta `3030` e Backend assíncrono com FastAPI/Uvicorn na porta `8800`.
  2. **Comunicação em Tempo Real:** Utilização de *Server-Sent Events* (SSE) na rota `/api/downloads/stream` para transmissão de status de progresso (velocidade, porcentagem, tamanho e ETA) sem sobrecarga de polling HTTP repetitivo.
  3. **Persistência Assíncrona com SQLite (`aiosqlite`):** Consultas totalmente parametrizadas prevenindo SQL Injection e sistema de auto-migração de tabelas (`downloads`, `settings`, `ai_summaries`).
  4. **Fila Assíncrona com Cancelamento Limpo:** Criação do `QueueManager` gerenciando workers em segundo plano e cancelamento seguro de processos de download sem travar o servidor.
  5. **Módulo de IA (DeepSeek):** Integração para resumo de vídeos, transcrição e extração de tópicos principais.
  6. **Launcher `.bat` Resiliente:** Script revisado para Windows com detecção automática de ambiente Python (`.venv`), instalação de dependências, finalização limpa de processos via PowerShell e logs dedicados em `logs/logs-cmd/`.

- **Desafios Superados:**
  - Tratamento de extração de mídias de plataformas com restrições dinâmicas através do motor atualizado `yt-dlp` com injeção segura de parâmetros.
  - Prevenção de conflitos de portas e gerenciamento estável de subprocessos em ambiente Windows.

### [2026-09-01] - Arquitetura Final do Launcher Desacoplado (.bat + PowerShell)

- **Diagnóstico e Causa Raiz:**
  O interpretador clássico do Windows (`cmd.exe`) apresentava falhas de sintaxe (`... foi inesperado neste momento`) ao processar blocos `if (...)` multilinhas contendo parênteses aninhados e caracteres de controle do PowerShell.

- **Solução Definitiva:**
  1. O arquivo `iniciar-servidor-local.bat` foi convertido para uma estrutura puramente linear (estilo DOS clássico com `goto`), sem nenhum bloco de parênteses no batch.
  2. A lógica de inicialização, encerramento, diagnóstico de status e instalação de dependências foi modularizada na pasta `/scripts/`:
     - `scripts/start-all.ps1`: Inicialização desacoplada, verificação de prontidão dos sockets TCP e abertura do navegador em `http://localhost:3030`.
     - `scripts/stop-all.ps1`: Encerramento forçado e limpo de processos vinculados às portas 3030 e 8800.
     - `scripts/status-all.ps1`: Diagnóstico em tempo real e verificação de integridade da API `/health`.
     - `scripts/install-deps.ps1`: Gerenciamento do ambiente virtual `.venv` e `npm install`.

### [2026-09-01] - Integração do FFmpeg Portátil e Aprimoramento de UX de Download

- **Problema Diagnosticado:**
  1. Falha no `yt-dlp` ao solicitar formatos de alta qualidade (1080p, 4K ou áudio MP3) devido à ausência do binário do FFmpeg no sistema operacional (`You have requested merging of multiple formats but ffmpeg is not installed`).
  2. Redirecionamento indesejado para a aba de Fila Ativa ao clicar em "Baixar Agora".
  3. Presença de indicador textual com porta interna no header ("Online (Porta 8800)").

- **Soluções Implementadas:**
  1. **FFmpeg Portátil Integrado:** Instalação e integração do pacote `imageio-ffmpeg` v7.1 nativo de 64-bit no backend, injetando `ffmpeg_location` automaticamente no `yt-dlp` em todas as operações de merge, cortes de tempo e conversões de áudio.
  2. **UX de Download Direto (Inline Progress):** Adicionada barra de progresso em tempo real na própria aba de Download/Inspeção, exibindo percentual, velocidade (MB/s) e tempo restante (ETA) sem forçar navegação de abas. A aba "Fila Ativa" permanece disponível para consultas simultâneas.
  3. **Header Minimalista:** Removido o badge com indicação de porta do header superior.

### [2026-09-01] - Seletor de Plataformas e Varredura de Perfis (Instagram, Twitter, TikTok, YouTube)

- **Novos Requisitos:**
  1. Adição de seletor visual de plataforma na tela inicial (Automático/+1800, YouTube, Instagram, Twitter/X, TikTok).
  2. Suporte a download por perfil/usuário (ex: `@usuario`), estilo StoriesIG/Picuki, exibindo galeria com fotos, vídeos, reels e carrosséis públicos.
  3. Capacidade de download individual e em lote ("Baixar Selecionados").

- **Implementações Técnicas:**
  1. **Serviço de Varredura (`profile_scanner.py`):**
     - Integração com `instaloader` para extração de posts, carrosséis, reels, dados biográficos e avatar do Instagram.
     - Suporte a extração de feeds de canais do YouTube e timelines do Twitter/X via `yt-dlp` (`extract_flat`).
  2. **Endpoint `/api/profile/scan`:** Rota assíncrona dedicada com sanitização e normalização de `@username` e URLs de perfis.
  3. **Interface Visual (Profile Media Gallery):**
     - Pills interativas com ajuste automático de placeholder de busca.
     - Card de cabeçalho do perfil com avatar, bio, contagem de seguidores e posts.
     - Grade responsiva de mídias com badges de formato (Vídeo, Reel, Foto, Carrossel), seleção múltipla e enfileiramento em lote.

### [2026-09-01] - Refatoração e Redesign Visual da Tela Inicial (UI Pro)

- **Diagnóstico do Bug Visual:**
  O seletor CSS do input de busca estava restrito a `input[type="url"]`, enquanto o markup HTML havia sido atualizado para `input[type="text"]` (para suportar inputs como `@usuario`). Isso causava perda de largura total (`width: 100%`) e quebrava o alinhamento do formulário flexbox.

- **Aprimoramentos de UI/UX:**
  1. **Barra de Pesquisa de Alto Impacto:** Input unificado (`height: 52px`) com foco suave, ícone temático e botão de colar integrado.
  2. **Platform Selector Pills:** Botões de plataforma estilizados com SVG nítidos, hover translúcido e estado ativo com glow.
  3. **Destaques da Home (Welcome Grid):** Seção informativa com cards explicativos de recursos (YouTube 4K, Instagram Stories/Reels, Twitter/TikTok e Resumos IA DeepSeek) para preenchimento harmônico do layout.

### [2026-09-01] - Interatividade Completa nos Cards da Home & Card Exclusivo do TikTok

- **Novas Melhorias:**
  1. **Cards Clicáveis com Ação Direta:** Os cards da tela inicial agora são totalmente interativos (`clickable-card`), com micro-animação de hover (`translateY(-4px)` e glow suave), seta indicativa e redirecionamento dinâmico:
     - Clicar nos cards de plataforma (**YouTube**, **Instagram**, **Twitter/X**, **TikTok**) seleciona a pill correspondente no seletor, foca o campo de busca e ajusta o placeholder.
     - Clicar no card de **Resumos IA com DeepSeek** navega instantaneamente para a aba dedicada de Inteligência Artificial no menu.
  2. **Card Independente para o TikTok:** Criação de card próprio com ícone e estilização ciano/neon dedicada a downloads em alta definição sem marca d'água.
  3. **Navegação pela Marca (Brand Home Click):** A área de logotipo e título no cabeçalho superior (`header-brand`) tornou-se clicável e com acessibilidade (`role="button"` e atalho de teclado), permitindo retornar instantaneamente à tela inicial de download a partir de qualquer aba.

### [2026-09-01] - Tratamento Resiliente de Rate Limit (Instagram) & Prevenção de Falhas de JSON

- **Diagnóstico da Falha:**
  1. A varredura de perfil do Instagram (`instaloader`) entrava em loop de retry automático prolongado (666 segundos) quando a API pública do Instagram devolvia HTTP 429 (*Too Many Requests*), gerando timeout no proxy do Vite (`504 Gateway Timeout`).
  2. O frontend tentava parsear a resposta de erro com `res.json()` diretamente, gerando a exceção não tratada `Failed to execute 'json' on 'Response': Unexpected end of JSON input`.

- **Correções Aplicadas:**
  1. **Controle Estrito de Conexão no Backend:** Configurado `max_connection_attempts=1`, `sleep=False` e `asyncio.wait_for` com timeout rígido (12s), prevenindo qualquer travamento de worker ou loop de retry.
  2. **Parser Resiliente de Erros HTTP:** Implementação do helper `parseResponseError()` no frontend com suporte a `AbortController` (15s), garantindo que mensagens de erro sejam sempre extraídas e apresentadas em português claro via Toast Notifications.
  3. **Detecção Universal de Modo Perfil:** Roteamento automático para varredura de perfil ao identificar links de perfil ou `@usuario`, independentemente da pill ativa.

### [2026-09-01] - Inicialização 100% Silenciosa dos Servidores (Headless/Background)

- **Problema Reportado:**
  Ao selecionar a opção de ligar o sistema no launcher, janelas de console do `cmd.exe` (Vite) e `python.exe` (Uvicorn) eram criadas e ficavam visíveis na tela.

- **Solução Implementada:**
  1. A inicialização em `scripts/start-all.ps1` foi refatorada utilizando `System.Diagnostics.ProcessStartInfo` com `CreateNoWindow = $true`, `WindowStyle = 'Hidden'` e `UseShellExecute = $false`.
### [2026-09-01] - Suporte Completo a Fotos e Carrosséis do Instagram (Resolução de 'No video formats found')

- **Diagnóstico da Falha:**
  Posts do Instagram compostos exclusivamente por fotos ou carrosséis de imagens/vídeos falhavam no `yt-dlp` com a mensagem `No video formats found!`, pois o `yt-dlp` espera fluxos convencionais de vídeo e não trata publicações estáticas ou carrosséis híbridos do Instagram.

- **Solução Implementada:**
  1. **Módulo Especializado `instagram_helper.py`:**
     - Extração inteligente de metadados de posts através do shortcode.
     - Suporte nativo para **Foto Única (JPG)**, **Vídeo (MP4)** e **Carrossel Completo (JPG + MP4)**.
  2. **Pipeline de Download Direto Assíncrono:**
     - Integração de download direto via `httpx` assíncrono para mídias de carrossel e fotos em alta definição.
     - Todas as mídias do carrossel são baixadas sequencialmente (`_1.jpg`, `_2.mp4`, etc.) e salvas na pasta configurada (`/downloads/`).
### [2026-09-01] - Sistema Multitemas Visuais (Preto & Dourado, Preto & Cinza, Tons Claros)

- **Novos Temas Adicionados na Aba de Configurações:**
  1. **Azul Noturno (Padrão):** Paleta clássica e sóbria com azul elétrico e fundo ardósia escuro (`#0f172a`).
  2. **Preto & Dourado (Gold Luxury):** Visual sofisticado com preto profundo (`#09090b`), bordas âmbar e acentos dourados metálicos (`#d97706` / `#eab308`).
  3. **Preto & Cinza (Dark Slate Minimal):** Design monocromático moderno em tons de grafite, cinza escovado e ardósia (`#475569`).
  4. **Claro Moderno (Clean Light):** Tema claro com fundo branco níveo e acentos azuis de alto contraste (`#2563eb`).
  5. **Claro Creme (Warm Sand):** Tema claro suave com tons de areia/creme (`#fafaf9`) e toques quentes de âmbar.
- **Interatividade & Persistência Instantânea:**
  - Cards interativos com mini-paleta de amostra e seleção por clique direto com efeito imediato sem recarregar a página.
  - Persistência automática em `localStorage` e sincronização no banco SQLite via endpoint `/api/settings`.

- **Melhorias e Limpeza de UX Implementadas:**
  1. **Abertura Confiável de Pastas no Windows Explorer (`os.startfile`):**
     - Substituído `subprocess.run` por `os.startfile` nativo da API Win32 do Python em `routes_history.py`. O botão **`Abrir Pasta`** agora abre instantaneamente a pasta de downloads no Windows Explorer.
  2. **Remoção de Elementos Desnecessários:**
     - Removido o bloco de "Diagnóstico e Saúde do Servidor" (CPU/RAM/yt-dlp) que poluía as configurações.
  3. **Portabilidade de Pastas entre Diferentes Máquinas:**
     - A pasta de download não fica mais atrelada a caminhos absolutos fixos (`D:\...`). Se estiver em branco ou padrão, o sistema resolve automaticamente para a pasta `./downloads` dentro do projeto onde quer que ele esteja rodando.
  4. **Navegação Intuitiva e Clique no Logo:**
     - Clicar no logo/título **MediaDownloader PRO** ou no botão **Baixar** agora alterna de forma fluida para a tela principal (Home).
  5. **Widget Flutuante de Downloads Ativos (`#floating-queue-widget`):**
     - A página inteira da "Fila Ativa" foi removida da navegação superior.
     - Em seu lugar, foi criado um **card flutuante discreto e moderno no canto inferior direito**, que surge automaticamente **apenas durante downloads em andamento** com barra de progresso, velocidade e opção de minimizar, e se oculta sozinho quando a fila é finalizada.
















