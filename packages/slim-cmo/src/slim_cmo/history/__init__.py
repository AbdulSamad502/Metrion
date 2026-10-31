"""CMO 3.0 M7: listing history, version intelligence and optimisation (docs/specs/slim-cmo-agent.md section 6.19). Pure and deterministic: no model, no I/O, no unit.

Every function here reads saved versions (M6 immutable packs and their saved audits) handed in by the backend and returns plain data. Nothing invents a change, a claim, a search volume, a ranking,
a demand or a business effect; a missing input is reported as unavailable, never as zero."""
