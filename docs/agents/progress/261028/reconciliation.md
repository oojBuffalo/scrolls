# Reconciliation — 2026-10-28

The release audit follows the latest steering toward actual dogfood and release
quality. It adds no adapters or product breadth. Existing green tests proved
insufficient at import, capture, filesystem, and generated-view boundaries;
reproduced failures drive the hardening changes.

The fixes preserve canonical raw capture, keep adoption explicit, retain
model-complete exports, and regenerate derived views from the index. Contract
docs and ADR 0120 describe the resulting behavior. The operative vision is
unchanged.

The user did not grant commit, push, tag, or publication authority. Changes
remain available for review without modifying main or publishing a release.
