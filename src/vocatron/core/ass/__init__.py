r"""The ASS subtitle file of a scene, and a small parser that reads it back (ADR-0002, ADR-0009).

The writer draws the scene with libass in mind: every text is placed with ``\an7\pos`` at the
top left of its line cell, a lyric line sweeps with ``\kf`` (or ``\k``) per syllable, and the
countdown, the dots and the bar are vector drawings and the timer of a break screen is one
plain text event per second. The parser reads the events, the karaoke
durations and the positions back, so that the tests can compare the times of the file with the
scene; the renderer uses it to tell whether the file draws any text (then libass must name its
font).

All times are in centiseconds in an ASS file; the writer rounds each boundary once from the
seconds of the scene, so the durations of a line add up to its end to within half a centisecond.

The effects of a video-only look (ADR-0032) are drawn here: a glow is a second event under the
line that draws a blurred copy of the text in the glow colour, swept with the same ``\kf`` or
``\k`` as the text so that it grows with the colour, a pop is a ``\t`` transform of
the scale on each word, dimmed upcoming lines start at a lower alpha that a ``\t`` brings back to
full at the first syllable, and a fade is ``\fad``. A slide cannot be one event (``\move`` moves
once), so a line that slides is three: coming in, being sung and going out.

A line in scroll mode (ADR-0033) is one event per stretch of its path: a still part is a ``\pos``,
a glide a ``\move`` that fades the line in or out where it comes or goes. The column glides
between two lines; where the silence after a line is short, the line glides out during its last
``min_glide`` seconds (ADR-0036). The wipe lies in one still part and, where the line glides
out while it is still sung, goes on in the moving part after it (its ``\k`` offsets start where
the wipe has got to). The parts before hold the unsung text, the parts after the wipe the sung
text in the sung colour. A sung line is dimmed by a ``\t`` after its last syllable.

At the end of a part of the column (before a long break) the lines fade out over ``ending.fade``
seconds in a final plain event in the sung colours (ADR-0040). The break screen of a
scrolling look stands still, drawn like that of the other looks.

``write`` holds the writer (``write_ass``), ``parse`` the parser (``parse_ass``, ``Script``,
``Event``, ``Sweep``) and ``timing`` the centisecond helpers both use.
"""
