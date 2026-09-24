"""Plum: find the plum deal.

Pipeline: identifiers -> textfeatures -> matching -> coupons + pricing -> ranking.
Adapters fetch listings/feeds; service.py orchestrates with timeouts and partial results.
"""
__all__ = ["models", "identifiers", "textfeatures", "matching", "coupons", "pricing", "ranking", "cache", "service"]
