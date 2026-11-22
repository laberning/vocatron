"""Research code: pure like ``core``, run by the scripts in ``tools/`` and by tests (ADR-0042).

Nothing here runs in a ``vocatron`` command. ``lab`` may import ``core`` only, under the same
forbidden imports as ``core`` (no torch, no I/O, no network, no subprocess). The ``engines`` may
import it (the evaluation worker); ``stages`` and ``cli`` never do. ``cdg`` analyses classic
CD+G discs, ``separation`` measures and compares separation models and prepares the listening
test, ``alignment`` tells what the voice does under every word of a song.
"""
