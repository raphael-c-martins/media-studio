import httpx
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from app.database import get_db_connection
from app.models import AISummaryResponse
from app.services.downloader import extract_media_info

logger = logging.getLogger("media_downloader.ai")

async def get_effective_api_key() -> str:
    """Busca a chave da API DeepSeek no banco de configurações ou variável de ambiente."""
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = 'deepseek_api_key'")
        row = await cursor.fetchone()
        if row and row["value"].strip():
            return row["value"].strip()
    return DEEPSEEK_API_KEY

async def summarize_video(url: str, custom_prompt: Optional[str] = None, download_id: Optional[str] = None) -> AISummaryResponse:
    """Gera um resumo e tópicos estruturados do vídeo utilizando a API DeepSeek."""
    api_key = await get_effective_api_key()
    if not api_key:
        raise ValueError("Chave de API do DeepSeek não configurada. Insira sua chave nas Configurações.")

    # Obter informações e descrição do vídeo
    info = await extract_media_info(url)
    title = info.title
    author = info.author
    description = info.description or "Sem descrição fornecida."

    system_prompt = (
        "Você é um assistente de análise e sumarização de conteúdo audiovisual de alta precisão. "
        "Seu objetivo é analisar os metadados, títulos e contexto do vídeo e produzir um resumo conciso, "
        "estruturado e profissional em Português do Brasil (PT-BR). "
        "Retorne sua resposta formatada em seções: 'Resumo Geral', 'Tópicos Principais' (em bullet points) e 'Principais Conclusões'."
    )

    user_content = (
        f"Título do Vídeo: {title}\n"
        f"Autor/Canal: {author}\n"
        f"Plataforma: {info.platform}\n"
        f"Duração: {info.duration_string or f'{info.duration}s'}\n"
        f"Descrição/Contexto:\n{description}\n\n"
    )

    if custom_prompt:
        user_content += f"Instrução Adicional do Usuário: {custom_prompt}\n"
    else:
        user_content += "Por favor, elabore um resumo conciso e extraia os 3 a 5 pontos-chave mais relevantes."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.5,
        "max_tokens": 1500
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        url_endpoint = f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
        response = await client.post(url_endpoint, json=payload, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Erro na API DeepSeek ({response.status_code}): {response.text}")
            raise ValueError(f"Erro na comunicação com a API DeepSeek: {response.text}")

        data = response.json()
        raw_text = data["choices"][0]["message"]["content"]

    # Extrair key points
    key_points = []
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if cleaned.startswith(("-", "*", "•", "1.", "2.", "3.", "4.", "5.")) and len(cleaned) > 5:
            key_points.append(cleaned.lstrip("-*• 0123456789.").strip())

    summary_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()

    # Salvar no SQLite
    async with get_db_connection() as db:
        await db.execute("""
            INSERT INTO ai_summaries (
                id, download_id, url, title, summary, key_points, transcript, model, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            summary_id, download_id, url, title, raw_text,
            "\n".join(key_points), description, DEEPSEEK_MODEL, created_at
        ))
        await db.commit()

    return AISummaryResponse(
        id=summary_id,
        download_id=download_id,
        url=url,
        title=title,
        summary=raw_text,
        key_points=key_points[:5],
        transcript=description,
        model=DEEPSEEK_MODEL,
        created_at=created_at
    )
