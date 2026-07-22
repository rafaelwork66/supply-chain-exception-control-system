"""Named deterministic random streams for synthetic generation."""

from __future__ import annotations

import hashlib
import random


class RandomContext:
    """Create isolated random streams from one seed and generator version."""

    def __init__(self, seed: int, generator_version: str) -> None:
        """Initialise the context."""

        self._seed = seed
        self._generator_version = generator_version

    def stream(self, domain: str) -> random.Random:
        """Return a deterministic random stream for a named domain."""

        material = f"{self._generator_version}:{self._seed}:{domain}".encode()
        digest = hashlib.sha256(material).digest()
        return random.Random(int.from_bytes(digest[:8], byteorder="big", signed=False))
