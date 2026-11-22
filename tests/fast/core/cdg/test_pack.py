"""Stage 1: the names and the order of the MP3+G zip (ADR-0030)."""

from vocatron.core.cdg.pack import CDG_SUFFIX, MP3_SUFFIX, ZIP_TIME, pair_names, zip_name


def test_the_pair_is_the_mp3_then_the_cdg_file_named_after_the_song() -> None:
    assert pair_names("Artist - Title") == ("Artist - Title.mp3", "Artist - Title.cdg")
    assert (MP3_SUFFIX, CDG_SUFFIX) == (".mp3", ".cdg")


def test_the_zip_is_named_after_the_song_too() -> None:
    assert zip_name("Artist - Title") == "Artist - Title.zip"
    assert zip_name("Anna & Ben - Lied (live)") == "Anna & Ben - Lied (live).zip"


def test_every_member_has_the_earliest_time_a_zip_can_hold() -> None:
    assert ZIP_TIME == (1980, 1, 1, 0, 0, 0)  # no clock enters the bytes
