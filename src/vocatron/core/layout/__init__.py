"""The layout: from syllable times, singers, song info and a profile to a scene (ADR-0009).

``phrases`` prepares the lines, ``fit`` splits and shrinks them to the safe area, ``place`` gives
them slots and times, ``cards`` builds the title, break and end screens and the countdown, and
``build`` puts it together (``layout``). The rules of the presentation that check a scene are in
``rules`` (the list and ``scene_findings``) and, by family, ``rules_slots``, ``rules_showing``,
``rules_cards``, ``rules_singers`` and ``rules_scroll``, with what they share in ``rules_base``.
"""
