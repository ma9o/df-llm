# Local game reference

The searchable source mirror lives at `.df-llm/wiki/`. The initial snapshot on
2026-09-07 contains 9,579 pages. Each `.wiki` file starts with its title, exact
revision URL, revision timestamp and license. `manifest.json` records the crawl
dates, page revisions, namespace coverage, completion state and site licensing.

```sh
rg -n -i 'stun|pain|training' .df-llm/wiki/articles/Ettin.wiki
sed -n '1,100p' .df-llm/wiki/articles/Experience.wiki
rg --files .df-llm/wiki/articles | rg -i 'adventure|combat|wrestl'
```

The mirror includes the current article namespace (0), templates (10),
categories (14) and Lua module **source text** (828). Images, talk/user pages,
revision histories and historical game-version namespaces are omitted. Wikitext
retains redirects and template references; templates are stored alongside the
articles without a rendering step. A current-namespace article may still contain
old advice or a link to an omitted historical page. Consult the page's warnings
and revision date, and verify mechanics against installed DFHack/native state
when available.

To create or resume a copy:

```sh
uv run python tools/mirror_wiki.py
```

A completed copy causes that command to return without contacting the network.
To explicitly update it:

```sh
uv run python tools/mirror_wiki.py --refresh
```

The downloader uses MediaWiki's read-only API, requests 50 pages per batch,
honors the API's `maxlag` refusal, and pauses between requests. A failed batch
leaves the last committed continuation available to resume with the first
command. A completed refresh removes files for deleted or renamed pages.
It has no DFHack connection and is independent of harness execution policy.

This follows the wiki's [offline-copy approach](https://dwarffortresswiki.org/index.php/Dwarf_Fortress_Wiki:Offline_wiki)
using current revision content. The site's reported licensing is
[GFDL & MIT](https://dwarffortresswiki.org/index.php/Dwarf_Fortress_Wiki:Copyrights).
The downloaded text is kept in the ignored local reference directory.
