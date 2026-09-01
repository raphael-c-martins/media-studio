import httpx
import re
from bs4 import BeautifulSoup
import json

def test_instagram_embed(shortcode):
    url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    r = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
    print("Embed Status Code:", r.status_code)
    
    # 1. Procurar JSON ou URLs de mídia no HTML do embed
    soup = BeautifulSoup(r.text, "html.parser")
    
    # Imagem / Vídeo
    img_tags = soup.select("img.EmbeddedMediaImage, img")
    print("Imagens encontradas no embed:", len(img_tags))
    for img in img_tags:
        src = img.get("src", "")
        if "instagram" in src or "fbcdn" in src:
            print(" -> Imagem CDN:", src[:80])

    # Caption / Autor
    author = soup.select_one(".Username")
    caption = soup.select_one(".Caption")
    print("Autor:", author.text.strip() if author else None)
    print("Legenda:", caption.text.strip()[:60] if caption else None)

if __name__ == "__main__":
    test_instagram_embed("Dcrhp_1lh2D")
