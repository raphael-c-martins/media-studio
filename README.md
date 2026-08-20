# FrameStudio PRO - Extrator de Frames de Alta Precisão 🎬🚗

<div align="center">

[![Open Source](https://img.shields.io/badge/Open%20Source-100%25-brightgreen.svg)](https://github.com/)
[![Privacidade](https://img.shields.io/badge/Privacidade-Zero%20Data%20Collection-blue.svg)](https://github.com/)
[![Processamento Local](https://img.shields.io/badge/Processamento-100%25%20Offline%20%26%20Local-orange.svg)](https://github.com/)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Licença MIT](https://img.shields.io/badge/Licen%C3%A7a-MIT-yellow.svg)](LICENSE)

**Uma ferramenta gratuita, de código aberto e focada em privacidade para criadores de conteúdo, páginas automotivas e editores.**

</div>

---

## 🎯 Por que o FrameStudio existe?

O **FrameStudio PRO** nasceu de uma necessidade real: **extrair o frame perfeito de um vídeo sem complicação, sem perda de nitidez e sem bugs**.

Muitos criadores de conteúdo automotivo e videomakers sofrem com:
- O visualizador padrão do Windows gerando a clássica **tela metade verde** por falhas de decodificação YUV.
- Vídeos gravados em smartphones em 4K vertical ficando com **tela preta** ou virados de lado (devido a codecs HEVC/H.265 e tags de orientação).
- Ferramentas online que exigem upload de vídeos pesados de vários gigabytes, comprimem a imagem ou cobram assinaturas caras.

O FrameStudio resolve tudo isso **diretamente no seu computador**, com motor C++ (OpenCV/PyAV) e interface de edição limpa, moderna e ergonômica.

---

## 🛡️ Privacidade e Filosofia Open-Source

- **Zero Coleta de Dados:** Nenhum dado pessoal, metadado ou byte de vídeo é enviado para servidores externos.
- **100% Offline & Local:** Toda a decodificação, recorte e amostragem ocorrem exclusivamente na sua máquina (CPU/GPU).
- **Livre e Gratuito para a Comunidade:** Feito sob licença MIT para ajudar criadores, fotógrafos e a comunidade de desenvolvedores.

---

## 🚫 Solução Definitiva para Codecs e Orientação

| Desafio no Windows / Web | Solução do FrameStudio PRO |
| :--- | :--- |
| **Tela Verde em fotos do Windows** | Decodificação nativa via **OpenCV / Canvas RGB** com fidelidade de cor absoluta. |
| **Tela Preta em vídeos HEVC/H.265** | Motor **PyAV (FFmpeg)** integrado que lê qualquer codec sem depender do navegador. |
| **Vídeo de Smartphone virado de lado** | Detecção automática de matriz de rotação (`90°`, `180°`, `270°`) para vídeos verticais (`2160x3840`). |
| **Lentidão em vídeos pesados de 4K** | **Cache em Memória RAM (< 0.1ms)** para scrubbing instantâneo na timeline e playback suave a 60 FPS. |

---

## ✨ Funcionalidades Principais

- **Sugestão Automática de Melhores Momentos:** Grade com 12 miniaturas geradas em frações de segundo para encontrar os melhores ângulos do carro.
- **Controle Frame a Frame de Alta Precisão:**
  - Avanço e recuo de 1 frame exato (`+1F` / `-1F`).
  - Micro-passos de `0.1s` e `1.0s`.
  - Scrubber digital com exibição em `HH:MM:SS.mmm` e contagem de frames.
- **Formatos e Proporções para Redes Sociais:**
  - Exportação em **PNG (Lossless / Sem Perdas)** ou **JPEG (Alta Qualidade)**.
  - Recorte centralizado: **Nativo**, **9:16** (Reels/Stories/TikTok), **1:1** (Feed), **4:5** (Retrato) e **16:9** (Capa/YouTube).
- **Galeria com Exportação Inteligente:**
  - **1 Frame:** Download direto da imagem (`.png` / `.jpg`).
  - **Múltiplos Frames:** Download em lote `.ZIP` plano (sem pastas aninhadas) com nomes concisos (ex: `frame_01_03.9s.png`).
  - **Inspeção com Zoom:** Modal em alta resolução com dados técnicos da captura.

---

## 🚀 Como Iniciar

### Opção 1: Console de Operações (Recomendado)
Execute o arquivo:
```cmd
iniciar-servidor-local.bat
```
- Pressione `[1]` para ligar o servidor na porta **5522** (abre automaticamente o navegador em `http://localhost:5522`).
- Pressione `[2]` para desligar o servidor quando terminar.

### Opção 2: Inicializador Direto de 1 Clique
Dê um duplo clique no arquivo `iniciar.bat`.

---

## ⌨️ Atalhos de Teclado (One-Hand Workflow)

| Atalho | Ação |
| :--- | :--- |
| <kbd>Espaço</kbd> ou <kbd>K</kbd> | Play / Pausar Vídeo |
| <kbd>C</kbd> | **Capturar Frame Atual para a Galeria** |
| <kbd>→</kbd> | Avançar 1 Frame Exato |
| <kbd>←</kbd> | Voltar 1 Frame Exato |
| <kbd>Alt</kbd> + <kbd>→</kbd> | Avançar 0.1 Segundo |
| <kbd>Alt</kbd> + <kbd>←</kbd> | Voltar 0.1 Segundo |
| <kbd>Shift</kbd> + <kbd>→</kbd> | Avançar 1 Segundo |
| <kbd>Shift</kbd> + <kbd>←</kbd> | Voltar 1 Segundo |
| <kbd>?</kbd> | Abrir Painel de Atalhos |
| <kbd>Esc</kbd> | Fechar Modais / Zoom |

---

## 🛠️ Tecnologias Utilizadas

- **Frontend:** HTML5 Semântico, Vanilla CSS (Design System Studio Sóbrio), JavaScript ES6+ Modular, Google Fonts (Inter + JetBrains Mono), JSZip.
- **Backend & Processamento de Vídeo:** Python 3, FastAPI, Uvicorn, OpenCV (C++), PyAV (FFmpeg C-bindings).

---

## 📂 Organização do Projeto

```
video-frame-extrator/
├── index.html                   # Interface do estúdio
├── server.py                    # Servidor FastAPI com motor OpenCV/PyAV
├── iniciar-servidor-local.bat   # Console de operações e launcher local
├── iniciar.bat                  # Inicializador de 1 clique
├── css/
│   └── style.css                # Design system, timeline e galeria
├── js/
│   ├── app.js                   # Orquestrador da aplicação e chamadas de API
│   ├── video-engine.js          # Utilitários de tempo e formatação
│   ├── auto-sampler.js          # Amostragem automática de miniaturas
│   ├── gallery.js               # Galeria, modal de zoom e exportação
│   ├── shortcuts.js             # Mapeamento de atalhos de teclado
│   └── toast.js                 # Notificações visuais
├── README.md                    # Manual de operação e manifesto open-source
├── HISTORICO.md                 # Diário de decisões arquiteturais
└── .gitignore                   # Proteção de logs, caches e temporários
```

---

## 🤝 Como Contribuir

Contribuições são super bem-vindas! Sinta-se à vontade para:
1. Abrir uma **Issue** relatando bugs ou sugerindo novas funcionalidades.
2. Enviar um **Pull Request** com melhorias de código, novas proporções de corte ou otimizações.

---

## 📄 Licença

Este projeto é distribuído sob a licença **MIT**. Consulte o arquivo `LICENSE` para mais detalhes. Feito para fortalecer a comunidade open-source! 🚀
