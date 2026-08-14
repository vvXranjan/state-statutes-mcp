"""South Dakota adapter package.

Exposes :class:`~state_statutes_mcp.adapters.south_dakota.adapter.SouthDakotaAdapter`
for the official South Dakota Codified Laws JSON API at
sdlegislature.gov/api/Statutes.
"""

from state_statutes_mcp.adapters.south_dakota.adapter import SouthDakotaAdapter

__all__ = ["SouthDakotaAdapter"]