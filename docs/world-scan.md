# World site scan

`dfctl world-scan` and `Client.world_scan()` share one implementation. The native
reader copies only site identity, names, tagged subtype, active native flags, and
bounding coordinates. `--match flag HAS_MARKET` locates market settlements;
`RUINED` remains a factual flag for the controller to assess. A market record
does not verify the presence or stock of a merchant. Flag names come from the
running game's enum, and failed reads remain unknown, including on older cached
snapshots without flags. Sorting uses the current travel army while offloaded.
It uses named fields and live enum mappings, reads no character profiles or UI,
and sends no game inputs. An open game panel does not block the query.

The index is copied under DFHack's core lock. Sending concurrent RPCs cannot
parallelize those native reads: `library/RemoteServer.cpp` in the pinned DFHack
reference suspends the core while executing them. Python owns filtering and
ranking on the plain snapshot. `workers=2..8` partitions it among separate
processes; each retains bounded nearest matches and exact counts. The merge
preserves the same ordering and counts as one worker. Worker failure reports an
error without retrying the snapshot or returning partial success. The subprocess
module entry works for CLI, scripts, and Python callers using stdin or a REPL.

Bounds: 32 search terms, 200 characters per term, 32,768 scanned sites, 100 results
per term, eight workers, and a 30-second worker timeout. Native read errors are
counted with at most 20 examples. Each result's `complete` describes search
coverage; `truncated` describes omitted matching results. The top-level
`truncated` describes the scan bound. Missing subtype records are distinct from
failed reads, which prevent a complete negative subtype search. Distances are
Chebyshev distances to surface site centers in travel tiles, not path lengths.

## Measurements, 2026-09-07

Live DF 0.53.16 / DFHack 53.16-r1.1 under CrossOver, 793 sites. All reads left the
current panel alone. No game inputs were issued.

| Measurement | One worker | Four workers |
| --- | ---: | ---: |
| Filter five terms on the same snapshot, median of five | 2.92 ms | 38.25 ms |
| Complete Python query, median of three | 115.14 ms | 160.04 ms |
| DFHack RPCs per query | 1 | 1 |
| Controller output for two terms, three results each | 649 tokens | 649 tokens |

The snapshot was 143,856 bytes and its initial read took 124.82 ms. The complete
query samples used `LAIR CAVE --match type --limit 3`; their output was 1,967 bytes
under the named `o200k_base` tokenizer. Counts were 139 lairs and 25 caves. The
five-term filter samples used default `any` matching, which also finds places
whose names contain a term, so their cave count was 34. Both worker counts
returned identical results from the same snapshot. Parallelism does not help this
world: the default remains one worker, and native transport dominates the cost.
These are local samples, not a throughput guarantee for other worlds or hosts.

Verification: 436 offline Python tests and 300 isolated native fixtures passed,
along with lint, format, type, dead-code, Lua, shell, and package-build checks.
New cases cover real worker processes, global ranking/count preservation,
validation before RPC, no retry after worker failure, literal Unicode names,
zero values, partial coverage, optional subtype reads, bounds, and live token
catalog enumeration.
