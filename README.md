# MediaDownloader Pro

Aplicativo moderno, assíncrono e de alta densidade para download e processamento de vídeos e áudios de plataformas online (YouTube, Instagram, Twitter/X, TikTok e mais de 1.800 sites suportados via yt-dlp).

---

## ✨ Funcionalidades (Features)

- **Extração Universal de Mídias:** Compatível com YouTube, Instagram (Reels, Posts, Carrossel), Twitter/X, TikTok, Reddit, Facebook, Twitch e mais de 1.800 plataformas.
- **Inspeção Prévia de URL:** Obtenha título, autor, miniatura, duração e lista de resoluções disponíveis antes de iniciar o download.
- **Seleção Granular de Formato:** Opções de melhor qualidade automática (*Best*), 4K, 1080p, 720p, 480p ou extração direta de áudio (MP3, M4A, Opus, WAV, FLAC).
- **Corte de Vídeo por Intervalo (Time-Range):** Defina tempo inicial e final (ex: `00:00:10` a `00:01:30`) para baixar apenas o trecho desejado.
- **Fila Assíncrona de Downloads:** Acompanhe em tempo real velocidade de transferência, porcentagem, tamanho do arquivo e tempo estimado (ETA) via Server-Sent Events (SSE).
- **Histórico Persistente:** Armazenamento seguro em banco de dados SQLite com busca rápida, filtros e botão de abertura direta no Windows Explorer.
- **Resumo Inteligente com IA (DeepSeek):** Integração com DeepSeek AI para transcrição estruturada, tópicos principais e insights de vídeos.
- **Launcher Local Automatizado:** Inicialização rápida com controle de processos, gerenciamento de ambiente virtual e logs de execução.

---

## 🛠️ Tecnologias Utilizadas

- **Frontend:** HTML5 Semântico, CSS3 Moderno (Design System de alta densidade, variáveis CSS, temas e animações fluidas), Vanilla JavaScript SPA e Vite na porta **3030**.
- **Backend:** Python 3.11+, FastAPI (totalmente assíncrono), Uvicorn na porta **8800**, `aiosqlite` para persistência e `pydantic` para validação rigorosa de schemas.
- **Processamento de Mídia:** `yt-dlp` e `FFmpeg`.
- **Inteligência Artificial:** API DeepSeek / LLM Service para sumarização e análise de conteúdo.

---

## 🚀 Como Iniciar (Desenvolvimento)

### 1. Inicialização Automática (Recomendado)
Basta dar dois cliques no arquivo **`iniciar-servidor-local.bat`** na raiz do projeto. O script irá:
1. Criar o ambiente virtual Python (`.venv`) caso não exista.
2. Instalar automaticamente as dependências de backend e frontend.
3. Iniciar o Backend na porta `8800` e o Frontend na porta `3030`.
4. Abrir automaticamente a aplicação no navegador em `http://localhost:3030`.

### 2. Inicialização Manual

#### Backend
```powershell
# Criar e ativar ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Instalar dependências
pip install -r backend/requirements.txt

# Iniciar servidor FastAPI
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8800
```

#### Frontend
```powershell
cd frontend
npm install
npm run dev
```

---

## 📂 Organização do Projeto

```
media-downloader/
├── backend/
│   ├── app/
│   │   ├── api/             # Rotas modulares (downloads, info, history, ai, settings, health)
│   │   ├── services/        # Motores yt-dlp, FFmpeg, Fila assíncrona e DeepSeek AI
│   │   ├── config.py        # Configurações do servidor e caminhos
│   │   ├── database.py      # Conexão SQLite assíncrona e migrações
│   │   ├── models.py        # Schemas de validação Pydantic
│   │   └── main.py          # Ponto de entrada FastAPI e lifespans
│   └── requirements.txt     # Dependências Python
├── frontend/
│   ├── src/
│   │   ├── style.css        # Design System completo e responsivo
│   │   └── main.js          # Lógica SPA com SSE em tempo real
│   ├── index.html           # Interface web de alta densidade
│   ├── package.json         # Dependências do frontend
│   └── vite.config.js       # Configuração do Vite (porta 3030)
├── logs/                    # Logs persistentes de execução
├── downloads/               # Diretório padrão de mídias salvas
├── iniciar-servidor-local.bat # Launcher do sistema para Windows
├── README.md                # Este manual de operação
├── HISTORICO.md             # Diário de decisões e regras de integridade
└── .gitignore               # Proteção de credenciais, logs e temporários
```

---

## 🔒 Diretrizes de Segurança e Integridade

- **Sanitização de URLs:** Todas as entradas passam por validação estrita para evitar injeções de comando e requisições maliciosas.
- **Consultas Parametrizadas:** Proteção contra SQL Injection em todas as operações com SQLite.
- **Preservação de Dados:** O banco de dados e os logs persistentes são preservados entre reinicializações do sistema.
