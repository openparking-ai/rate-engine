"""Open Parking AI -- the rate engine.

Price a parking stay, and explain every line of the answer. Standalone, no
dependencies, no database, and no payment of any kind: this module calculates.

Importing the package registers the rule types it ships.
"""

from .rules import daily_max, early_bird, increment, space_surcharge  # noqa: F401

__all__ = ["daily_max", "early_bird", "increment", "space_surcharge"]
