#!/usr/bin/env python3
"""
api_hub — Open-Source GitHub & Zero-Key Public API Hub.

Syncs open-source API catalogs from GitHub (`public-apis/public-apis`,
`models.dev/api.json`, GitHub Search/Trending) and provides built-in live
connectors (Ollama, GitHub, Open-Meteo Weather, Wikipedia, ArXiv, HackerNews,
CoinGecko, Frankfurter FX, npm, PyPI, IP).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

CACHE_DIR = Path(os.environ.get("AI_HUB_CACHE_DIR", Path.home() / ".cache" / "ai-hub"))
FALLBACK_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
PUBLIC_APIS_URL = "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md"
MODELS_DEV_URL = "https://models.dev/api.json"
OLLAMA_URL = "http://127.0.0.1:11434"


def _ssl_ctx() -> ssl.SSLContext:
    ca = "/etc/ssl/cert.pem"
    if os.path.exists(ca):
        return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()


def _cache_dir() -> Path:
    for d in (CACHE_DIR, FALLBACK_CACHE_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
            test = d / ".write_test"
            test.write_text("ok")
            test.unlink()
            return d
        except OSError:
            continue
    return FALLBACK_CACHE_DIR


def _opener(local: bool = False):
    if local:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_ctx()))


def fetch_text(url: str, timeout: int = 20, headers: dict | None = None, local: bool = False) -> str:
    hdrs = {"User-Agent": "NexusCLI-APIHub/2.0"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with _opener(local=local).open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_json(url: str, timeout: int = 20, headers: dict | None = None, local: bool = False):
    return json.loads(fetch_text(url, timeout=timeout, headers=headers, local=local))


# ---------------------------------------------------------------- catalog sync
def parse_public_apis_md(md: str) -> list[dict]:
    """Parse markdown tables from github.com/public-apis/public-apis."""
    apis: list[dict] = []
    category = "General"
    row_re = re.compile(r"^\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|")
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("### "):
            category = s[4:].strip()
            continue
        m = row_re.match(s)
        if m:
            name, url, desc, auth, https_flag, cors = [g.strip().strip("`") for g in m.groups()]
            apis.append({
                "name": name,
                "url": url,
                "desc": desc,
                "auth": auth or "No",
                "https": https_flag,
                "cors": cors,
                "category": category,
            })
    return apis


def sync_open_apis() -> dict:
    """Pull latest open-source API catalogs from GitHub & models.dev."""
    cdir = _cache_dir()
    summary: dict = {"synced_at": dt.datetime.now().isoformat(timespec="seconds"), "sources": {}}

    try:
        md = fetch_text(PUBLIC_APIS_URL, timeout=25)
        apis = parse_public_apis_md(md)
        no_auth = [a for a in apis if a["auth"].lower() in ("no", "none", "")]
        (cdir / "public_apis.json").write_text(json.dumps(apis, ensure_ascii=False))
        summary["sources"]["public-apis"] = {"ok": True, "total": len(apis), "no_auth": len(no_auth)}
    except Exception as e:
        summary["sources"]["public-apis"] = {"ok": False, "error": str(e)}

    try:
        mdata = fetch_json(MODELS_DEV_URL, timeout=25)
        providers = []
        if isinstance(mdata, dict):
            for pid, pinfo in mdata.items():
                if not isinstance(pinfo, dict):
                    continue
                models = pinfo.get("models") or {}
                providers.append({
                    "id": pid,
                    "name": pinfo.get("name", pid),
                    "api": pinfo.get("api", ""),
                    "doc": pinfo.get("doc", ""),
                    "env": pinfo.get("env", []),
                    "model_count": len(models) if isinstance(models, dict) else 0,
                    "sample_models": list(models.keys())[:8] if isinstance(models, dict) else [],
                })
        (cdir / "models_dev.json").write_text(json.dumps(providers, ensure_ascii=False))
        summary["sources"]["models.dev"] = {"ok": True, "providers": len(providers)}
    except Exception as e:
        summary["sources"]["models.dev"] = {"ok": False, "error": str(e)}

    try:
        odata = fetch_json(f"{OLLAMA_URL}/api/tags", timeout=5, local=True)
        models = [m.get("name") for m in odata.get("models", []) if m.get("name")]
        summary["sources"]["ollama"] = {"ok": True, "models": models}
    except Exception as e:
        summary["sources"]["ollama"] = {"ok": False, "error": str(e)}

    (cdir / "sync_meta.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def load_public_apis() -> list[dict]:
    for d in (CACHE_DIR, FALLBACK_CACHE_DIR):
        p = d / "public_apis.json"
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    return []


def load_models_dev() -> list[dict]:
    for d in (CACHE_DIR, FALLBACK_CACHE_DIR):
        p = d / "models_dev.json"
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    return []


# ---------------------------------------------------------------- built-in live connectors
BUILTIN_APIS = [
    ("sync", "Sync open-source API catalogs from GitHub (public-apis + models.dev)"),
    ("gh <query>", "Search open-source GitHub repositories"),
    ("trending [topic]", "Most starred open-source GitHub repositories"),
    ("models [filter]", "Open-source & cloud AI model catalog (models.dev + Ollama)"),
    ("ollama", "Local Ollama API status & loaded models (127.0.0.1:11434)"),
    ("weather [city]", "Real-time weather forecast (Open-Meteo API)"),
    ("wiki <topic>", "Wikipedia article summary (REST API)"),
    ("arxiv <query>", "Search AI & CS research papers (ArXiv API)"),
    ("hn [count]", "Top tech stories (HackerNews API)"),
    ("crypto [coins]", "Live crypto prices in USD & IDR (CoinGecko API)"),
    ("fx [from] [to]", "Live currency exchange rates (Frankfurter API)"),
    ("npm <package>", "Open-source JS package info (npm Registry API)"),
    ("pypi <package>", "Open-source Python package info (PyPI JSON API)"),
    ("ip", "Check public IP address (ipify API)"),
    ("search <keyword>", "Search thousands of GitHub public APIs (--free for no-auth)"),
    ("call <url>", "Call any JSON or text API endpoint directly"),
]


def run_api(command_line: str) -> dict:
    """Execute an API subcommand and return {ok, title, markdown, raw}."""
    parts = command_line.strip().split(None, 1)
    if not parts or parts[0] in ("list", "help"):
        lines = ["| Command | Description |", "|---|---|"]
        for cmd, desc in BUILTIN_APIS:
            lines.append(f"| `/api {cmd}` | {desc} |")
        return {"ok": True, "title": "API Hub — Open-Source GitHub & Public APIs", "markdown": "\n".join(lines), "raw": ""}

    sub = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    t0 = time.time()

    try:
        if sub == "sync":
            res = sync_open_apis()
            s = res["sources"]
            lines = [f"**Synced at:** `{res['synced_at']}`\n"]
            pa = s.get("public-apis", {})
            if pa.get("ok"):
                lines.append(f"- **GitHub `public-apis/public-apis`**: `{pa['total']}` APIs indexed (`{pa['no_auth']}` without API key)")
            else:
                lines.append(f"- **GitHub `public-apis`**: failed ({pa.get('error')})")
            md = s.get("models.dev", {})
            if md.get("ok"):
                lines.append(f"- **`models.dev` AI Catalog**: `{md['providers']}` AI providers cached")
            else:
                lines.append(f"- **`models.dev`**: failed ({md.get('error')})")
            ol = s.get("ollama", {})
            if ol.get("ok"):
                lines.append(f"- **Local Ollama (`127.0.0.1:11434`)**: `{', '.join(ol['models'])}`")
            else:
                lines.append(f"- **Local Ollama**: offline ({ol.get('error')})")
            return {"ok": True, "title": "Open-Source API Catalog Sync", "markdown": "\n".join(lines), "raw": json.dumps(res, indent=2)}

        if sub == "ollama":
            data = fetch_json(f"{OLLAMA_URL}/api/tags", timeout=5, local=True)
            models = data.get("models", [])
            lines = [f"Endpoint: `{OLLAMA_URL}` · OpenAI-Compat: `{OLLAMA_URL}/v1`\n"]
            for m in models:
                sz = round((m.get("size") or 0) / (1024**3), 2)
                lines.append(f"- `{m.get('name')}` ({sz} GB)")
            return {"ok": True, "title": f"Local Ollama ({len(models)} models)", "markdown": "\n".join(lines), "raw": json.dumps(data, indent=2)}

        if sub in ("gh", "github", "trending"):
            q = arg or ("stars:>5000 topic:ai" if sub == "trending" else "ai cli")
            if sub == "trending" and arg:
                q = f"{arg} stars:>500"
            url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(q)}&sort=stars&order=desc&per_page=8"
            data = fetch_json(url)
            items = data.get("items", [])
            lines = []
            for r in items:
                stars = r.get("stargazers_count", 0)
                lang = r.get("language") or "-"
                desc = (r.get("description") or "").replace("\n", " ")[:110]
                lines.append(f"- **[{r['full_name']}]({r['html_url']})** ★ `{stars:,}` · `{lang}`\n  {desc}")
            return {"ok": True, "title": f"GitHub Open-Source ({q})", "markdown": "\n".join(lines) or "_No results._", "raw": json.dumps(items, indent=2)}

        if sub == "models":
            providers = load_models_dev()
            if not providers:
                sync_open_apis()
                providers = load_models_dev()
            q = arg.lower()
            matched = [p for p in providers if not q or q in p["id"].lower() or q in p["name"].lower() or any(q in m.lower() for m in p.get("sample_models", []))]
            lines = []
            for p in matched[:15]:
                samp = ", ".join(p.get("sample_models", [])[:4])
                env_s = ", ".join(p.get("env", [])) or "no-key/custom"
                lines.append(f"- **{p['name']}** (`{p['id']}`) — {p['model_count']} models · env: `{env_s}`\n  Sample: `{samp}`")
            return {"ok": True, "title": f"AI Model Catalog ({len(matched)} providers)", "markdown": "\n".join(lines) or "_No matches._", "raw": json.dumps(matched[:15], indent=2)}

        if sub == "weather":
            city = arg or "London"
            geo = fetch_json(f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=en")
            results = geo.get("results") or []
            if not results:
                return {"ok": False, "title": "Weather", "markdown": f"City not found: `{city}`", "raw": ""}
            loc = results[0]
            lat, lon = loc["latitude"], loc["longitude"]
            wx = fetch_json(
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code&timezone=auto"
            )
            cur = wx.get("current", {})
            md = (
                f"**{loc.get('name')}, {loc.get('country', '')}** (`{lat:.2f}, {lon:.2f}`)\n\n"
                f"- Temperature: **{cur.get('temperature_2m')}°C** (feels like {cur.get('apparent_temperature')}°C)\n"
                f"- Humidity: **{cur.get('relative_humidity_2m')}%**\n"
                f"- Wind: **{cur.get('wind_speed_10m')} km/h**"
            )
            return {"ok": True, "title": f"Weather — {loc.get('name')}", "markdown": md, "raw": json.dumps(wx, indent=2)}

        if sub == "wiki":
            topic = arg or "Artificial intelligence"
            slug = urllib.parse.quote(topic.replace(" ", "_"))
            for lang in ("en", "id"):
                try:
                    data = fetch_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{slug}")
                    if data.get("extract"):
                        md = f"**{data.get('title')}** (`{lang}.wikipedia.org`)\n\n{data['extract']}\n\n[Read more]({data.get('content_urls', {}).get('desktop', {}).get('page', '')})"
                        return {"ok": True, "title": f"Wikipedia — {data.get('title')}", "markdown": md, "raw": json.dumps(data, indent=2)}
                except Exception:
                    continue
            return {"ok": False, "title": "Wikipedia", "markdown": f"Article not found: `{topic}`", "raw": ""}

        if sub == "arxiv":
            q = arg or "open source coding agent"
            xml_txt = fetch_text(f"https://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(q)}&start=0&max_results=5")
            root = ET.fromstring(xml_txt)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            lines = []
            for entry in root.findall("a:entry", ns):
                title = " ".join((entry.findtext("a:title", "", ns) or "").split())
                link = entry.findtext("a:id", "", ns)
                pub = (entry.findtext("a:published", "", ns) or "")[:10]
                lines.append(f"- **[{title}]({link})** (`{pub}`)")
            return {"ok": True, "title": f"ArXiv Papers ({q})", "markdown": "\n".join(lines) or "_No results._", "raw": xml_txt}

        if sub == "hn":
            n = int(arg) if arg.isdigit() else 6
            n = max(1, min(12, n))
            ids = fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")[:n]
            lines = []
            for sid in ids:
                it = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                if not it:
                    continue
                url = it.get("url") or f"https://news.ycombinator.com/item?id={sid}"
                lines.append(f"- **[{it.get('title')}]({url})** — {it.get('score', 0)} pts · {it.get('descendants', 0)} comments")
            return {"ok": True, "title": f"HackerNews Top {n}", "markdown": "\n".join(lines), "raw": ""}

        if sub == "crypto":
            coins = arg.replace(" ", ",") if arg else "bitcoin,ethereum,solana"
            data = fetch_json(f"https://api.coingecko.com/api/v3/simple/price?ids={urllib.parse.quote(coins)}&vs_currencies=usd,eur&include_24hr_change=true")
            lines = ["| Coin | USD | EUR | 24h |", "|---|---|---|---|"]
            for k, v in data.items():
                usd = f"${v.get('usd', 0):,.2f}"
                eur = f"€{v.get('eur', 0):,.2f}"
                chg = v.get("usd_24h_change", 0)
                lines.append(f"| `{k}` | {usd} | {eur} | {chg:+.2f}% |")
            return {"ok": True, "title": "CoinGecko Live Crypto", "markdown": "\n".join(lines), "raw": json.dumps(data, indent=2)}

        if sub == "fx":
            toks = arg.upper().split()
            base = toks[0] if len(toks) >= 1 else "USD"
            to = toks[1] if len(toks) >= 2 else "EUR,GBP,JPY,IDR"
            data = fetch_json(f"https://api.frankfurter.app/latest?from={urllib.parse.quote(base)}&to={urllib.parse.quote(to)}")
            lines = [f"**1 {data.get('base')}** (`{data.get('date')}`)\n"]
            for k, v in (data.get("rates") or {}).items():
                lines.append(f"- **{k}**: `{v:,.4f}`")
            return {"ok": True, "title": f"Currency Rates ({base})", "markdown": "\n".join(lines), "raw": json.dumps(data, indent=2)}

        if sub == "npm":
            pkg = arg or "textual"
            data = fetch_json(f"https://registry.npmjs.org/{urllib.parse.quote(pkg)}")
            latest = (data.get("dist-tags") or {}).get("latest", "?")
            desc = data.get("description", "")
            md = f"**{data.get('name')}** `v{latest}`\n\n{desc}\n\nRepo: `{(data.get('repository') or {}).get('url', '-')}`"
            return {"ok": True, "title": f"npm: {pkg}", "markdown": md, "raw": json.dumps({"name": data.get("name"), "latest": latest, "description": desc}, indent=2)}

        if sub == "pypi":
            pkg = arg or "textual"
            data = fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(pkg)}/json")
            info = data.get("info", {})
            md = f"**{info.get('name')}** `v{info.get('version')}`\n\n{info.get('summary', '')}\n\nHome: {info.get('home_page') or info.get('project_url', '')}"
            return {"ok": True, "title": f"PyPI: {pkg}", "markdown": md, "raw": json.dumps(info, indent=2)}

        if sub == "ip":
            data = fetch_json("https://api.ipify.org?format=json")
            return {"ok": True, "title": "Public IP", "markdown": f"Public IP: `{data.get('ip')}`", "raw": json.dumps(data, indent=2)}

        if sub == "search":
            apis = load_public_apis()
            if not apis:
                sync_open_apis()
                apis = load_public_apis()
            q = arg.lower()
            no_auth_only = False
            if "--free" in q or "--no-auth" in q:
                no_auth_only = True
                q = q.replace("--free", "").replace("--no-auth", "").strip()
            hits = []
            for a in apis:
                if no_auth_only and a["auth"].lower() not in ("no", "none", ""):
                    continue
                hay = f"{a['name']} {a['desc']} {a['category']}".lower()
                if not q or q in hay:
                    hits.append(a)
            lines = []
            for a in hits[:15]:
                lines.append(f"- **[{a['name']}]({a['url']})** `[{a['category']}]` · Auth: `{a['auth']}`\n  {a['desc']}")
            return {"ok": True, "title": f"GitHub Public APIs ({len(hits)} matches)", "markdown": "\n".join(lines) or "_No matches._", "raw": json.dumps(hits[:15], indent=2)}

        if sub == "call":
            target = arg.strip()
            if not target:
                return {"ok": False, "title": "API Call", "markdown": "Usage: `/api call https://...`", "raw": ""}
            if not target.startswith(("http://", "https://")):
                apis = load_public_apis()
                match = next((a for a in apis if target.lower() in a["name"].lower()), None)
                if match:
                    target = match["url"]
                else:
                    target = "https://" + target
            is_local = target.startswith(("http://127.0.0.1", "http://localhost"))
            txt = fetch_text(target, timeout=20, local=is_local)
            try:
                pretty = json.dumps(json.loads(txt), indent=2, ensure_ascii=False)[:4000]
                md = f"Endpoint: `{target}`\n```json\n{pretty}\n```"
            except Exception:
                pretty = txt[:4000]
                md = f"Endpoint: `{target}`\n```\n{pretty}\n```"
            return {"ok": True, "title": f"GET {target} ({round(time.time()-t0, 1)}s)", "markdown": md, "raw": pretty}

        return {"ok": False, "title": "API Hub", "markdown": f"Unknown subcommand `/api {sub}`. Type `/api help`.", "raw": ""}
    except Exception as e:
        return {"ok": False, "title": f"API Error ({sub})", "markdown": f"**Error:** `{e}`", "raw": str(e)}
