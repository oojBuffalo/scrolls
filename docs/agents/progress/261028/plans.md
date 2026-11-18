# Plans — 2026-10-28

## Next objectives

1. Complete live verification of account-based X/Wikipedia collections and
   optional paid LLM classification/concept synthesis with authorized accounts.
2. Review the hardening changes, then run CI on the final accepted commit.
3. Choose the release version and supported platform statement, update the
   metadata and release notes, then tag and publish when authorized.
4. Keep release work driven by observed failures; do not resume the superseded
   guard-cell queue or add adapters as release preparation.

## 1-day plan

Review the release evidence and remaining external integration checks. Run a
small authorized account dogfood pass and retain redacted outcomes.

## 3-day plan

Confirm the final commit's Python matrix on GitHub and repeat the installed
package custody round-trip on a second machine.

## 7-day plan

Publish the agreed v1 release after the remaining gates pass. Monitor initial
usage for custody and portability failures before expanding scope.
