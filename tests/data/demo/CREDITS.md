# Credits of the demo songs

Vocatron's demo and test songs are freely licensed. Their audio is not part of this repository:
`make demo-songs` downloads it into `.corpus/demo/` and checks its SHA-256. The lyrics files in
this folder are the artists' own texts and fall under the licence of their song. The song list
with sources and checksums is `demo.toml`.

## Verdächtig

Music and lyrics: Systemabsturz, "Verdächtig" (album "Überwachung zum Mitsingen", 2021).
Licence: CC0 1.0 Universal (<https://creativecommons.org/publicdomain/zero/1.0/>), as stated on
the band's website <https://systemabsturz.band/>. Bandcamp and Wikimedia Commons list the song
under CC BY 3.0 (<https://creativecommons.org/licenses/by/3.0/>); this credit satisfies that
licence too. The audio file comes from a copy of the band's download page on the Internet Archive
(<https://archive.org/details/uberwachung-zum-mitsingen>). The reference frames in
`tests/slow/golden/demo/de/` are made from this song by Vocatron and show its lyrics as karaoke
frames.

## My Favorite Regret

Music - "My Favorite Regret" by Josh Woodward feat. Katie Pederson. Free download:
<https://www.joshwoodward.com/>

Music and lyrics: Josh Woodward feat. Katie Pederson (album "Addressed to the Stars", 2016).
Licence: Creative Commons Attribution 4.0 (<https://creativecommons.org/licenses/by/4.0/>), source
<https://www.joshwoodward.com/song/MyFavoriteRegret>. The audio file comes from the Internet Archive
copy of the album, which lists CC BY 3.0 (<https://archive.org/details/jamendo-158415>); the song is
used unchanged. The reference frames in `tests/slow/golden/demo/en/` are made from this song by
Vocatron and show its lyrics as karaoke frames; they are credited as above (CC BY 4.0, Josh Woodward
feat. Katie Pederson).

The file `Josh Woodward - My Favorite Regret.timing.json` holds the lines, singers and syllable
times that Vocatron found for this song (`make picture-song`); it falls under the same licence
(CC BY 4.0, Josh Woodward feat. Katie Pederson). The pictures of the looks in `docs/assets/` and the
animation on the front page are made from it.
