"""Adapters for the heavy and impure parts, each behind a protocol.

Separator, acoustic model, transcriber, lyrics source, renderer, downloader, file store and
clock live here. Heavy libraries (torch, transformers) are imported lazily inside the engines.
"""
