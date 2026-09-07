#!/usr/bin/env python3
"""Download current DF Wiki article/template sources for local rg/sed lookups.

No game connection. Completed mirrors are offline unless --refresh is requested.
Interrupted downloads resume at the last committed API continuation.
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

API = "https://dwarffortresswiki.org/api.php"
INDEX = "https://dwarffortresswiki.org/index.php"
NAMESPACES = {0: "articles", 10: "templates", 14: "categories", 828: "modules"}


def now():
    return datetime.now(UTC).isoformat()


def request(params):
    query = {"format": "json", "formatversion": 2, "maxlag": 5, **params}
    req = Request(
        API + "?" + urlencode(query),
        headers={"User-Agent": "DF-LLM-local-reference/0.25 (personal offline reference)"},
    )
    with urlopen(req, timeout=30) as response:
        data = json.load(response)
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def mirror(root, refresh=False, fetch=request, pause=time.sleep):
    path = root / "manifest.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    if previous.get("complete") and not refresh:
        return previous
    state = (
        {
            "source": API,
            "started_at": now(),
            "complete": False,
            "scope": NAMESPACES,
            "omitted": "Images, revision history, discussions, user pages and historical version namespaces",
            "pages": {},
            "finished_namespaces": [],
        }
        if refresh or not previous
        else previous
    )
    if "siteinfo" not in state:
        state["siteinfo"] = fetch(
            {"action": "query", "meta": "siteinfo", "siprop": "general|rightsinfo"}
        )["query"]
    for ns, folder in NAMESPACES.items():
        if ns in state["finished_namespaces"]:
            continue
        continuation = state.get("continuation", {})
        while True:
            data = fetch(
                {
                    "action": "query",
                    "generator": "allpages",
                    "gapnamespace": ns,
                    "gaplimit": 50,
                    "prop": "revisions",
                    "rvprop": "ids|timestamp|content",
                    "rvslots": "main",
                    **continuation,
                }
            )
            for page in data.get("query", {}).get("pages", []):
                rev = page["revisions"][0]
                title = page["title"]
                # Flat, encoded filenames: wiki titles can contain /, .. or :.
                name = quote(title.replace(" ", "_"), safe="")
                if len(name) > 180:
                    name = name[:160] + "--" + str(page["pageid"])
                file = f"{folder}/{name}.wiki"
                source = INDEX + "?" + urlencode({"title": title, "oldid": rev["revid"]})
                write(
                    root / file,
                    f"Title: {title}\nSource: {source}\nRevision: {rev['timestamp']}\n"
                    f"License: {state['siteinfo']['rightsinfo']['text']}\n\n"
                    + rev["slots"]["main"]["content"],
                )
                state["pages"][str(page["pageid"])] = {
                    "title": title,
                    "namespace": ns,
                    "revision": rev["revid"],
                    "timestamp": rev["timestamp"],
                    "path": file,
                    "source": source,
                }
            continuation = data.get("continue", {})
            state["continuation"] = continuation
            if not continuation:
                state["finished_namespaces"].append(ns)
            state["updated_at"] = now()
            write(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            print(f"{folder}: {len(state['pages'])} pages stored", flush=True)
            pause(0.5)
            if not continuation:
                break
    # Files missing from a completed fresh crawl are stale (deleted or renamed).
    # Retain them until completion so an interrupted refresh loses no reference.
    retained = {p["path"] for p in state["pages"].values()}
    for folder in NAMESPACES.values():
        for file in (root / folder).glob("*.wiki"):
            if file.relative_to(root).as_posix() not in retained:
                file.unlink()
    state["complete"] = True
    state["completed_at"] = now()
    write(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path(".df-llm/wiki"))
    parser.add_argument(
        "--refresh", action="store_true", help="Explicitly fetch a new current snapshot"
    )
    args = parser.parse_args()
    result = mirror(args.path, args.refresh)
    print(f"Ready: {len(result['pages'])} pages in {args.path}; {result['completed_at']}")


if __name__ == "__main__":
    main()
