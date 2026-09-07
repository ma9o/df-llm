"""Explicit reading projections. The comprehensive status response is never filtered."""

from copy import deepcopy

from .events import project_events


def pick(value, fields):
    return {key: deepcopy(value[key]) for key in fields if key in value}


def reading_coatings(coatings):
    # Presence, material, phase and location inform the next decision. Exact
    # amounts and temperatures stay in full observations/status, not every tick.
    return [
        {k: deepcopy(v) for k, v in coating.items() if k not in ("size", "temperature")}
        for coating in coatings
    ]


def reading_item(item):
    out = pick(item, ("id", "description", "mode", "body_part_id", "quality", "wear"))
    weight = item.get("weight_raw", {})
    if item.get("weight_computed") is True and "whole" in weight and "fraction" in weight:
        out["weight_kg"] = weight["whole"] + weight["fraction"] / 1000000
    elif "weight_kg" in item:
        out["weight_kg"] = item["weight_kg"]
    else:
        out["weight_unavailable"] = item.get(
            "weight_unavailable_reason", "Native weight is unavailable or stale"
        )
    if "location" in item:
        out["location"] = (
            pick(item["location"], ("kind", "position", "container_id"))
            if isinstance(item["location"], dict)
            else deepcopy(item["location"])
        )
    if "contents" in item:
        out["contents_shown_in_full_view"] = len(item["contents"])
    elif "contents_shown_in_full_view" in item:
        out["contents_shown_in_full_view"] = item["contents_shown_in_full_view"]
    if item.get("contaminants"):
        out["contaminants"] = reading_coatings(item["contaminants"])
    out.update(pick(item, ("contaminants_unavailable", "contaminants_truncated")))
    return out


def inventory_item(item):
    """Inventory context already supplies location; definitions stay in item/status."""
    out = reading_item(item)
    for key in ("location", "quality", "wear"):
        out.pop(key, None)
    return out


def landmark_rows(landmarks):
    """Exact inclusive x spans per y/z, with terrain identity written once."""
    groups = {}
    for tile in landmarks:
        position = tile.get("position") or {}
        if not all(type(position.get(k)) is int for k in ("x", "y", "z")):
            # Preserve malformed/unknown readings, never manufacture coordinates.
            return deepcopy(landmarks)
        identity = (*(tile.get(k) for k in ("shape", "type", "material")), position["z"])
        groups.setdefault(identity, set()).add((position["y"], position["x"]))
    out = []
    for identity, cells in groups.items():
        rows = []
        for y, x in sorted(cells):
            if rows and rows[-1][0] == y and rows[-1][2] + 1 == x:
                rows[-1][2] = x
            else:
                rows.append([y, x, x])
        out.append(dict(zip(("shape", "type", "material", "z"), identity, strict=True), rows=rows))
    return out


def reading_menu(menu, focus=None):
    out = pick(
        menu,
        (
            "kind",
            "open",
            "context",
            "context_name",
            "mode",
            "selection_unavailable",
            "truncated",
            "target_unit_id",
            "confirm_unit_id",
            "choosing_amount",
            "amount",
            "amount_max",
            "entering_number",
            "number",
            "allow_strike",
            "allow_wrestle",
            "always_do_something",
            "aim_modifiers",
            "attack_flags",
            "charge_restriction",
            "gait_type",
            "selected_index",
            "settings",
            "no_sky",
            "filename",
            "selecting_tact",
        ),
    )
    if menu.get("tact_topic"):
        out["tact_topic"] = pick(menu["tact_topic"], ("native_type", "label"))
    options = menu.get("options", [])
    original_count = len(options)
    if focus:
        item_ids = {focus[k] for k in ("item_id", "container_id") if k in focus}
        if item_ids and any("item_id" in o or "container_id" in o for o in options):
            options = [
                o
                for o in options
                if o.get("item_id") in item_ids or o.get("container_id") in item_ids
            ]
        if "unit_id" in focus and any("unit_id" in o for o in options):
            options = [o for o in options if o.get("unit_id") == focus["unit_id"]]
        if focus.get("position") and any("target_position" in o for o in options):
            options = [o for o in options if o.get("target_position") == focus["position"]]
    groups = {}
    for option in options:
        kind = option.get("native_type", option.get("kind", "option"))
        value = {"id": option.get("handle", option["id"])}
        if "subject_hf_id" in option:
            value = {"hf": option["subject_hf_id"], "name": option["subject_name"]}
        else:
            value.update(
                pick(
                    option,
                    (
                        "label",
                        "item_id",
                        "container_id",
                        "unit_id",
                        "gait_index",
                        "operation",
                        "target_position",
                        "source_container_id",
                        "material_ref",
                        "details_unavailable",
                        "body_part_id",
                        "attack_index",
                        "required_body_part_id",
                        "hit_chance_adjustment",
                        "hit_squareness_adjustment",
                        "flags",
                    ),
                )
            )
            prefixes = {
                "AskAboutHf": "Ask about ",
                "AskForDirectionsToHf": "Ask for the whereabouts of ",
                "AskForDirectionsToSite": "Ask for directions to ",
            }
            prefix = prefixes.get(kind)
            if prefix and value.get("label", "").startswith(prefix):
                value["name"] = value.pop("label")[len(prefix) :]
            if kind == "ReturnToMain":
                value.pop("label", None)
            if option.get("tact_required"):
                value["tact_required"] = True
        groups.setdefault(kind, []).append(value)
    out["options"] = groups
    out["total"] = menu.get("total", len(menu.get("options", [])))
    if len(options) != original_count:
        out["omitted_options"] = original_count - len(options)
    return out


