# --- SENTINEL URL FEATURES BLOCK START ---
import re
from urllib.parse import urlparse

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
# Explicit URLs: scheme (incl. defanged hxxp) or www. prefix.
_EXPLICIT = r"(?:h(?:tt|xx)ps?://|www\.)[^\s<>\"']+"
# Bare domains: labels with no spaces around dots, TLD of 2-24 letters, optional path.
# [.] and (.) are defanged dots.
_DOT = r"(?:\.|\[\.\]|\(\.\))"
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_BARE = rf"(?<![\w@.])(?:{_LABEL}{_DOT})+[a-z]{{2,24}}(?![\w-])(?:/[^\s<>\"']*)?"
_URL_RE = re.compile(rf"{_EXPLICIT}|{_BARE}", re.I)
# Common words that look like domains (abbreviations) - not URLs.
_NOT_DOMAINS = {"e.g", "i.e", "a.m", "p.m"}
# Bare domains (no scheme, no www.) need a known TLD, else "ok.See you" reads as a URL.
# ponytail: curated list, swap for the full IANA list if recall on bare domains suffers.
_BARE_TLDS = set((
    "com net org info biz xyz top site online store shop club live app dev io co ai me cc tk ml ga cf gq "
    "buzz link click icu vip win bid loan work fun space website tech pro cloud email support help "
    "in uk us ca au de fr ru cn jp br pk bd lk np ae sg my id ph th vn ng ke za eu ly to gl gd sh"
).split())


def normalise_url(url: str) -> str:
    """Normalise a URL so the model cannot learn the scheme/www/trailing-slash shortcut."""
    if not url or not isinstance(url, str):
        return ""
    url = re.sub(r"^hxxp", "http", url.strip(), flags=re.I)
    url = url.replace("[.]", ".").replace("(.)", ".")
    try:
        parsed = urlparse(url if _SCHEME.match(url) else "http://" + url)
        port = parsed.port
    except ValueError:  # malformed host/port: fall back to plain lowercase text
        return url.lower()
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    netloc = host + (f":{port}" if port else "")
    if parsed.username:
        netloc = parsed.username + "@" + netloc
    path = parsed.path.rstrip("/")
    query = "?" + parsed.query if parsed.query else ""
    frag = "#" + parsed.fragment if parsed.fragment else ""
    return netloc + path + query + frag


def extract_urls(text: str) -> list:
    """Return URLs found in message text, defanged forms repaired, in order, no duplicates."""
    if not text or not isinstance(text, str):
        return []
    urls = []
    for m in _URL_RE.finditer(text):
        u = m.group(0).rstrip(".,;:!?)]}'\"")
        u = re.sub(r"^hxxp", "http", u, flags=re.I).replace("[.]", ".").replace("(.)", ".")
        host = re.split(r"[/?#]", re.sub(r"^[a-z]+://", "", u, flags=re.I))[0].lower()
        bare = not re.match(r"^(h(tt|xx)ps?://|www\.)", m.group(0), re.I)
        if host in _NOT_DOMAINS or (bare and host.rsplit(".", 1)[-1] not in _BARE_TLDS):
            continue
        if u not in urls:
            urls.append(u)
    return urls
# --- SENTINEL URL FEATURES BLOCK END ---
