# 0117: One maintenance pass at a time — the run lock

Date: 2026-10-29

Status: accepted

Settles issue #23 (roadmap H443).

## Context

`scrolls maintain` is the recurring custody pass: recheck, regenerate, audit,
record a baseline (roadmap H22 onward). The docs called it "cron-able", but
nothing made scheduling it safe, and nothing scheduled it.

- **The live library went unverified for 66 days.** Every one of its 1,048
  items was last checked on 2026-08-23, by a one-off manual sweep.
- **Two passes could run at once.** A pass that overruns its interval, or a
  manual pass during a scheduled one, would run two recheck loops against
  one ledger and write one trend baseline twice. The MCP `run_maintenance`
  act writes the same snapshot and log, so it could collide too.
- **No recipe existed.** How to schedule it, at what cadence and bound, was
  left to the reader.

The hourly development worker already solved the same problem with a lock:
a run that overruns makes later ticks skip, not overlap.

## Decision

**Every maintenance pass holds a run lock, and a second pass skips.**

- **Where:** `<root>/.maintenance/lock`, beside the snapshot and log it
  protects. `maintain.maintenance_lock` is the one primitive; the CLI pass
  and the MCP act both take it. `--history` is a read and never does.
- **What kind:** an OS file lock (`flock`). It dies with its process, so a
  pass killed mid-run cannot wedge the schedule, and no stale-lock cleanup
  or PID check is needed. The file stays and is reused.
- **Who holds it:** the holder writes `{pid, started_at}` into the file, so
  a refused pass can say what it waited on.
- **How a skip reports:** the CLI writes nothing, prints a typed envelope on
  stderr (`reason: "already_running"`, `holder`), and exits **75**
  (sysexits' EX_TEMPFAIL, "try again later"). Exit 1 keeps its meaning,
  structural issues remain, so a scheduler can tell a skip from a finding.
  The MCP act raises `MaintenanceBusy`.
- **Skip, never queue.** A queued pass would run on stale intent; the next
  scheduled tick is the retry.

The recipe lives in `docs/dogfood.md` ("Scheduling it"): a daily
`maintain --limit 200` under launchd or cron.

## Consequences

- **A schedule cannot double-record.** Overlap is structurally impossible
  for every pass that goes through `maintenance_lock`.
- **POSIX only.** `fcntl.flock` exists on macOS and Linux, the platforms
  Scrolls runs and tests on. Windows would need a different primitive.
- **Not covered:** `scrolls verify` run by hand beside a pass still appends
  to the same ledger. The ledger is append-only, so the cost is a duplicate
  verdict, not a corrupt baseline.

Tests: `tests/test_maintain_lock.py`.
