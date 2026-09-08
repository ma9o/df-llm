"""Bounded world site searches over one native snapshot."""

from heapq import nsmallest
from typing import Any, TypedDict

# Original native names from df-structures; exposed enum names remain canonical.
ALIASES = {
    "lair": "lairshrine",
    "city": "town",
    "cavedetailed": "mountainhalls",
    "treecity": "forestretreat",
}


class Bucket(TypedDict):
    matches: list[dict[str, Any]]
    total: int
    unknown: int


def normalized(value):
    return "".join(c for c in value.casefold() if c.isalnum())


def validate(tokens, match, limit, material=None):
    if material is not None and (
        not isinstance(material, str) or not material.strip() or len(material) > 200
    ):
        raise ValueError("material must be a nonempty native token of at most 200 characters")
    if tokens is None and material is not None:
        tokens = []
    minimum = 0 if material is not None else 1
    if not isinstance(tokens, (list, tuple)) or not minimum <= len(tokens) <= 32:
        raise ValueError("world_scan requires 1..32 search tokens or a material")
    if any(not isinstance(t, str) or not t.strip() or len(t) > 200 for t in tokens):
        raise ValueError("Search tokens must be nonempty strings of at most 200 characters")
    if match not in ("any", "type", "name", "flag"):
        raise ValueError("match must be any, type, name or flag")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer in [1, 100] per token")
    return [token.strip() for token in tokens]


def rank(site):
    return site.get("distance", float("inf")), site["id"]


def scan_chunk(sites, tokens, match, limit, origin, material=False):
    buckets: list[Bucket] = [{"matches": [], "total": 0, "unknown": 0} for _ in tokens]
    needles = [
        (ALIASES.get(normalized(t), normalized(t)), normalized(t), t.casefold()) for t in tokens
    ]
    for row in sites:
        types = {normalized(row["type"]), normalized(row.get("subtype", ""))} - {""}
        flags = {normalized(flag) for flag in row.get("flags", [])}
        names = [row.get("name", "").casefold(), row.get("native_name", "").casefold()]
        site = dict(row)
        if origin is not None:
            site["distance"] = max(abs(site["position"][k] - origin[k]) for k in ("x", "y"))
        for (type_needle, flag_needle, name_needle), bucket in zip(needles, buckets, strict=True):
            type_match = type_needle in types
            name_match = any(name_needle in name for name in names)
            found = (
                (match in ("any", "type") and type_match)
                or (match in ("any", "name") and name_match)
                or (match in ("any", "flag") and flag_needle in flags)
            )
            if material:
                stock = row.get("stock", {})
                if found and stock.get("complete") is not True:
                    bucket["unknown"] += 1
                # Known zero stock rules out a material match even when the
                # optional site flags/subtype could not be read.
                if not stock.get("matched") and stock.get("complete") is True:
                    continue
                if found and not stock.get("matched"):
                    continue
            if found:
                bucket["total"] += 1
                bucket["matches"].append(site)
                if len(bucket["matches"]) >= limit * 2:
                    bucket["matches"] = nsmallest(limit, bucket["matches"], key=rank)
            elif (match in ("any", "type") and row.get("subtype_unavailable")) or (
                match in ("any", "flag") and ("flags" not in row or row.get("flags_unavailable"))
            ):
                bucket["unknown"] += 1
    for bucket in buckets:
        bucket["matches"] = nsmallest(limit, bucket["matches"], key=rank)
    return buckets


def attach_stock(snapshot, material, request):
    """Scan every indexed site in bounded reads without loading any local map."""
    if not snapshot.get("available"):
        return snapshot
    out: dict[str, Any] = dict(snapshot, sites=[])
    sites = snapshot["sites"]
    epoch = snapshot["world"]["epoch"]
    canonical = None
    unavailable = []
    unknown_count = 0
    for start in range(0, max(len(sites), 1), 32):
        batch = sites[start : start + 32]
        ids = [site["id"] for site in batch]
        result = request(
            {
                "op": "world_stock",
                "material": material.strip(),
                "site_ids": ids,
                "world_epoch": epoch,
            }
        )
        if not result.get("available"):
            return dict(out, available=False, complete=False, reason=result.get("reason"))
        if result.get("world_epoch") != epoch:
            raise ValueError("World changed during material scan; read the world index again")
        if canonical is not None and result["material"] != canonical:
            raise ValueError("Material identity changed during world scan")
        canonical = result["material"]
        rows = result["sites"]
        if len(rows) != len(ids) or {row["id"] for row in rows} != set(ids):
            raise ValueError("World material scan returned an incomplete site batch")
        stock = {row["id"]: row["stock"] for row in rows}
        out["sites"].extend(dict(site, stock=stock[site["id"]]) for site in batch)
        for site in batch:
            reading = stock[site["id"]]
            if reading.get("complete") is not True:
                unknown_count += 1
                if len(unavailable) < 8:
                    problems = []
                    for source in ("resource_pile", "sale_records"):
                        part = reading.get(source, {})
                        if part.get("complete") is False:
                            problems.append(
                                {
                                    "source": source,
                                    "errors": part.get("errors", []),
                                    "error_count": part.get("error_count", 0),
                                }
                            )
                    unavailable.append(
                        {"site_id": site["id"], "name": site.get("name"), "problems": problems}
                    )
    out["material"] = canonical or material.strip()
    out["material_scope"] = (
        "Material-bearing site resource allotments and available shop sale records; "
        "quantities are not live merchant catalogs, item quality, fit or prices"
    )
    if unknown_count:
        out["material_unavailable"] = unavailable
        out["material_unavailable_count"] = unknown_count
    return out


def search(snapshot, tokens, match="any", limit=20, material=None):
    tokens = validate(tokens, match, limit, material)
    out = {k: v for k, v in snapshot.items() if k not in ("sites", "tokens", "format")}
    out["format"] = "world_scan"
    if not snapshot.get("available"):
        return out
    sites = snapshot["sites"]
    buckets = scan_chunk(
        sites,
        tokens or [""],
        match if tokens else "name",
        limit,
        snapshot.get("origin"),
        material=material is not None,
    )
    out["order"] = (
        "Chebyshev distance to site center, then site ID"
        if snapshot.get("origin") is not None
        else "site ID"
    )
    out["results"] = []
    for token, bucket in zip(tokens or [None], buckets, strict=True):
        total = bucket["total"]
        unknown = snapshot.get("error_count", 0) + bucket["unknown"]
        matches = bucket["matches"]
        out["results"].append(
            {
                **(
                    {"token": token}
                    if token is not None
                    else {"material": out.get("material", material)}
                ),
                "matches": matches,
                "total": total,
                "truncated": len(matches) < total,
                "complete": snapshot.get("complete", False) and unknown == 0,
                **({"unknown": unknown} if unknown else {}),
            }
        )
    out["complete"] = all(result["complete"] for result in out["results"])
    return out
