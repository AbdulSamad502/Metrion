"""Image analysis (P6) - the PURE core: closed schema, provider seam, prompt, parser, trust gate, evaluation maths.

Nothing here touches a network, a database, a file or a clock. A model's reply is untrusted TEXT: it
becomes a seller-visible observation only after `parse` (closed schema, policy filtering) and only
becomes TRUSTED when `trust` finds a passing evaluation for the exact (provider, model, schema_version).
Raw model text is never persisted and never a seller fact.
"""
