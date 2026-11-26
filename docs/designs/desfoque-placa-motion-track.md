# Desfoque de placa com rastreamento, corte e áudio no Media Studio

*   **Autor:** Raphael Martins (com revisão arquitetural EGM)
*   **Status:** Aprovado para implementação (v1)
*   **Data:** 2026-11-25
*   **Issue / Item:** [#1](https://github.com/raphael-c-martins/media-studio/issues/1) · Notion `ID-011`

--------------------------------------------------------------------------------

## Visão geral

O **Media Studio** passa a oferecer na aba **Frames** o fluxo completo e local para ocultar placas em vídeos em movimento (rastreamento 2D com correção manual por quadros-chave), além de corte temporal (`trim`), controle de áudio (preservar ou silenciar) e aplicação opcional do recorte/proporção (`4:5`, `9:16`, `1:1`, `16:9`) na exportação em **MP4**.

Todo o processamento roda na própria máquina via **OpenCV** e **PyAV** (`av==15.1.0`), sem enviar mídia para fora, sem depender de agentes de IA e sem consumir tokens no preparo recorrente de vídeos para o **@reliquiasitaborai**.

## O problema e a solução proposta

No piloto do post da Mercedes (`06 - Piloto da Mercedes.md`), foi necessário ocultar a placa traseira com a câmera em movimento antes de publicar. Até então, o processo exigia escrever scripts avulsos ou acionar um agente a cada clipe. Além do custo de tokens e dependência externa, pequenos trechos em que a placa gira, entra pelo canto ou reaparece precisam de conferência visual imediata.

A solução integra o rastreamento e a renderização diretamente na aba **Frames**:
1. O usuário pausa o vídeo onde a placa está nítida e desenha uma ou mais caixas de máscara sobre a prévia.
2. O backend rastreia cada máscara ao longo do intervalo escolhido usando correlação de template nativa (`cv2.TM_CCOEFF_NORMED`) com janela local, subamostragem a 30 fps e micro-escalas, devolvendo os pontos com pontuação de confiança.
3. Na linha do tempo, o usuário navega entre os quadros, ajusta manualmente a caixa em qualquer ponto (criando um quadro-chave `manual`) ou marca *"Ocultar daqui em diante"* quando o carro sai de cena.
4. Na exportação, o backend aplica as máscaras no quadro original orientado, aplica o recorte opcional (se marcado), garante dimensões pares em `yuv420p` e exporta o MP4 com H.264 (`libx264`) e áudio AAC sincronizado (ou silenciado).

## Objetivos

*   Permitir marcar, ajustar, rastrear e ocultar placas em vídeos reais de celular (`.mp4`, `.mov` verticais com rotação e VFR) direto pela interface web em `http://127.0.0.1:8810`.
*   Suportar múltiplas trilhas de máscara simultâneas no mesmo vídeo (ex.: placa principal + segundo veículo no canto).
*   Permitir corte temporal (`trim_start`, `trim_end`), opção explícita de silenciar o áudio (`mute_audio`) e opção de aplicar a proporção/enquadramento da aba Frames (`4:5`, `9:16`, `contain_blur`).
*   Entregar prévia reproduzível do MP4 gerado em modal próprio com download direto, preservando o arquivo original intacto e sem deixar sobras temporárias ou vazamento de memória.
*   Garantir segurança (CSRF `X-Media-Studio: 1`, validação estrita Pydantic `extra="forbid"`, limites de RAM/CPU e guarda de sessão ativa).

## Fora de escopo na v1

*   Detecção automática de placas por modelos neurais/ONNX ou download de pesos externos (`YOLO`, `Nano`, `Vit`).
*   Persistência de projetos de edição ou fila assíncrona em SQLite entre reinicializações do servidor.
*   Edição de múltiplas faixas de áudio externas, trilhas musicais ou transições entre vários clipes.

## Jornadas críticas (CUJs)

### CUJ 1: Flagra em movimento com ocultação de placa
*   **Dado que** um vídeo vertical (`1080x1350` ou `1080x1920` `.mov`/`.mp4`) foi carregado na aba **Frames**.
*   **Quando** o usuário pausa num quadro nítido, clica em **Marcar placa**, desenha o retângulo sobre a placa, aciona **Rastrear vídeo**, confere os pontos incertos (se houver) e clica em **Exportar vídeo (MP4)**.
*   **Então** o servidor devolve um MP4 compatível (`H.264` + `yuv420p`), com a placa ilegível em todo o percurso, duração preservada e áudio original sincronizado (ou ausente se não houver faixa de áudio).

### CUJ 2: Placa que sai de cena, retorna ou muda de ângulo
*   **Dado que** uma trilha já foi rastreada, mas a placa some atrás de um obstáculo ou gira no final do clipe.
*   **Quando** o usuário salta até o ponto onde a máscara se perdeu, ajusta a caixa manualmente (ou clica em **Ocultar daqui em diante** / **Rastrear daqui pra frente**).
*   **Então** os quadros anteriores permanecem preservados, nenhuma interpolação fantasma atravessa trechos ocultos (`visible=false`) e a reexportação reflete a correção exata.

### CUJ 3: Corte de trecho, silenciamento de áudio e recorte 4:5
*   **Dado que** um vídeo longo de celular (`16:9` ou `9:16` com som ambiente indesejado) está aberto.
*   **Quando** o usuário marca **Início** e **Fim** do trecho, marca **Silenciar áudio** e ativa **Aplicar recorte e proporção acima ao vídeo**.
*   **Então** as máscaras são aplicadas no espaço original antes do recorte `4:5` (inclusive em `contain_blur`, evitando vazar a placa no fundo desfocado), o MP4 final tem duração `trim_end - trim_start`, dimensões pares e zero faixas de áudio.

## Arquitetura técnica e contratos

```text
[ Navegador (frames.js + video-blur.js) ]
   |-- GET  /api/frames/videos/{id}/preview?exact=true   --> header X-Frame-Time (s)
   |-- POST /api/frames/videos/{id}/track (X-Media-Studio: 1)
   |        '-- BlurBoxIn + anchor_time (s) + direction
   |            --> asyncio.to_thread(track_region_in_video) [OpenCV matchTemplate + PyAV]
   |            <-- keyframes [{t, x, y, w, h, visible, source, confidence}]
   |-- POST /api/frames/videos/{id}/export-video (X-Media-Studio: 1)
            '-- tracks[] + trim + mute_audio + crop
                --> asyncio.to_thread(export_processed_video) [PyAV H.264 + AAC]
                <-- FileResponse (MP4) + BackgroundTask(_safe_unlink)
```

### Decisões-chave de engenharia (incorporando revisão EGM)

1. **Chave canônica temporal em segundos (`t: float`):** O frontend permite alterar `#select-fps` e vídeos de celular usam taxa de quadros variável (VFR). Por isso, todas as âncoras, keyframes e interpolações usam o timestamp real `pts * time_base` em segundos, e não índices inteiros de quadro.
2. **Orientação unificada e saída compatível (`yuv420p` par):** Quadros decodificados via PyAV não aplicam rotação automática de metadado; `orient_pyav_frame` corrige `90/180/270` antes de rastrear e desfocar, e o MP4 gravado sai já rotacionado nos pixels com dimensões truncadas para múltiplo de 2 (`dim & ~1`) e `pix_fmt="yuv420p"` (evitando falhas no Instagram/WhatsApp/Safari).
3. **Rastreador híbrido offline (`matchTemplate`):**
   - Trabalha em escala cinza reduzida (lado maior `640px`, largura mínima `360px` quando disponível) e subamostragem máxima de `30 fps`.
   - Usa faixa de contexto (`1.35x` da caixa) e velocidade amortecida (`0.5 * prev_v`), testando micro-escalas (`0.96, 1.0, 1.04`) periodicamente e comparando sempre contra o template inicial (`tpl_init`) antes de atualizar `tpl_curr`, evitando drift para o para-choque.
   - A passagem *backward* usa buffer limitado (`MS_MAX_BACKWARD_BUFFER = 600` quadros); a passagem *forward* roda em streaming `O(1)`.
   - Lacunas com `visible=False` após 3 quadros abaixo de `0.42` interrompem a interpolação (sem borrões fantasmas entre pontos ocultos).
4. **Áudio re-encodado para AAC (`av.AudioResampler`):** Em vez de remux condicional (que falha com Opus em `.webm`/`.mkv`, PCM em `.mov` ou edit lists de iPhone), qualquer faixa de áudio com `mute_audio=False` é decodificada no intervalo `[t0, trim_end]`, reamostrada para `fltp` com `frame_size` do AAC (`160 kbps`) e rebaseada para `PTS = 0`. Vídeos sem stream de áudio não falham mesmo com `mute_audio=False`.
5. **Proteção de sessão e layers no `#player`:**
   - `VideoSession.hold()` impede que `cleanup_loop` ou a evicção por `MAX_FRAME_SESSIONS` fechem/apaguem o arquivo temporário durante `track` ou `export-video`. Um bloqueio por `video_id` devolve `409 Conflict` em chamadas simultâneas sobre o mesmo vídeo.
   - Matriz de precedência no `#player`: **Lupa (`loupe`) > Modo marcar placa (`blur-drawing`, que desliga `pointer-events` no `#crop-guide`) > Guia de recorte (`#crop-guide`) > Clique de play/foco no `#frame-view`**.
   - Em `#blur-overlay`, `ResizeObserver` mantém o retângulo alinhado exatamente a `offsetLeft/offsetTop/clientWidth/clientHeight` do `#frame-view`.
   - A exceção em `shortcuts.js` vale apenas para `#timeline`, evitando conflito das setas em sliders de desfoque/margem/zoom.

### Alternativas consideradas

*   **`opencv-contrib-python` (`TrackerCSRT`):** Rejeitado na v1 porque o ambiente já fixa `opencv-python-headless==4.11.0.86` (sem `contrib`), o `TrackerCSRT` não está disponível sem trocar pacotes e o piloto real da Mercedes já comprovou eficácia com `matchTemplate`.
*   **Subprocesso `ffmpeg` CLI para filtro/encode:** Rejeitado para a v1 porque o rastreamento e a interpolação quadro a quadro por keyframes acontecem em Python/NumPy de toda forma; manter tudo em **PyAV** evita montar filtros complexos com dezenas de `enable='between(t,...)'` em linha de comando e respeita exatamente o mesmo código de recorte/orientação do `engine.py`.
*   **Remux direto de áudio:** Rejeitado na v1 pelos riscos de incompatibilidade entre `.mov`/`.webm`/VFR e cortes que não caem em limites de pacote AAC.

## Requisitos não-funcionais

*   **Segurança:** Cabeçalho `X-Media-Studio: 1` obrigatório nas novas rotas `POST`; modelos Pydantic com `ConfigDict(extra="forbid")` e checagem `math.isfinite`; teto de `10` trilhas, `3000` keyframes/trilha, `1800` amostras no rastreamento e lado máximo de `1920px` na exportação; exclusão segura de `ms_exp_*.mp4` via `BackgroundTask` + varredura periódica em `cleanup_stale_exports()`.
*   **Desempenho e memória:** Processamento fora do Event Loop via `asyncio.to_thread`; URL de `Blob` no modal sempre liberada com `URL.revokeObjectURL` ao fechar/substituir.

## Plano de arquivos

### Backend (`D:\Projetos\media-studio\backend\`)
1. `app/config.py` (Modificar): constantes `MS_MAX_TRACK_SAMPLES`, `MS_MAX_BACKWARD_BUFFER`, `MS_MAX_BLUR_TRACKS`, `MS_MAX_EXPORT_DIMENSION`.
2. `app/frames/registry.py` (Modificar): `VideoSession.hold()`, `is_busy`, proteção na evicção/expiração e `cleanup_stale_exports()`.
3. `app/frames/engine.py` (Modificar): `orient_pyav_frame()`, detecção de rotação segura no `probe_video()` e `read_preview_exact()`.
4. `app/frames/routes.py` (Modificar): parâmetro `exact` e cabeçalho `X-Frame-Time` em `/preview`, chamada a `cleanup_stale_exports()`.
5. `app/frames/video_blur.py` (Criar): `resolve_box_at_time`, `apply_masks_to_frame`, `track_region_in_video`, `export_processed_video`.
6. `app/frames/video_routes.py` (Criar): schemas Pydantic estritos e rotas `POST /api/frames/videos/{video_id}/track` e `/export-video`.
7. `app/main.py` (Modificar): registrar `video_routes.router`.

### Frontend (`D:\Projetos\media-studio\frontend\`)
1. `index.html` (Modificar): `#blur-overlay`, `#panel-video-edit` e `#video-export-modal`.
2. `css/app.css` (Modificar): estilos sóbrios das caixas, alças, lista de trilhas, trim e player do modal.
3. `js/core/api.js` (Modificar): suporte opcional a `signal` externo em `request()`.
4. `js/frames/shortcuts.js` (Modificar): restringir exceção de range a `#timeline`.
5. `js/frames/video-blur.js` (Criar): desenho/arrasto/redimensionamento de caixas, rastreamento bidirecional e para frente, ocultação, trim, áudio e modal de exportação.
6. `js/frames/frames.js` (Modificar): integração de ciclo de vida, `/preview?exact=true`, `seek`, `updateCropGuide` e `closeModals`.

### Documentação e testes
1. `docs/designs/desfoque-placa-motion-track.md` (Criar): este documento de design.
2. `backend/tests/test_video_blur.py` (Criar): testes unitários e de API com vídeos PyAV sintéticos (rastreamento, interpolação com lacuna, `pixelate`/`blur`/`solid`, trim, áudio AAC e mudo, vídeo sem áudio, rotação `90°`/`180°`, dimensões ímpares, `4:5` + `contain_blur`, CSRF `403`, Pydantic `422`, `404`, `hold()` e limpeza).
3. `backend/e2e/test_frames_e2e.py` (Modificar): cenário Playwright E2E completo (upload, desenho, rastreamento, silenciar áudio, exportação MP4 e download com telemetria limpa).
4. `README.md` e `HISTORICO.md` (Modificar): documentação PT-BR acessível da nova funcionalidade.

## Plano de verificação

*   `backend/.venv/Scripts/python.exe -m pytest -q` (todos os testes unitários e de API).
*   `backend/.venv/Scripts/python.exe -m pytest e2e -v` (suíte Playwright headless).
*   Smoke isolado somente leitura no clipe pré-desfoque de referência da Mercedes gravando saída temporária em `%TEMP%` e validando quadros, dimensões e duração antes de apagar a cópia temporária.
*   Checks do GitHub Actions no Pull Request (`Testes (Python)` + `gitleaks`).

--------------------------------------------------------------------------------

*Rascunho estruturado e revisado com EGM*
