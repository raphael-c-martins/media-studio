# Media Studio

Ferramenta local do Relíquias para preparar mídia para as redes. Junta em um só lugar os antigos **MediaDownloader Pro** e **FrameStudio (video-frame-extrator)**:

- **Baixar**: vídeos, áudios e fotos do YouTube, Instagram (posts, Reels e carrosséis), X, TikTok e outros sites suportados pelo yt-dlp. Também lista as publicações de um perfil para baixar várias de uma vez.
- **Frames**: abre um vídeo do computador e captura quadros em resolução original, com corte para 16:9, 9:16, 1:1 e 4:5, sequência para carrossel, sugestões automáticas e lupa de foco.
- **Histórico** dos downloads e **Configurações** (pasta de destino, qualidade padrão e tema claro/escuro).

Tudo roda neste computador. Os vídeos enviados para o extrator não saem da máquina.

## Como usar

1. Dê dois cliques em `iniciar-servidor-local.bat`.
2. Na primeira vez, escolha `[4]` para criar o ambiente e instalar as dependências.
3. Escolha `[1]`: o servidor sobe em segundo plano e o navegador abre em `http://localhost:8810`.
4. Para desligar, abra o mesmo arquivo e escolha `[2]`.

Pelo terminal:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd backend
..\.venv\Scripts\python.exe -m app
```

Requisitos: Windows 10/11 e Python 3.11. O FFmpeg é baixado automaticamente pelo pacote `static-ffmpeg` na primeira execução.

## Configuração (variáveis de ambiente, todas opcionais)

| Variável | Padrão | Para que serve |
|---|---|---|
| `MS_PORT` | `8810` | Porta do servidor |
| `MS_HOST` | `127.0.0.1` | Endereço de escuta. Qualquer valor fora da própria máquina exige `MS_ACCESS_TOKEN` |
| `MS_ACCESS_TOKEN` | (vazio) | Token de acesso pela rede (mínimo 24 caracteres). Abra `http://IP:PORTA/?token=...` uma vez para criar a sessão |
| `MS_MAX_UPLOAD_MB` | `4096` | Tamanho máximo de vídeo no extrator |
| `MS_MAX_DIRECT_MEDIA_MB` | `1024` | Tamanho máximo de fotos/vídeos baixados direto (Instagram) |
| `MS_FRAME_SESSION_TTL_MIN` | `30` | Minutos sem uso até liberar um vídeo do extrator |
| `MS_MAX_FRAME_SESSIONS` | `4` | Vídeos abertos ao mesmo tempo no extrator |
| `MS_MAX_CONCURRENT_DOWNLOADS` | `3` | Downloads simultâneos |

## Segurança

- Por padrão o servidor só aceita conexões da própria máquina e recusa requisições endereçadas a outros nomes de site (proteção contra DNS rebinding).
- Toda ação que altera algo exige o cabeçalho `X-Media-Studio`, que outros sites não conseguem enviar. Não há CORS liberado.
- Links externos são conferidos antes de qualquer acesso: endereços da rede local ou internos são recusados.
- Só arquivos de mídia podem ser abertos, entregues ou apagados pelo histórico. Pastas do sistema não podem ser usadas como destino.
- A interface monta o conteúdo sem `innerHTML`; títulos e legendas vindos da internet nunca viram código. A página roda com Content-Security-Policy restrita e sem scripts de terceiros.

## Estrutura

```text
media-studio/
├── backend/
│   ├── app/
│   │   ├── main.py            # app FastAPI, inicialização e rotas
│   │   ├── config.py          # caminhos, limites e variáveis MS_*
│   │   ├── security.py        # acesso local, cabeçalho anti-CSRF, token de rede
│   │   ├── net_guard.py       # validação de links externos e downloads com limite
│   │   ├── database.py        # SQLite com migrations incrementais
│   │   ├── downloads/         # yt-dlp, Instagram, fila, histórico, configurações
│   │   └── frames/            # extrator: motor OpenCV/PyAV, sessões e rotas
│   ├── tests/                 # testes automatizados (pytest)
│   └── requirements.txt
├── frontend/                  # HTML, CSS e módulos JS (sem build)
├── docs/                      # históricos dos projetos originais e ideias
├── data/                      # banco local (fora do Git)
├── downloads/                 # pasta padrão dos downloads (fora do Git)
├── logs/                      # logs (fora do Git)
└── iniciar-servidor-local.bat
```

## Testes

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
```

Os testes usam banco, logs e pastas temporárias, nunca os dados reais.

## Licença

MIT. Veja [LICENSE](LICENSE).
