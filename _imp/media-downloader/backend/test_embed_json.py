import httpx
import re
import json

def extract_from_instagram_embed_html(shortcode):
    url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Referer": "https://www.instagram.com/"
    }
    r = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
    html = r.text
    
    # 1. Regex do omniget
    m = re.search(r'"init",\[\],\[(.*?)\],"contextJSON"', html)
    if not m:
        m = re.search(r'"contextJSON":"(\{.*?\})"', html)
        if m:
            raw = m.group(1).encode().decode('unicode_escape')
            data = json.loads(raw)
            print("Sucesso contextJSON:", list(data.keys()))
            return data

    # 2. Procurar gql_data ou shortcode_media
    m_gql = re.search(r'\\\"gql_data\\\":(\{.*?\}\}\}\})', html)
    if m_gql:
        raw = m_gql.group(1).encode().decode('unicode_escape')
        print("Sucesso gql_data:", raw[:100])
        return json.loads(raw)

    print("Tentando busca de URLs diretas no HTML do embed...")
    video_urls = re.findall(r'"video_url":"(https:[^"]+)"', html)
    display_urls = re.findall(r'"display_url":"(https:[^"]+)"', html)
    print("Videos encontrados:", len(video_urls), "| Fotos encontradas:", len(display_urls))
    if display_urls:
        print("Primeira foto:", display_urls[0].encode().decode('unicode_escape')[:70])

if __name__ == "__main__":
    extract_from_instagram_embed_html("Dcrhp_1lh2D")
