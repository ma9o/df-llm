# World site scan

`dfctl world-scan` and `Client.world_scan()` search world site records by type,
flag or name. The native reader copies site identity, names, tagged subtype,
active native flags and bounding coordinates under DFHack's core lock; Python
filters and ranks the snapshot. It reads no character profiles or UI and sends
no game input. An open game panel does not block the query.

Bounds: 32 search terms, 200 characters per term, 32,768 scanned sites and 100
results per term. Native read errors are counted with at most 20 examples. Each
result's `complete` describes search coverage and `truncated` describes omitted
matching results; the top-level `truncated` describes the scan bound. Missing
subtype records are distinct from failed reads, which prevent a complete
negative search. Distances are Chebyshev distances to surface site centers in
travel tiles, not path lengths, and use the current travel army while offloaded.

## Usage

```sh
./dfctl world-scan LAIR CAVE --match type --limit 5
./dfctl world-scan 'Meandering Prophecy' --match name
./dfctl world-scan HAS_MARKET --match flag --limit 5
./dfctl world-scan --tokens
```

The Python equivalent is `Client().world_scan(["LAIR", "CAVE"], match="type")`.
The default `--match any` matches an exact type or subtype, an active flag or a
name substring. Tokens ignore case and separators; original tokens such as
`LAIR`, `CITY`, `CAVE_DETAILED` and `TREE_CITY` are accepted alongside the
exposed enum names. `--tokens` lists the running game's catalog.

`HAS_MARKET` distinguishes market settlements from hamlets, which share the
native `Town` type. Results keep every active flag, including `RUINED`, for
the controller to assess. A market flag does not prove a living merchant or
stock. An empty flags list means every catalogued flag was false; failed flag
reads are explicitly unavailable.

This searches world records, including places the character does not know.
Coordinates identify site centers, not entrances or verified routes.
