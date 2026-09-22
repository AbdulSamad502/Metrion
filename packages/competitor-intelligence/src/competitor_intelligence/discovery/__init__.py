"""Discovery pipeline — competitor-intelligence-agent.md §6.10-§6.12, C21-C23.

Checkpoint 3 scope only: the `SearchProvider` interface, `MockSearchProvider`, query
generation + the §6.11 privacy boundary, and the budget/cache plumbing that sits around a
`SearchProvider` call. No named search provider is selected, imported or configured
anywhere in this subpackage (C22, AC13) — that is gated on the §6.10.1 provider record and
human approval, both outside an implementation agent's authority.

The discovery run state machine (§6.12.2), identity resolution (§6.13) and relevance
scoring (§6.14) are NOT built here — they are a later checkpoint, built on top of this
package's `SearchProvider`/query-generation/budget/cache seam.
"""

from __future__ import annotations
