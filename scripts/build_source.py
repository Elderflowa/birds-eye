#!/usr/bin/env python3
"""Scan a GitHub account for releases that contain .ipa files and write an
AltStore/Feather compatible source (source.json)."""
import base64, json, os, pathlib, plistlib, re, shutil, sys, tempfile, urllib.error, urllib.request, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
OWNER = CFG.get("owner") or os.environ.get("GITHUB_REPOSITORY_OWNER")
SELF = os.environ.get("GITHUB_REPOSITORY", f"{OWNER}/birds-eye")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"
CACHE_FILE = ROOT / "cache.json"
FALLBACK_ICON = f"https://raw.githubusercontent.com/{SELF}/main/assets/icon.png"


def request(url, accept="application/vnd.github+json"):
    headers = {"Accept": accept, "User-Agent": "birds-eye"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return urllib.request.Request(url, headers=headers)


def api(url):
    global TOKEN
    while True:
        try:
            with urllib.request.urlopen(request(url), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401 and TOKEN:
                print("token rejected, continuing without it", file=sys.stderr)
                TOKEN = ""
                continue
            raise


def paged(url):
    page, out = 1, []
    while True:
        sep = "&" if "?" in url else "?"
        batch = api(f"{url}{sep}per_page=100&page={page}")
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def read_info(path):
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", name):
                return plistlib.loads(z.read(name))
    return None


def inspect_ipa(asset):
    limit = CFG.get("max_ipa_mb", 600) * 1024 * 1024
    if asset["size"] > limit:
        print(f"  skip {asset['name']}: larger than {CFG.get('max_ipa_mb')} MB", file=sys.stderr)
        return None
    print(f"  downloading {asset['name']} ({asset['size'] // 1024} KB)")
    with tempfile.NamedTemporaryFile(suffix=".ipa", delete=False) as tmp:
        try:
            with urllib.request.urlopen(request(asset["browser_download_url"], "application/octet-stream"), timeout=300) as r:
                shutil.copyfileobj(r, tmp)
        except Exception as e:
            print(f"  download failed: {e}", file=sys.stderr)
            return None
    try:
        info = read_info(tmp.name)
    except zipfile.BadZipFile:
        info = None
    finally:
        os.unlink(tmp.name)
    if not info or "CFBundleIdentifier" not in info:
        print(f"  no Info.plist found in {asset['name']}", file=sys.stderr)
        return None
    return {
        "bundle": info["CFBundleIdentifier"],
        "name": info.get("CFBundleDisplayName") or info.get("CFBundleName"),
        "version": str(info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "1.0"),
        "build": str(info.get("CFBundleVersion") or ""),
        "minos": str(info.get("MinimumOSVersion") or ""),
    }


def find_icon(repo):
    for p in CFG.get("icon_paths", []):
        try:
            data = api(f"{API}/repos/{repo['full_name']}/contents/{p}")
            if isinstance(data, dict) and data.get("download_url"):
                return data["download_url"]
        except urllib.error.HTTPError:
            continue
    return find_readme_icon(repo)


IMG = re.compile(r'!\[[^\]]*\]\(\s*<?([^)\s>]+)|<img[^>]+src=["\']([^"\']+)["\']', re.I)


def find_readme_icon(repo):
    try:
        data = api(f"{API}/repos/{repo['full_name']}/readme")
        text = base64.b64decode(data.get("content", "")).decode("utf-8", "replace")
    except Exception:
        return None
    readme_dir = os.path.dirname(data.get("path", "README.md"))
    base = f"https://raw.githubusercontent.com/{repo['full_name']}/{repo.get('default_branch', 'main')}/"
    urls = []
    for m in IMG.finditer(text):
        u = (m.group(1) or m.group(2) or "").strip()
        low = u.lower().split("?")[0]
        if not u or "shields.io" in u or "badge" in low or "/workflows/" in low:
            continue
        if low.endswith((".svg", ".gif", ".webp")):
            continue
        if not u.startswith("http"):
            u = base + os.path.normpath(os.path.join(readme_dir, u.lstrip("/"))).replace("\\", "/") if not u.startswith("/") else base + u.lstrip("/")
        u = re.sub(r"^https://github\.com/([^/]+/[^/]+)/blob/", r"https://raw.githubusercontent.com/\1/", u)
        urls.append(u)
    for u in urls:
        if re.search(r"logo|icon", u, re.I):
            return u
    return urls[0] if urls else None


def main():
    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    seen, apps = {}, {}
    excluded = set(CFG.get("exclude_repos", []))

    for repo in paged(f"{API}/users/{OWNER}/repos?type=owner"):
        if repo["name"] in excluded or repo.get("disabled"):
            continue
        if repo["fork"] and not CFG.get("include_forks"):
            continue
        if repo["archived"] and not CFG.get("include_archived"):
            continue
        try:
            releases = api(f"{API}/repos/{repo['full_name']}/releases?per_page=20")
        except urllib.error.HTTPError as e:
            print(f"{repo['name']}: cannot read releases ({e.code})", file=sys.stderr)
            continue
        icon = None
        icon_checked = False
        has_ipa = lambda r: any(x["name"].lower().endswith(".ipa") for x in r["assets"])
        stable = [r for r in releases if not r["draft"] and re.match(r"v?\d", r["tag_name"]) and has_ipa(r)]
        if stable:
            releases = [r for r in releases if r["tag_name"].lower() not in ("latest", "nightly")]
        for rel in releases:
            if rel["draft"] or (rel["prerelease"] and not CFG.get("include_prereleases")):
                continue
            for asset in rel["assets"]:
                if not asset["name"].lower().endswith(".ipa") or asset["state"] != "uploaded":
                    continue
                key = f"{asset['id']}:{asset['size']}"
                meta = cache.get(key)
                if meta is None:
                    print(f"{repo['name']} {rel['tag_name']}")
                    meta = inspect_ipa(asset)
                if meta is None:
                    continue
                seen[key] = meta
                if meta["bundle"] in CFG.get("exclude_bundles", []):
                    continue
                if not icon_checked:
                    icon, icon_checked = find_icon(repo), True
                app = apps.setdefault(meta["bundle"], {
                    "name": meta["name"] or repo["name"],
                    "bundleIdentifier": meta["bundle"],
                    "developerName": OWNER,
                    "subtitle": (repo.get("description") or f"From {repo['name']}")[:80],
                    "localizedDescription": repo.get("description") or f"Built from {repo['full_name']}.",
                    "iconURL": icon or FALLBACK_ICON,
                    "tintColor": CFG.get("tintColor", "0A84FF"),
                    "screenshotURLs": [],
                    "permissions": [],
                    "beta": False,
                    "versions": [],
                })
                if icon and app["iconURL"] == FALLBACK_ICON:
                    app["iconURL"] = icon
                stamp = asset.get("updated_at") or rel["published_at"]
                app["versions"].append({
                    "_ts": stamp,
                    "version": meta["version"],
                    "buildVersion": meta["build"],
                    "date": stamp[:10],
                    "localizedDescription": (rel.get("body") or "").strip()[:600] or f"Release {rel['tag_name']}",
                    "downloadURL": asset["browser_download_url"],
                    "size": asset["size"],
                    "minOSVersion": meta["minos"] or "17.0",
                })

    out_apps = []
    for app in apps.values():
        newest_first = sorted(app["versions"], key=lambda v: v["_ts"], reverse=True)
        unique, used = [], set()
        for v in newest_first:
            if v["version"] in used:
                continue
            used.add(v["version"])
            unique.append(v)
        unique = unique[: CFG.get("max_versions", 5)]
        for v in unique:
            v.pop("_ts")
        app["versions"] = unique
        top = unique[0]
        app.update({"version": top["version"], "versionDate": top["date"],
                    "versionDescription": top["localizedDescription"],
                    "downloadURL": top["downloadURL"], "size": top["size"]})
        out_apps.append(app)
    out_apps.sort(key=lambda a: a["name"].lower())

    raw = f"https://raw.githubusercontent.com/{SELF}/main"
    source = {
        "name": CFG["name"],
        "identifier": CFG["identifier"],
        "subtitle": CFG.get("subtitle", ""),
        "description": CFG.get("description", ""),
        "iconURL": f"{raw}/assets/icon.png",
        "website": f"https://github.com/{SELF}",
        "tintColor": CFG.get("tintColor", "0A84FF"),
        "sourceURL": f"{raw}/source.json",
        "apps": out_apps,
        "news": [],
    }
    (ROOT / "source.json").write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n")
    CACHE_FILE.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n")
    print(f"wrote source.json with {len(out_apps)} app(s)")


if __name__ == "__main__":
    main()
