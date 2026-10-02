"""Deterministic core of the RFQ Insight skill.

schema / sanitize / preprocess / renderer are ported verbatim from the
Azure Container App (rfq_insight/). extractors and images are new: they
replace the Power Automate OCR extraction with native per-format parsing.

Nothing in this package makes a network call or talks to a model.
"""
