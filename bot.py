"""Compatibility facade for the modular ltabot package.

This file re-exports the public API used by tests and external callers, while the
actual implementation lives under the ltabot/ package following SOLID principles.
"""

from ltabot import *  # noqa: F401,F403

if __name__ == "__main__":
    from ltabot import main
    main()