def needs_ui_text(view):
    """Unknown interfaces retain their text; decoded native choices suffice."""
    return view.get("input_guard", {}).get("native_complete") is not True


def reading_status(status):
    return pick(
        status,
        (
            "mode",
            "ready_for_input",
            "can_move",
            "turn_phase",
            "position",
            "map_origin",
            "adventure_menu",
            "open_panels",
            "modal",
            "active_dispatch",
            "interface_unavailable",
        ),
    )


def choice_observation(view):
    out = pick(view, ("state_id", "effect_id"))
    out.update(
        format="choice_observation",
        projection=True,
        status=reading_status(view.get("status", {})),
        choices=[reading_menu(view[k]) for k in ("menu", "conversation", "combat") if view.get(k)],
        omitted="Current choices only; use observe for the scene or status for the character.",
    )
    if needs_ui_text(view):
        out["status"].update(pick(view.get("status", {}), ("screen", "focus")))
        out["ui_text"] = [r["text"].strip() for r in view.get("ui", {}).get("rows", [])]
    return out


def concise_observation(view, event_detail="task", force_types=()):
    out = pick(
        view,
        (
            "state_id",
            "status",
            "conversation",
            "combat",
            "reports",
            "nearby_items_truncated",
            "target_unit",
            "reports_more",
            "next_report_cursor",
            "report_cursor_reset",
        ),
    )
    out.update(
        format="concise_observation",
        projection=True,
        omitted="Inventory: brief/status. Full terrain records, report history and raw UI: observe(view='full'). Landmark rows are [y,x_first,x_last], inclusive.",
    )
    out["status"] = reading_status(view.get("status", {}))
    if view.get("adventurer") is not None:
        player = view["adventurer"]
        out["adventurer"] = pick(
            player,
            (
                "id",
                "name",
                "position",
                "alive",
                "on_ground",
                "health",
                "needs",
                "movement",
                "inventory_truncated",
            ),
        )
        if "inventory_count" in player:
            out["adventurer"].update(pick(player, ("inventory_count", "held_items")))
        elif "inventory" in player:
            out["adventurer"]["inventory_count"] = len(player["inventory"])
            out["adventurer"]["held_items"] = [
                pick(item, ("id", "description", "body_part_id"))
                for item in player["inventory"]
                if item.get("mode") == "Weapon"
            ]
        if "burden" in player:
            out["adventurer"]["burden"] = pick(
                player["burden"],
                ("available", "reason", "label", "compared_weight_kg", "thresholds"),
            )
    if "nearby_items" in view:
        out["nearby_items"] = [reading_item(i) for i in view["nearby_items"]]
    if view.get("map"):
        out["map"] = pick(
            view["map"],
            (
                "origin",
                "width",
                "height",
                "rows",
                "units",
                "units_scope",
                "units_truncated",
                "units_available",
                "units_unavailable",
                "routing_window",
                "legend",
                "visibility",
                "buildings",
                "buildings_truncated",
                "liquid_regions",
                "buildings_unavailable_tiles",
                "feature_distance_from",
            ),
        )
        if "landmarks" in view["map"]:
            out["map"]["landmarks"] = landmark_rows(view["map"]["landmarks"])
        if "legend" in out["map"] and "rows" in out["map"]:
            symbols = set("".join(out["map"]["rows"]))
            out["map"]["legend"] = {k: v for k, v in out["map"]["legend"].items() if k in symbols}
    if view.get("navigation"):
        out["navigation"] = pick(
            view["navigation"], ("position", "current_site", "leads", "leads_source", "truncated")
        )
    for key in ("menu", "conversation", "combat"):
        if view.get(key):
            out[key] = reading_menu(view[key])
    if "reports" in view:
        reports, filtered = project_events(view["reports"], event_detail, force_types)
        out["reports"] = deepcopy(reports[-4:])
        out["reports_omitted"] = (
            len(view["reports"]) - len(out["reports"]) + view.get("reports_truncated", 0)
        )
        out["report_cursor"] = view.get(
            "report_cursor", max((e["id"] for e in view["reports"]), default=-1)
        )
        if filtered:
            out["report_omissions"] = filtered
        out["reports_full_query"] = (
            "observe(view='full', reports_after=cursor); dispatch_details for dispatch history"
        )
    if needs_ui_text(view):
        out["status"].update(pick(view.get("status", {}), ("screen", "focus")))
        out["ui_text"] = [r["text"].strip() for r in view.get("ui", {}).get("rows", [])]
    return out


