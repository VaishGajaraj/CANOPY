# Dual-use governance and export-control posture

These are **build requirements, not a values statement** — and program offices
reward them, so they also strengthen a proposal. This file exists in the public
repo on purpose.

## What this is

CANOPY is a **friendly-force emissions-detectability auditor** (EMCON / OPSEC
training). During a training exercise it passively records what a friendly unit
radiates, classifies each emitter, coarsely geolocates it, and scores how
detectable each element was. The scoping — friendly side, training — is
deliberate and load-bearing.

## What this is, structurally

A locator. The friendly-force audit framing is the benign face of a capability
that is, at its core, about making emitters findable. The same detector that
audits a friendly unit's hygiene would locate a target for whoever holds it.
That is not a reason not to build it; it is the reason this document is part of
the engineering, not an afterthought.

## Open / closed line (also the moat line)

| Open-sourced (builds TAK-ecosystem trust) | Kept closed (the asset + export-sensitive) |
| --- | --- |
| edge ingestion / the pipes | the **classifier logic** (`classify.py` rule tuning) |
| the ATAK / CoT export path | the **signature library** (the compounding data asset) |
| the schema and fusion scaffolding | tuned DF calibration and any learned models (v1+) |

This repository publishes the **pipes and the scaffolding**. In a real venture
the tuned classifier weights and the accumulated signature library stay private.

## Controls (from the spec, sec 12)

1. **Export control before any public repo, not after.** RF direction-finding
   and signal-classification software can implicate ITAR/EAR depending on
   capability claims. Spend an hour with defense-savvy counsel before publishing
   anything beyond this scaffolding.
2. **Customer line, written down before the term sheet.** Decide now who you
   will and won't sell to. The dangerous drift is the "governments and NGOs"
   path where the buyer stops being a US/allied training customer. Good
   intentions don't survive a fundraise — structure does.
3. **Data-retention limits (PII).** Friendly-force personal-device detections
   are PII. Store band/timing, **not** decoded identifiers; make per-exercise
   purge a first-class feature (see the purge note in `db/schema.sql`); scope the
   library to signatures, not to persistent tracking of individuals.
4. **Claim discipline.** Never oversell fix accuracy or detection confidence.
   Every fix carries its error ellipse; the score prints its assumptions.
   Overclaiming a locator's precision is how a capability ends up misused by
   someone who trusted the number.

> This MVP is a research/training scaffolding demonstrator. It ships no tuned
> classifier weights, no real signature library, and no capability claims beyond
> the documented, simulated feasibility numbers.
