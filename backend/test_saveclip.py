import httpx
import re

def test_saveclip(url):
    # saveclip API
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://saveclip.app/",
        "Origin": "https://saveclip.app"
    }
    try:
        r = httpx.post("https://api.saveclip.app/api/ajaxSearch", data={"q": url, "t": "media", "lang": "en"}, headers=headers, timeout=10)
        print("SaveClip API Status:", r.status_code)
        if r.status_code == 200:
            print("SaveClip Response:", r.json().keys() if "json" in r.headers.get("content-type", "") else r.text[:200])
    except Exception as e:
        print("SaveClip erro:", e)

    # fastdl / snapinsta
    try:
        r = httpx.post("https://fastdl.app/api/convert", json={"url": url}, headers={"User-Agent": headers["User-Agent"]}, timeout=10)
        print("FastDL Status:", r.status_code)
    except Exception as e:
        print("FastDL erro:", e)

if __name__ == "__main__":
    test_saveclip("https://www.instagram.com/p/Dcrhp_1lh2D/")