def character_brief(report):
    out = pick(report, ("state_id", "status", "available", "reason", "schema_version"))
    out.update(format="character_brief", projection=True, full_query="status")
    if not report.get("available"):
        return out
    out["status"] = reading_status(report.get("status", {}))
    c = report["character"]
    brief = pick(c, ("id", "name", "race", "position", "alive", "on_ground", "health", "skills"))
    health = c.get("health", {})
    brief["health"] = pick(
        health,
        (
            "blood_count",
            "blood_max",
            "wounds",
            "pain",
            "exhaustion",
            "nausea",
            "dizziness",
            "fever",
            "infection_level",
            "numbness",
            "paralysis",
            "stunned",
            "suffocation",
            "unconscious",
            "webbed",
            "winded",
        ),
    )
    if "flags" in health:
        brief["health"]["flags"] = deepcopy(health["flags"])
    brief["identity"] = pick(
        c.get("identity", {}), ("english_name", "age_years", "profession", "hist_figure_id")
    )
    brief["attributes"] = {
        key: {
            a["name"]: a["value"]
            if "value" in a and a.get("effective") == a["value"]
            else pick(a, ("value", "effective"))
            for a in values
        }
        for key, values in c.get("attributes", {}).items()
        if isinstance(values, list)
    }
    if isinstance(c.get("skills"), list):
        brief["skills"] = {
            s["name"]: dict(
                pick(s, ("rating_name", "effective")),
                **(
                    {"xp": [s["experience"], s["next_level_xp_threshold"]]}
                    if "experience" in s and "next_level_xp_threshold" in s
                    else pick(s, ("experience", "next_level_xp_threshold"))
                ),
            )
            for s in c["skills"]
        }
    load = c.get("encumbrance", {})
    brief["encumbrance"] = pick(
        load,
        (
            "total_weight_kg",
            "known_weight_kg",
            "weight_complete",
            "native_cached_weight_kg",
            "unweighed_items",
        ),
    )
    if "heaviest_items" in load:
        brief["encumbrance"]["heaviest_item_ids"] = [i["id"] for i in load["heaviest_items"]]
    for key in ("capacity", "burden", "load_penalty"):
        if key in load:
            brief["encumbrance"][key] = pick(
                load[key],
                (
                    "available",
                    "reason",
                    "label",
                    "weight_kg",
                    "capacity_used_percent",
                    "excess_weight_kg",
                    "movement_cost_added",
                    "speed_reduction_percent",
                ),
            )
    speed = c.get("movement", {}).get("effective_speed", {})
    brief["movement"] = {
        "effective_speed": pick(speed, ("available", "reason", "gait", "displayed_text", "rate"))
    }
    if "unloaded" in speed:
        brief["movement"]["effective_speed"]["unloaded"] = pick(
            speed["unloaded"], ("rate", "displayed_text")
        )
    if "interpreted_needs" in c.get("physiology", {}):
        needs = c["physiology"]["interpreted_needs"]
        interpreted = pick(needs, ("available", "reason"))
        for key in ("hunger", "thirst", "sleep"):
            if key in needs:
                interpreted[key] = pick(
                    needs[key],
                    (
                        "available",
                        "reason",
                        "label",
                        "severity",
                        "counter",
                        "required",
                        "next_stage",
                    ),
                )
        brief["physiology"] = {"interpreted_needs": interpreted}
    brief["combat"] = pick(
        c.get("combat", {}), ("opponent", "attacker_ids", "interface", "grapple_count")
    )
    brief["inventory"] = [inventory_item(i) for i in c.get("inventory", [])]
    brief["inventory_truncated"] = c.get("inventory_truncated", False)
    coverage = c.get("coverage", {})
    native_brief = coverage.get("scope") == "brief"
    # A narrow native query cannot promise anything about unread full sections.
    coverage_key = "query_coverage" if native_brief else "full_report_coverage"
    brief[coverage_key] = pick(coverage, ("complete", "unavailable_count", "truncated_count"))
    brief[coverage_key]["partial_sections"] = [
        s["section"] for s in coverage.get("sections", []) if s["status"] != "available"
    ]
    brief["unavailable"] = deepcopy(c.get("unavailable", []))
    brief["truncated"] = deepcopy(c.get("truncated", []))
    out["omitted_sections"] = (
        coverage["not_queried"] if native_brief else sorted(set(c) - set(brief) - {"coverage"})
    )
    out["omission_note"] = (
        "Selected fields only, including within displayed sections. status returns every supported section."
    )
    out["character"] = brief
    return out


