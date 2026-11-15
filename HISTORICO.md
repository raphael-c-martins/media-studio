# Histórico do Media Studio

Registro das decisões do projeto. O histórico completo de cada ferramenta antes da união está em:

- [docs/HISTORICO-media-downloader.md](docs/HISTORICO-media-downloader.md)
- [docs/HISTORICO-video-frame-extrator.md](docs/HISTORICO-video-frame-extrator.md)

---

## Diretrizes de preservação (leia antes de qualquer manutenção)

> **Nunca apagar, resetar ou recriar o banco de dados (`data/media_studio.db`) e nunca apagar os logs em `logs/`.**
>
> - Mudanças na estrutura do banco entram só como migrations novas na lista `MIGRATIONS` de `backend/app/database.py`. As existentes não são alteradas.
> - Testes usam banco e pastas temporárias. Para testar com o servidor real, use uma cópia do banco.
> - A pasta `temp/frames` guarda só cópias temporárias de vídeos enviados ao extrator e pode ser limpa pelo próprio sistema.

---

## Linha do tempo

### [14/11/2026] - Preparo de fotos (.HEIC), EXIF e recorte por ponto focal (4:5)
- Adicionado suporte completo a fotos estáticas (`JPG`, `PNG`, `WebP`, `.HEIC`/`.HEIF`) via `pillow==13.0.0` e `pillow-heif==1.8.1`, com leitura segura de caminhos Unicode no Windows, transposição obrigatória de rotação `EXIF`, conversão de perfil de cor (ex.: `Display P3` para `sRGB`) e limite configurável contra bombas de pixels (`MS_MAX_IMAGE_PIXELS`, padrão `120000000`, nunca ilimitado).
- Adicionado recorte inteligente por ponto focal (`focus_x`, `focus_y`), `zoom` (`1.0` a `4.0`), padronização opcional de resolução para Instagram (ex.: `1080x1350` em `4:5` usando `INTER_AREA`/`INTER_LANCZOS4`), modo `contain_blur` (fundo desfocado sem cortar bordas do veículo) e avisos automáticos de geometria (`wide_crop` e `low_resolution`).
- Criadas rotas dedicadas `/api/frames/images` (upload, prévia, análise de geometria e corte sob demanda com proteção anti-CSRF), novos parâmetros de foco/zoom também nas rotas de vídeo e CLI em lote `python -m app.frames.batch_cli` (manifesto JSON ou pasta, `--dry-run`, `--strict`, preservação de originais sem sobrescrita usando `unique_path` e bloqueio de pastas de sistema).
- Atualizada a interface da aba **Frames** para aceitar vídeos e fotos, arrastar o quadro de recorte no ponto focal ou clicar na imagem para posicionar o foco, ajustar zoom/encaixe/padronização e exibir avisos antes de exportar.
- Adicionada bateria de testes automatizados (`tests/test_image_frames.py` e `tests/test_frames_batch_cli.py`) cobrindo `.HEIC`, `EXIF`, bomba de pixels, CSRF, rejeição clara de `.dng`, remoção de sessões excedentes e fluxo em lote.

### [23/10/2026] - CI no GitHub e proteção de pastas no Linux

- **CI:** a cada envio, o GitHub Actions roda os 64 testes, a busca de segredos (gitleaks) e o `pip-audit` (só informativo).
- **Problema encontrado pelo CI:** a regra que impede escolher uma pasta do sistema como destino só conhecia pastas do Windows. Rodando em Linux (como no CI ou num servidor Ubuntu), `/etc`, `/usr` e outras eram aceitas. Agora também são recusadas, e os testes usam a pasta de sistema certa para cada sistema operacional.

### [22/10/2026] - Atalhos do extrator reduzidos ao básico

- **Por quê:** a regra de "One-Hand Workflow" saiu das diretrizes globais; os atalhos extras quase não eram usados e poluíam a tela com etiquetas de tecla.
- **Ficou:** espaço reproduz/pausa, setas andam um quadro e Esc fecha janelas.
- **Saiu:** botão e janela de Atalhos, teclas C, I, O, B, Z, K e ?, combinações Alt/Shift + setas e as etiquetas de tecla nos botões. Todas as funções continuam nos botões da tela.

