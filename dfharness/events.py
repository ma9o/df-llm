"""Controller-selected report projection; execution always receives full events."""

from collections import Counter

# Presentation defaults, never a threat assessment. Unrecognized report types
# remain visible, and controller interruption types override the filter.
ROUTINE_EVENTS = {
    "REGULAR_CONVERSATION",
    "SIMPLE_ANIMAL_ACTION",
    "PICK_UP_ITEM",
    "DROP_ITEM",
    "PUT_INTO_CONTAINER",
    "TAKE_OUT_OF_CONTAINER",
    "WEAR_ITEM",
    "REMOVE_ITEM",
    "DRINK_ITEM",
    "EAT_ITEM",
}


def project_events(events, detail="task", force_types=(), force_ids=()):
    if detail not in ("task", "all"):
        raise ValueError("event_detail must be task or all")
    shown, omitted = [], Counter()
    for event in events:
        kind = event.get("type", "unknown")
        if (
            detail == "task"
            and kind in ROUTINE_EVENTS
            and kind not in force_types
            and event.get("id") not in force_ids
        ):
            omitted[kind] += 1
        else:
            shown.append(event)
    return shown, dict(omitted)
