"""
registry.py

JARVIS Agent Layer: Generic Registry with Decorator-Based Registration.

Import with:
    from jarvis_core.agent.registry import RegistryBase

This module provides:
    1. RegistryBase[T] — A generic base class that any registrable subsystem
       (Tool, Engine, Agent, Channel) can subclass to get automatic
       name-based lookup, listing, and decorator registration.

=============================================================================
THE BIG PICTURE
=============================================================================

Without RegistryBase:
    -> Every subsystem (tools, engines, agents, channels) hand-rolls its own
       dict + register() + get() + list() pattern. 4 subsystems × 4 methods
       = 16 nearly-identical functions, each with its own bugs.
    -> Adding a new tool requires editing a central "tool_map" dict in a
       file that every tool imports. Merge conflicts when two devs add tools.

With RegistryBase:
    -> Subclass once. Get register/get/list for free.
    -> Registration is a @decorator on the implementation class — no central
       file to edit, no merge conflicts, no import-time side effects.
    -> Per-subclass isolation: Tool._registry is a separate dict from
       Engine._registry. They cannot collide.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: A subsystem (e.g., Tool) subclasses RegistryBase[Tool].
        __init_subclass__ creates an isolated _registry dict for that class.
        ↓
STEP 2: Developer decorates a concrete implementation:
            @CalculatorTool.register("calculator")
            class CalculatorTool(Tool): ...
        The decorator calls cls._registry[name] = implementation_class.
        ↓
STEP 3: At runtime, the agent calls Tool.get("calculator") to retrieve
        the class, then instantiates it.
        ↓
STEP 4: Tool.list_registered() returns all registered tool names for
        schema generation and discovery.

=============================================================================

Ported from OpenJarvis RegistryBase[T] (Apache 2.0).
Source: OpenJarvis/src/openjarvis/core/registry.py:19-172
Adapted: frozen dataclass metadata, per-subclass isolation via
         __init_subclass__, stricter typing.
"""

from __future__ import annotations

from typing import (
    Any,
    ClassVar,
    Dict,
    Generic,
    List,
    Optional,
    Type,
    TypeVar,
)

T = TypeVar("T")


# =============================================================================
# Part 1: THE GENERIC REGISTRY
# =============================================================================

