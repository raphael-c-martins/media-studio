import httpx
from bs4 import BeautifulSoup

def inspect_dumpor(username):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    url = f"https://dumpor.com/v/{username}"
    r = httpx.get(url, headers=headers, timeout=12, follow_redirects=True)
    soup = BeautifulSoup(r.text, "html.parser")
    print("Page Title:", soup.title.text if soup.title else None)
    
    # Imprimir todas as classes de divs principais
    for div in soup.find_all(["div", "img", "a"], limit=30):
        c = div.get("class", [])
        if c:
            print(f"Tag: {div.name} | Class: {c} | Text/Src: {(div.text or div.get('src') or '')[:35]}")

if __name__ == "__main__":
    inspect_dumpor("jornitrack")
