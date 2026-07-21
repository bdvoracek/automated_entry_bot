"""Automated Entry Bot — enter prediction competitions using 51Folds forecasts.

First platform: Metaculus. Predictions produced by 51Folds.AI models,
aggregated across N runs via (mean + median) / 2, then mapped to Metaculus
forecast payloads (binary / multiple_choice / numeric-CDF).
"""

__version__ = "0.1.0"
