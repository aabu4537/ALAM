"""Real provider implementations (M5.5a).

Never imported at module scope by ``alam.ai.providers`` — the resolvers
import these lazily, inside the branch that actually needs one, so the
default ("fake") path used by every other test never pulls an SDK in.
``tests/test_real_providers.py`` does import these directly, but only to
construct them and check Protocol conformance under the same
socket-blocking guard ``TestNoNetwork`` uses — rule 8's "zero network
calls in tests" holds either way; it's enforced, not just assumed.
"""

from __future__ import annotations
