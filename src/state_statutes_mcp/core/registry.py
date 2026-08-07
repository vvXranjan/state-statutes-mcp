"""AdapterRegistry: an explicit, instance-owned map from state code to
adapter.

This registry is deliberately dumb: it holds adapter instances that
have already been constructed elsewhere and lets callers register,
retrieve, and enumerate them by state code. It does not construct
adapters, does not discover them by scanning packages, and does not
decide which adapters exist — all of that is the caller's
responsibility, performed via explicit ``register`` calls.

There is no module-level instance and no other global mutable state:
every ``AdapterRegistry()`` is an independent registry, so callers that
want a single shared registry own that choice (and that instance)
themselves, and callers that want several independent registries
(for example, one per test) get that for free.
"""

from __future__ import annotations

from typing import Sequence

from state_statutes_mcp.adapters.base import BaseStateAdapter


class DuplicateAdapterError(Exception):
    """Raised when ``register`` is called for a state code that already
    has an adapter registered.

    Attributes:
        state_code: The state code that was already registered.
    """

    def __init__(self, state_code: str) -> None:
        self.state_code = state_code
        super().__init__(
            f"An adapter is already registered for state code {state_code!r}; "
            "unregister it first if you intend to replace it."
        )


class UnknownStateError(Exception):
    """Raised when ``get`` is called for a state code with no registered
    adapter.

    Attributes:
        state_code: The state code that was requested.
    """

    def __init__(self, state_code: str) -> None:
        self.state_code = state_code
        super().__init__(f"No adapter is registered for state code {state_code!r}.")


class AdapterRegistry:
    """An explicit, non-singleton registry of state adapters, keyed by
    two-letter state code.

    Registration is entirely explicit: nothing is registered
    automatically, and constructing a registry does not construct or
    locate any adapters. Callers build their own adapter instances and
    hand them to :meth:`register` one at a time (typically during
    application start-up), then look them up by state code via
    :meth:`get`.

    State codes are matched case-insensitively and stored upper-case
    internally, so ``"tx"`` and ``"TX"`` refer to the same registration.

    Example:
        >>> registry = AdapterRegistry()
        >>> registry.register(some_texas_adapter)
        >>> registry.get("tx") is some_texas_adapter
        True
        >>> registry.list_state_codes()
        ('TX',)
    """

    def __init__(self) -> None:
        """Create an empty registry.

        Each instance owns its own, independent mapping — there is no
        shared or module-level state, so creating multiple registries
        (e.g. one per test, or one per tenant) never causes them to
        interfere with one another.
        """
        self._adapters: dict[str, BaseStateAdapter] = {}

    def register(self, adapter: BaseStateAdapter) -> None:
        """Register ``adapter`` under its own ``state_code``.

        Args:
            adapter: A constructed adapter instance. Its ``state_code``
                property determines the key it is registered under.

        Raises:
            DuplicateAdapterError: If an adapter is already registered
                for this ``state_code``. Callers who intend to replace
                a registration must call :meth:`unregister` first, so
                that overwriting an existing adapter is always an
                explicit, deliberate act rather than an accidental one.
        """
        state_code = adapter.state_code.upper()
        if state_code in self._adapters:
            raise DuplicateAdapterError(state_code)
        self._adapters[state_code] = adapter

    def unregister(self, state_code: str) -> None:
        """Remove the adapter registered for ``state_code``, if any.

        Args:
            state_code: Two-letter state code to unregister. Matched
                case-insensitively.

        Raises:
            UnknownStateError: If no adapter is registered for
                ``state_code``.
        """
        key = state_code.upper()
        try:
            del self._adapters[key]
        except KeyError:
            raise UnknownStateError(key) from None

    def get(self, state_code: str) -> BaseStateAdapter:
        """Retrieve the adapter registered for ``state_code``.

        Args:
            state_code: Two-letter state code to look up. Matched
                case-insensitively.

        Returns:
            The adapter instance previously passed to :meth:`register`
            for this state code.

        Raises:
            UnknownStateError: If no adapter is registered for
                ``state_code``.
        """
        key = state_code.upper()
        try:
            return self._adapters[key]
        except KeyError:
            raise UnknownStateError(key) from None

    def is_registered(self, state_code: str) -> bool:
        """Check whether an adapter is registered for ``state_code``.

        Args:
            state_code: Two-letter state code to check. Matched
                case-insensitively.

        Returns:
            ``True`` if an adapter is registered for this state code,
            ``False`` otherwise. Never raises for an unregistered code.
        """
        return state_code.upper() in self._adapters

    def list_state_codes(self) -> Sequence[str]:
        """List the state codes with a registered adapter.

        Returns:
            An immutable, alphabetically sorted tuple of upper-case
            two-letter state codes. Sorted so callers get a stable,
            deterministic order regardless of registration order.
        """
        return tuple(sorted(self._adapters))

    def list_adapters(self) -> Sequence[BaseStateAdapter]:
        """List the registered adapters themselves.

        Returns:
            An immutable tuple of adapter instances, ordered to match
            :meth:`list_state_codes` (alphabetically by state code).
        """
        return tuple(self._adapters[code] for code in self.list_state_codes())

    def __len__(self) -> int:
        """Return the number of registered adapters."""
        return len(self._adapters)

    def __contains__(self, state_code: str) -> bool:
        """Support ``state_code in registry`` as an alias for
        :meth:`is_registered`."""
        return self.is_registered(state_code)