class RegistryBase(Generic[T]):
    """
    LAYER: Agent — Generic decorator-based registry.

    Purpose:
        - Provide automatic name→class lookup for any registrable subsystem
        - Enforce per-subclass isolation (Tool._registry ≠ Engine._registry)
        - Support decorator-style registration with zero boilerplate

    How it works:
        - __init_subclass__ fires when a class directly subclasses RegistryBase.
          It installs a fresh _registry dict on that subclass ONLY.
        - The @register(name) classmethod returns a decorator that maps
          name → implementation class in that subclass's _registry.
        - get(name) and list_registered() read from that same dict.
        - Subclasses of subclasses (e.g., CalculatorTool(Tool)) do NOT get
          their own _registry — they register INTO their parent's registry.
          This is intentional: Tool.get("calculator") finds CalculatorTool.
    """

    # Each direct subclass of RegistryBase gets its own isolated dict.
    # This annotation tells type checkers the attribute exists, but the
    # actual dict is created per-subclass in __init_subclass__.
    _registry: ClassVar[Dict[str, Type[Any]]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """
        Called automatically when a class inherits from RegistryBase.

        Only creates a NEW _registry dict for classes that DIRECTLY inherit
        from RegistryBase (e.g., class Tool(RegistryBase[Tool])).

        Classes that inherit from Tool (e.g., class CalculatorTool(Tool))
        do NOT get a new _registry — they share Tool._registry. This is
        the per-subclass isolation mechanism.
        """
        super().__init_subclass__(**kwargs)

        # Walk the MRO to check if THIS class's direct parent is RegistryBase.
        # If so, it's a "registry owner" (Tool, Engine, Agent, Channel) and
        # gets a fresh dict. Otherwise it's a concrete implementation that
        # registers into the owner's dict.
        for base in cls.__mro__[1:]:
            if base is RegistryBase:
                # Direct child of RegistryBase → create isolated registry
                cls._registry = {}
                break
            if hasattr(base, "_registry"):
                # Indirect child (e.g., CalculatorTool → Tool → RegistryBase)
                # Shares the parent's registry — do NOT overwrite.
                break

    @classmethod
    def register(cls, name: str) -> Any:
        """
        Decorator factory that registers an implementation class under `name`.

        Usage:
            @Tool.register("calculator")
            class CalculatorTool(Tool):
                ...

        The decorated class is returned unmodified — this is a pure
        registration side-effect, not a wrapper.

        Args:
            name: The unique string key for this implementation.
                  Convention: lowercase_snake_case.

        Returns:
            A decorator that accepts the implementation class.

        Raises:
            ValueError: If `name` is already registered in this registry.
        """
        def decorator(impl_cls: Type[T]) -> Type[T]:
            if name in cls._registry:
                existing = cls._registry[name]
                raise ValueError(
                    f"[Registry] Name '{name}' already registered "
                    f"by {existing.__name__}. Cannot re-register "
                    f"with {impl_cls.__name__}."
                )
            cls._registry[name] = impl_cls
            return impl_cls
        return decorator

    @classmethod
    def get(cls, name: str) -> Optional[Type[T]]:
        """
        Look up a registered implementation by name.

        Args:
            name: The registered name string.

        Returns:
            The implementation class, or None if not found.
        """
        return cls._registry.get(name)

    @classmethod
    def get_or_raise(cls, name: str) -> Type[T]:
        """
        Look up a registered implementation by name; raise if missing.

        Args:
            name: The registered name string.

        Returns:
            The implementation class.

        Raises:
            KeyError: If `name` is not registered.
        """
        impl = cls._registry.get(name)
        if impl is None:
            available = ", ".join(sorted(cls._registry.keys())) or "(none)"
            raise KeyError(
                f"[Registry] '{name}' not found. "
                f"Available: {available}"
            )
        return impl

    @classmethod
    def list_registered(cls) -> List[str]:
        """Return sorted list of all registered names in this registry."""
        return sorted(cls._registry.keys())

    @classmethod
    def count(cls) -> int:
        """Return the number of registered implementations."""
        return len(cls._registry)


# =============================================================================
# MAIN ENTRY POINT (Smoke test: register and retrieve)
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  RegistryBase Smoke Test")
    print("=" * 60)

    # -- Define two independent registries ---------------------------------

    class Engine(RegistryBase["Engine"]):
        """Example registry owner: Engines."""
        pass

    class Channel(RegistryBase["Channel"]):
        """Example registry owner: Channels."""
        pass

    # -- Register implementations via decorator ----------------------------

    @Engine.register("openrouter")
    class OpenRouterEngine(Engine):
        def run(self) -> str:
            return "OpenRouter inference"

    @Engine.register("runpod")
    class RunPodEngine(Engine):
        def run(self) -> str:
            return "RunPod inference"

    @Channel.register("telegram")
    class TelegramChannel(Channel):
        def send(self, msg: str) -> None:
            print(f"[Telegram] {msg}")

    # -- Verify isolation --------------------------------------------------

    print(f"\n  Engine registry : {Engine.list_registered()}")
    print(f"  Channel registry: {Channel.list_registered()}")
    print(f"  Engine count    : {Engine.count()}")
    print(f"  Channel count   : {Channel.count()}")

    # -- Retrieve and instantiate ------------------------------------------

    openrouter_cls = Engine.get_or_raise("openrouter")
    engine_instance = openrouter_cls()
    print(f"\n  Engine.get('openrouter').run() => '{engine_instance.run()}'")

    # -- Verify KeyError on missing ----------------------------------------

    try:
        Engine.get_or_raise("nonexistent")
    except KeyError as e:
        print(f"  Engine.get_or_raise('nonexistent') => KeyError: {e}")

    # -- Verify duplicate name rejection -----------------------------------

    try:
        @Engine.register("openrouter")
        class DuplicateEngine(Engine):
            pass
    except ValueError as e:
        print(f"  Duplicate register => ValueError: {e}")

    # -- Verify cross-registry isolation -----------------------------------

    assert Engine.get("telegram") is None, "Engine should not see Channel entries"
    assert Channel.get("openrouter") is None, "Channel should not see Engine entries"
    print("\n  [OK] Cross-registry isolation verified.")

    print("\n" + "=" * 60)
    print("  All smoke tests passed.")
    print("=" * 60)
