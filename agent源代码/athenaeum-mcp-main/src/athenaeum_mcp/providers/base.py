"""Provider base class and shared helpers."""
from __future__ import annotations

from ..models import Work


class Provider:
    """Base class for a scholarly data provider.

    Subclasses override :meth:`search` and any of the optional capability
    methods. The meta-search only calls :meth:`search`; other tools call the
    richer methods on specific providers.
    """

    name: str = "base"

    def available(self) -> bool:
        """Whether this provider is usable in the current configuration."""
        return True

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        year_from: int | None = None,
        year_to: int | None = None,
        open_access_only: bool = False,
    ) -> list[Work]:
        raise NotImplementedError(f"{self.name} does not support search")
