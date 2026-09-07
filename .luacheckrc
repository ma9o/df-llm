std = "lua53"
codes = true
max_line_length = false

-- DFHack supplies these globals. They are writable because bridge.lua stores
-- session state on dfhack and temporarily adjusts native input/render fields.
globals = {"df", "dfhack"}
read_globals = {"qerror", "dfhack_flags", "SC_WORLD_LOADED", "SC_WORLD_UNLOADED", "SC_MAP_LOADED", "SC_MAP_UNLOADED"}

-- Comment-only branches document intentional no-ops (for example resume input)
-- and metadata fields intentionally omitted from character snapshots.
ignore = {"542"}
