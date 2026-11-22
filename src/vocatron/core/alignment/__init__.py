"""Forced alignment of lyrics on the singing: pure functions on NumPy arrays (ADR-0002).

``tokens`` turns lyrics into the characters the acoustic model knows, ``ctc`` is the Viterbi
search over the CTC trellis, ``chunks`` plans and stitches the model's pieces and measures the
loudness per frame, ``voice`` finds where the voice sounds (ADR-0012), ``rails`` checks the line
times of an ``.lrc`` against the singing, and ``estimate`` replaces what could not be measured.
``solve`` puts them together. ``file`` is the stage file ``alignment.json`` and ``job`` the
messages between the stage and its acoustic worker (ADR-0042).
"""
