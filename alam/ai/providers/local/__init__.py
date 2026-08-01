"""Local (\\$0) provider implementations (M5.5a task 2).

Never imported at module scope by ``alam.ai.providers`` — same lazy-import
discipline as ``ai/providers/real/``. Never constructed by the unit test
suite either: unlike the paid providers (safe to construct with no
credential validation), constructing any of these can hit the network on a
cache-miss (pulling a model), so rule 8's "zero network calls" is kept by
exercising these only from the eval harness, run manually, not from pytest.
"""

from __future__ import annotations