### [22/10/2026] - União do MediaDownloader Pro e do FrameStudio no Media Studio (v2.0.0)

**Por quê:** as duas ferramentas eram usadas juntas para o Relíquias (baixar o vídeo e depois tirar frames), mas rodavam separadas, com portas, estilos e manutenção duplicados. Uma auditoria também encontrou falhas de segurança importantes no MediaDownloader.

**Histórico:** os commits dos dois repositórios foram preservados. O arquivo `media_downloader.db`, que existia no histórico do repositório antigo com a lista de downloads, foi retirado do histórico novo antes da publicação, porque o repositório novo é público. Os repositórios originais continuam intactos (arquivados).

**Arquitetura:**

- Um único servidor FastAPI (porta 8810) serve a API e a interface. Acabou o Vite e a porta separada do frontend.
- Backend dividido em `downloads/` e `frames/`, com `security.py` e `net_guard.py` compartilhados.
- Banco com tabela `schema_migrations`; o banco antigo pode ser copiado para `data/` sem conversão.
- Interface nova, única para as duas ferramentas: abas Baixar, Histórico, Frames e Configurações; identidade do Relíquias (carvão, branco e laranja sóbrio), fonte do sistema, sem emojis, sem gradientes, tema claro/escuro.
- `.zip` dos frames gerado por um módulo próprio (`core/zip.js`), no lugar da biblioteca JSZip carregada de CDN: funciona offline e permite CSP sem scripts externos.
- Removidos: módulo de resumo por IA (DeepSeek), que não tinha tela; scripts de teste soltos; os cinco temas antigos.

**Segurança corrigida:**

- O MediaDownloader escutava em `0.0.0.0` sem login. Pela rede era possível mudar a pasta de download para qualquer lugar, baixar um arquivo e mandar o Windows abri-lo. Agora: só `127.0.0.1` (rede exige token forte), bloqueio de host externo, cabeçalho obrigatório em ações, pasta de destino validada e abertura só de arquivos de mídia.
- `GET /api/settings` devolvia a chave da DeepSeek. Agora só devolve quatro campos fixos, e a gravação aceita apenas esses campos.
- A rota de miniatura buscava qualquer endereço, inclusive da rede interna (SSRF). Agora todo link externo passa por `net_guard`, inclusive em cada redirecionamento, com limite de tamanho.
- O yt-dlp rodava com verificação de certificado desligada (`nocheckcertificate`). Voltou a verificar.
- Títulos e legendas vindos dos sites eram inseridos com `innerHTML` (XSS). A interface nova monta tudo como texto.
- Extrator: upload em blocos com limite, sessões que expiram e apagam o temporário, decodificação fora do loop principal, parâmetros validados, sem CORS aberto e sem servir a pasta do projeto inteira.

**Bugs corrigidos:**

- Corte de trecho com `00:00:10` quebrava o download (o yt-dlp recebia texto em vez de segundos). Agora aceita `SS`, `MM:SS` e `HH:MM:SS`.
- Downloads que estavam na fila quando o servidor parava ficavam "baixando" para sempre. Agora viram "erro" na inicialização.
- Cancelar um download podia ser sobrescrito por "erro"; cancelar algo inexistente respondia sucesso.
- Arquivos com o mesmo nome eram sobrescritos sem aviso. Agora ganham `(2)`, `(3)`...
- Burst salvava JPEG com extensão `.png`; o formato WebP virava JPEG sem avisar.
- O botão de atalhos do extrator não abria o modal (ids trocados); Esc não fechava a visualização do frame.
- Durante a indexação, a prévia podia mostrar um quadro distante do ponto escolhido.

**Testes:** 64 testes automatizados (segurança, validação de links, modelos, pastas, rotas de histórico e configurações, banco e extrator com vídeo sintético). Fluxo testado no navegador: busca e download com corte de trecho, histórico, configurações, tema escuro, extrator com atalhos, captura, sequência e .zip.
