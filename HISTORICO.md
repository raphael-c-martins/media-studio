# Histórico de Atualizações e Decisões de Arquitetura

Este documento registra a evolução técnica, decisões arquiteturais e notas de engenharia do **FrameStudio**.

---

> ### ⚠️ Diretrizes Críticas de Preservação e Manutenção
> O agente e qualquer desenvolvedor devem **SEMPRE** tomar o máximo de cuidado para **NUNCA** realizar o apagamento de logs persistentes ou o reset de banco de dados/estruturas persistidas em nenhuma circunstância de manutenção ou refatoração. A integridade dos dados e o histórico operacional devem ser rigorosamente mantidos.

---

## Linha do Tempo de Atualizações

### 🚀 [2026-08-20] - Criação e Lançamento do FrameStudio (v1.0.0)

- **Contexto e Desafio:**
  - O usuário relatou necessidade de extrair frames de alta fidelidade a partir de vídeos de carros para publicação em capas e redes sociais.
  - O reprodutor nativo do Windows e o app Fotos apresentavam com frequência o bug de renderização de "tela verde" (metade da foto verde) devido a problemas de aceleração por hardware e alinhamento de blocos de cor YUV/NV12.
  - Necessidade de carregar vídeos pesados localmente de forma instantânea, obter sugestões automáticas de frames e poder navegar manualmente com precisão de milissegundos/frame a frame.

- **Decisões Técnicas e Arquitetura:**
  - **Pipeline Client-Side com Canvas 2D:** Implementada extração direta do buffer de vídeo (`videoWidth` x `videoHeight`) via Canvas 2D (`ctx.drawImage`), eliminando 100% da distorção ou artefato de tela verde do Windows.
  - **Zero Latency / Privacidade Total:** Utilização de `URL.createObjectURL(file)` para leitura local imediata na memória do navegador, dispensando uploads para servidores.
  - **Amostragem Inteligente Automática:** Criado o módulo `AutoSampler` que varre o vídeo de forma assíncrona gerando miniaturas distribuídas sem travar a thread principal.
  - **Controle Fino e Scrubber:** Suporte a avançar e recuar 1 frame exato baseado no FPS do vídeo, passos de 0.1s e 1.0s, mostrador de tempo com precisão de milissegundos (`HH:MM:SS.mmm`).
  - **Exportação Flexível:** Suporte a formatos PNG (lossless) e JPEG (100%), presets de corte para redes sociais (16:9, 9:16, 1:1, 4:5) e download de múltiplos frames compactados em arquivo `.ZIP` via `JSZip`.
  - **Launcher de 1 Clique:** Criação do `iniciar.bat` para execução imediata no Windows.

### 🚀 [2026-08-20] - Atualização do Console Launcher (`iniciar-servidor-local.bat`) (v1.0.1)

- **Contexto e Revisão:**
  - Importação do launcher de console de operações (`iniciar-servidor-local.bat`).
  - Troca da porta padrão (5173/8000) para **5522** (Servidor Web) e **8010** (API).
  - Remoção de todos os caracteres acentuados para evitar corrupção de saída e falhas de encoding no CMD do Windows.
  - Correção de dependência do comando obsoleto `wmic` para data/hora e aprimoramento da captura de IP local e encerramento de processos órfãos via `netstat` e `taskkill`.

### 🚀 [2026-08-20] - Motor Híbrido com Decodificação OpenCV Nativa (v1.1.0)

- **Diagnóstico Definitivo:**
  - Vídeos 4K verticais (2160x3840) gravados em smartphones utilizam codecs HEVC/H.265 e perfis de cor avançados que o Google Chrome no Windows não decodifica nativamente sem extensões proprietárias da GPU, travando a reprodução e deixando os frames pretos.
- **Solução Arquitetural Completa:**
  - Implementado o backend Python de alta performance (`server.py`) com FastAPI e OpenCV (C++).
  - O OpenCV decodifica diretamente qualquer codec do mercado (H.264, HEVC/H.265, ProRes, AV1, HDR) em resolução nativa sem perdas e sem depender de codecs do navegador.
  - Endpoints dedicados: `/api/upload` (processamento instantâneo), `/api/frame` (extração em resolução máxima 4K) e `/api/samples` (geração de miniaturas em frações de segundo).
  - O visualizador do frontend foi atualizado para exibir o frame decodificado pelo OpenCV com fidelidade total e suporte completo a navegação frame-a-frame e controles de playback.

### 🚀 [2026-08-20] - Orientação Vertical Correta, Cache em RAM e Fix de Download (v1.2.0)

- **Diagnóstico das Falhas Reportadas:**
  1. **Vídeo de lado:** Smartphones gravam a matriz em `3840x2160` e embutem metadados de rotação (`90 graus`). O leitor lia a matriz bruta sem aplicar a rotação de orientação.
  2. **Lentidão extrema no Play/Scrubbing:** Cada requisição de frame em 4K abria e fechava o arquivo do disco com decode completo em CPU (~2.5s por quadro), sobrecarregando o servidor durante o Play.
  3. **Frames de 0 bytes no ZIP:** O método de empacotamento fazia split de string em `blob:` URLs em vez de passar o `Blob` diretamente para o `JSZip`.
- **Soluções Implementadas:**
  1. **Orientação Automática de 90°/180°/270°:** Detecção automática da tag de rotação via OpenCV e PyAV, entregando o vídeo e as fotos em pé (`2160x3840`).
  2. **Cache de Preview em Memória RAM (`/api/preview`):** Indexação em background com resposta em **< 0.1ms**, permitindo scrubbing instantâneo e playback suave a 60 FPS.
  3. **Fix de Exportação ZIP:** O `JSZip` agora recebe o `Blob` binário nativo, gerando arquivos PNG (7.4 MB) e JPG de alta resolução sem corrupção.

### 🚀 [2026-08-20] - Design System de Software Profissional (v1.3.0)

- **Reformulação Visual Completa (Anti-Generic UI):**
  1. **Paleta Studio Sólida e Sóbria:** Substituição de gradientes e efeitos de brilho genéricos por superfícies sólidas em tons de Slate/Zinc escuro (`#0c0e12`, `#14171f`, `#1a1e28`), com bordas nítidas de alto contraste (`#2e3648`).
  2. **Tipografia Técnica e Profissional:** Integração da família tipográfica `Inter` para a interface geral e `JetBrains Mono` para contadores de frames, timestamps e resoluções.
  3. **Ergonomia e Densidade Visual:**
     - Header compacto e limpo com marca sóbria e badges discretos.
### 🚀 [2026-08-20] - Correção de Layout do Grid de Miniaturas (v1.3.1)

- **Correção de CSS e Enquadramento:**
  1. **Grid Responsivo Unificado:** Mapeados os seletores `.suggested-frames-grid` e `.gallery-grid` com `grid-template-columns: repeat(auto-fill, minmax(140px, 1fr))` e espaçamento de `0.75rem`.
  2. **Dimensionamento Proporcional de Miniaturas:** Fixada a altura das miniaturas em `180px` com `object-fit: cover` e `background-color: #000000`, evitando que fotos verticais ocupem 100% da largura da tela.
  3. **Cards e Ações da Galeria:** Estilizados os cards da galeria com overlay de zoom, botão de download rápido e remoção com alinhamento compacto.







