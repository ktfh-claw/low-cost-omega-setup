# das-read plugin — DAS read path as a mounted config artifact (iteration 31)

Bind-mounted read-only into the stock plugins tree (see
`plugins.yaml.overlay` + `start.sh`). The plugin rebinds the `das-retrieve`
skill clause — same remove-then-add single-definition invariant as the
`das-write` plugin — so **both the clause and the adapter implementation
come from this repo's mounts**, converging the live deployment on the
"image + mounts/config" architecture documented in
[`docs/architecture.md`](../../../docs/architecture.md).

The plugin also re-registers the skill description the LLM sees: issue-2
v4 (2026-10-28) adds the atom-handles clause — retrieval receipts carry
per-answer stored-atom handles the agent can quote verbatim.

## Provenance context (read the docs truth note)

The deployed agent image is the **ktfh-claw/OmegaClaw-Core fork build**
(`omegaclaw:das-f38217f`), not a stock upstream image — upstream publishes
no container image at all (verified 2026-10-20: no `ghcr.io/singnet/omega`,
no `trueagi/omega` manifests; upstream CI builds without pushing). The
`das-retrieve` skill + the v1 adapter were **fork-baked** into that image
(pre-campaign). This plugin supersedes the baked clause at runtime: after
this plugin loads, the clause routes to the plugin-mounted v2 module
(`das_skills_read.py`, identical bytes to `deploy/omega/das-read/das_skills.py`).

On a genuinely stock image (if upstream ever publishes one) the plugin's
remove-then-add still works (the match simply binds nothing and the clause
is added fresh), but the skill would additionally need `add-skill`
registration for the LLM to see it — deferred until such an image exists.

## Gate

`OMEGA_DAS_ENABLED=1` (stock-style env, read by the module via
`os.environ` — the same gate the v1/v2 adapter always used; verified to
survive the image env handling live). When unset, the plugin logs
`das-read-plugin "DAS read path not bridged"` and changes nothing.

## Validation (2026-10-20, iteration 31)

Test container, both plugins mounted + the real overlay, against the LIVE
read-proxy — `tests/run_driver.sh`: PROBE-1/2 metta-mode read OK with
identical single-line output (single-definition check), PROBE-3 proxy
error surfaced verbatim; disabled run leaves the stock clause untouched.
Matrix in `memory/omega-das-bridge/evidence/iter31-align/` (gateway
workspace). Live attach: iteration 31 record in `docs/status.md`.
