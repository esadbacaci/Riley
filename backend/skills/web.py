"""Web becerileri: arama, sayfa özeti, URL açma. Harici API anahtarı gerekmez."""
from __future__ import annotations

import html
import re
import urllib.parse
import webbrowser

import httpx

from skills.registry import SkillError, skill

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

_RESULT_RE = re.compile(
    r'<a rel="nofollow" class="result__a" href="(?P<url>[^"]+)">(?P<title>.*?)</a>'
    r'.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL,
)


def _strip_tags(raw: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()


def _unwrap(url: str) -> str:
    """DuckDuckGo yönlendirme bağlantısını gerçek adrese çevirir."""
    if "duckduckgo.com/l/" in url:
        query = urllib.parse.urlparse(url).query
        target = urllib.parse.parse_qs(query).get("uddg", [""])[0]
        return urllib.parse.unquote(target) or url
    return url


@skill(
    name="web_search",
    description=(
        "Internette arama yapar ve ilk sonuçların başlıklarını, özetlerini ve "
        "adreslerini döndürür. Guncel bilgi, haber, fiyat, hava durumu gibi "
        "eğitim verinde olmayan şeyler sorulunca kullan."
    ),
    params={
        "query": {"type": "string", "description": "Arama sorgusu"},
        "count": {"type": "integer", "description": "Kac sonuç, varsayılan 5"},
    },
    required=["query"],
    level="narrow",
)
def web_search(query: str, count: int = 5) -> str:
    count = max(1, min(8, int(count)))
    try:
        resp = httpx.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "tr-tr"},
            headers={"User-Agent": _UA},
            timeout=15.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise SkillError(f"Arama yapılamadı: {exc}") from exc

    results = []
    for match in _RESULT_RE.finditer(resp.text):
        title = _strip_tags(match.group("title"))
        snippet = _strip_tags(match.group("snippet"))
        url = _unwrap(match.group("url"))
        if not title:
            continue
        results.append(f"{len(results) + 1}. {title}\n   {snippet[:280]}\n   {url}")
        if len(results) >= count:
            break

    if not results:
        return f"{query} için sonuç bulamadım."
    return f"'{query}' için arama sonuçları:\n" + "\n".join(results)


@skill(
    name="fetch_page",
    description=(
        "Verilen adresteki web sayfasının metnini indirir. Bir bağlantıyı okumak "
        "veya özetlemek gerektiğinde web_search sonrasında kullan."
    ),
    params={"url": {"type": "string", "description": "Tam adres, https:// ile başlamalı"}},
    required=["url"],
    level="narrow",
)
def fetch_page(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = httpx.get(
            url, headers={"User-Agent": _UA}, timeout=20.0, follow_redirects=True
        )
        resp.raise_for_status()
    except Exception as exc:
        raise SkillError(f"Sayfa alınamadı: {exc}") from exc

    body = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", resp.text)
    text = re.sub(r"\s+", " ", _strip_tags(body))
    if len(text) > 5000:
        text = text[:5000] + " ... (kısaltıldı)"
    return f"{url} sayfasından:\n{text}"


@skill(
    name="open_url",
    description=(
        "Bir web adresini varsayılan tarayıcıda açar. Kullanıcı bir siteyi "
        "açmanı istediğinde kullan. Site adı verilirse tahmin edip tamamla."
    ),
    params={"url": {"type": "string", "description": "Açılacak adres, orn: youtube.com"}},
    required=["url"],
    level="narrow",
)
def open_url(url: str) -> str:
    target = url.strip()
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    webbrowser.open(target)
    return f"{target} tarayıcıda açıldı."


@skill(
    name="search_youtube",
    description="YouTube'da arama yapıp sonuç sayfasını tarayıcıda açar.",
    params={"query": {"type": "string", "description": "Aranacak şarkı, video veya kanal"}},
    required=["query"],
    level="narrow",
)
def search_youtube(query: str) -> str:
    encoded = urllib.parse.quote_plus(query)
    webbrowser.open(f"https://www.youtube.com/results?search_query={encoded}")
    return f"YouTube'da '{query}' araması açıldı."
