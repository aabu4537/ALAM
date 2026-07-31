"""Pure domain logic. No I/O, no ORM, no network, no LLM calls.

Spoiler rules, confidence decay, salience scoring, and ordinal math live here
and must be testable in milliseconds without fixtures. Held to ``mypy --strict``
via the per-module override in pyproject.toml. See CLAUDE.md rule 3.
"""
