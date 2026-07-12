---
name: aeroing4-static-skill-docs
description: "Create a docs-first AutoQuant static skill file in AeRoing4, matching the existing skill schema and README conventions without changing runtime code."
version: 0.1.0
author: Hermes
license: MIT
platforms: [windows, macos, linux]
metadata:
  hermes:
    tags: [AutoQuant, docs-first, schema, AeRoing4, skill-authoring]
---

# AeRoing4 Static AutoQuant Skill Docs

## Overview

Create ONE docs-first AutoQuant static skill artifact under `backend/config/skills/auto_quant/`.

This skill writes a markdown skill document that matches the existing docs-only skill system contract in `backend/config/skills/auto_quant/schema.json` and `backend/config/skills/auto_quant/README.md`.

Do not modify backend runtime code, pipelines, APIs, frontend, or tests.

## When to Use

- User asks for a new AutoQuant static skill doc.
- User asks for Stage 1 Strategy Validation skill docs.
- User wants skill docs only, with schema validation, no runtime loading.

## Prerequisites

None beyond project read access.

Relevant sources:
- `backend/config/skills/auto_quant/schema.json`
- `backend/config/skills/auto_quant/README.md`

## How to Run

Use `read_file` to inspect the schema and README.
Use `write_file` to create the new skill doc.
Use an ad-hoc verification script if the user requests fresh verification.

## Quick Reference

- Docs root: `backend/config/skills/auto_quant/`
- Schema file: `backend/config/skills/auto_quant/schema.json`
- README file: `backend/config/skills/auto_quant/README.md`

## Procedure

1. Read `backend/config/skills/auto_quant/schema.json` and `backend/config/skills/auto_quant/README.md`.
2. Determine required skill fields from the schema.
3. Choose one stage-scoped skill.
4. Write one markdown file under `backend/config/skills/auto_quant/` following the docs-only format.
5. Validate the example JSON block against the schema contract by inspection or with a temporary verification script.
6. Do not touch backend runtime code, pipelines, APIs, frontend, or tests.

## Common Pitfalls

- Do not add service or router code for a docs-first skill.
- Do not add runtime loading logic.
- Do not modify frontend tabs or API endpoints.
- Do not infer missing schema fields; use only what is documented in `schema.json` and `README.md`.

## Verification Checklist

- [ ] One new docs file was created.
- [ ] File path is under `backend/config/skills/auto_quant/`.
- [ ] Skill example JSON includes the required root fields from `schema.json`.
- [ ] No backend runtime, service, pipeline, API, frontend, or test files were modified.
