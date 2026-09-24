"""Plum: find the plum deal.

Two ways in:
  * Local deals (local.py): a city or ZIP -> this week's weekly-ad deals at stores near it, from live public sources.
  * Product engine (service.py): identifiers -> textfeatures -> matching -> coupons + pricing -> ranking, fed by
    store adapters with timeouts and partial results. The bundled demo runs it on simulated data.
"""
__version__ = "0.2.0"
