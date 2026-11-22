"""The frame of a song's run, one module per pipeline stage, and the commands' orchestration.

Three kinds of module live here (ADR-0042):

- the frame: ``stage`` (the stage protocol and the typed stage), ``registry`` (the stages in
  order), ``batch`` (the runner), ``config``, ``progress`` and ``report``;
- the stages themselves, one module each: ``probe``, ``lyrics``, ``separation``, ``tempo``,
  ``alignment``, ``syllables``, ``layout``, ``render`` and ``cdg``;
- the orchestration behind the commands: ``songs``, ``models``, ``profiles``, ``doctor`` and
  ``bench``.

A stage reads stage files, calls ``core`` and the engines through their protocols, and writes
stage files and status. It never imports a concrete engine.
"""
