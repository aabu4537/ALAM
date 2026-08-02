"""Owner session authentication (M7 session 2, ADR-0017).

A new top-level module, not `domain/` (this isn't reading-domain logic —
spoiler rules, confidence decay, ordinal math) and not `ai/providers/`
(not a model capability). Same reasoning `alam/catalog/` used for its own
cross-cutting concern that didn't fit an existing directory.
"""
