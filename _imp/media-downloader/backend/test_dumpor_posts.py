import httpx
from bs4 import BeautifulSoup
import json

def parse_dumpor_profile(username):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    url = f"https://dumpor.com/v/{username}"
    r = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
    if r.status_code != 200:
        print("Erro HTTP:", r.status_code)
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    
    # Extrair dados do perfil
    # Avatar
    avatar_elem = soup.select_one("img[alt*='avatar'], .user-avatar img, img.rounded-full, img[src*='scontent']")
    avatar = avatar_elem.get("src") if avatar_elem else ""

    # Posts / Mídias
    items = []
    # Procurar containers de imagem/posts
    post_cards = soup.select(".post-card, .user-posts .item, .grid > div, .content-item")
    if not post_cards:
        # Fallback para tags de img com links
        imgs = soup.find_all("img")
        for img in imgs:
            src = img.get("src", "")
            if "scontent" in src or "cdninstagram" in src or "instagram" in src or "dumpor" in src:
                parent_a = img.find_parent("a")
                link = parent_a.get("href") if parent_a else ""
                if link and "/v/" not in link:
                    items.append({
                        "thumb": src,
                        "url": f"https://www.instagram.com/p/{link.split('/')[-1]}" if not link.startswith("http") else link
                    })

    print(f"Sucesso: Avatar={bool(avatar)} | Itens encontrados={len(items)}")
    return {"avatar": avatar, "items": items}

if __name__ == "__main__":
    parse_dumpor_profile("jornitrack")