def unit_brief(report):
    out = pick(report, ("format", "state_id", "status", "available", "reason", "unit_id"))
    out["status"] = reading_status(report.get("status", {}))
    if report.get("available"):
        u = report["unit"]
        out["unit"] = pick(
            u,
            (
                "id",
                "name",
                "race",
                "position",
                "alive",
                "on_ground",
                "identity",
                "health",
                "attributes",
                "skills",
                "affiliations",
                "combat",
                "condition",
                "coverage",
                "unavailable",
                "truncated",
                "inventory_truncated",
            ),
        )
        out["unit"]["inventory"] = [
            dict(reading_item(i), **pick(i, ("armor", "weapon"))) for i in u.get("inventory", [])
        ]
        out["unit"]["body"] = pick(u.get("body", {}), ("size",))
        if "parts" in u.get("body", {}):
            # Strike requires native body-part IDs. Hiding healthy anatomy
            # forced a second, full query before the controller could act.
            out["unit"]["body"]["parts"] = [pick(p, ("id", "name")) for p in u["body"]["parts"]]
            out["unit"]["body"]["parts_with_status_flags"] = [
                p for p in u["body"]["parts"] if p.get("active_status_flags")
            ]
    out.update(
        projection=True,
        omitted="Detailed item/container definitions; use unit(view='full'). Body-part IDs remain available for targeting.",
    )
    return out


def render_view(value):
    """Readable concise views; structured unknowns/false/zero remain visible."""
    import json

    lines = [f"State: {value.get('state_id', 'unavailable')}"]
    if value.get("format") == "concise_observation":
        player = value.get("adventurer", {})
        if player:
            lines.append(
                f"{player.get('name', '?')} [{player.get('id', '?')}] at {player.get('position')}"
            )
        for key in (
            "status",
            "adventurer",
            "target_unit",
            "nearby_items",
            "conversation",
            "combat",
            "menu",
            "reports",
            "navigation",
        ):
            if key in value:
                lines.append(key + ": " + json.dumps(value[key], ensure_ascii=False))
        if value.get("map"):
            m = value["map"]
            lines.append("Map origin: " + str(m["origin"]))
            lines.extend(m.get("rows", []))
            lines.append("Units: " + json.dumps(m.get("units", []), ensure_ascii=False))
            lines.append("Landmarks: " + json.dumps(m.get("landmarks", []), ensure_ascii=False))
            for key in (
                "buildings",
                "liquid_regions",
                "feature_distance_from",
                "buildings_truncated",
                "buildings_unavailable_tiles",
            ):
                if key in m:
                    lines.append(key + ": " + json.dumps(m[key], ensure_ascii=False))
        for key in (
            "omitted",
            "reports_omitted",
            "report_omissions",
            "report_cursor",
            "reports_more",
            "next_report_cursor",
            "report_cursor_reset",
        ):
            if key in value:
                lines.append(key + ": " + json.dumps(value[key], ensure_ascii=False))
        lines.extend(value.get("ui_text", []))
        return "\n".join(lines)
    return json.dumps(value, ensure_ascii=False, indent=2)
