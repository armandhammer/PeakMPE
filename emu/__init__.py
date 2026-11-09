"""Function-level emulation harness for the Summit firmware (docs/SIMULATOR.md)."""

from .machine import EmulationError, Machine, PeriphAccess

__all__ = ["EmulationError", "Machine", "PeriphAccess"]
