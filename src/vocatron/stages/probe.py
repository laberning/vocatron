"""The ``probe`` stage: tags, duration and identity of the song into ``song.json``."""

from vocatron.core.errors import StageError
from vocatron.core.song import SongInfo
from vocatron.core.stage_file import Fingerprint, StageFile
from vocatron.stages.config import Config, ProbeSettings
from vocatron.stages.stage import AUDIO, StageContext, TypedStage


class ProbeStage(TypedStage[ProbeSettings]):
    """Reads what the tags and the file name say about the song."""

    name = "probe"
    version = 1
    inputs = (AUDIO,)
    output = "song.json"
    output_model = SongInfo

    def settings_from(self, config: Config) -> ProbeSettings:
        """Return the ``probe`` section."""
        return config.probe

    def run(
        self, ctx: StageContext, settings: ProbeSettings, fingerprint: Fingerprint
    ) -> StageFile:
        """Write ``song.json``.

        Raises:
            StageError: If the audio file cannot be read or is shorter than ``min_duration``.
        """
        song = ctx.song
        if song.tags is None:
            raise StageError("unreadable-audio", song.tag_error or "cannot read the audio file")
        duration = song.tags.duration
        reasons: list[str] = []
        if duration is None:
            reasons.append("duration unknown")
        elif duration < settings.min_duration:
            raise StageError(
                "too-short",
                f"{duration:.2f} s is shorter than the minimum {settings.min_duration} s",
            )
        ctx.log(f"identity: {song.name} ({duration} s)")
        return SongInfo(
            fingerprint=fingerprint,
            reasons=reasons,
            artist=song.identity.artist,
            title=song.identity.title,
            name=song.name,
            source_file=song.source.name,
            duration=duration,
        )
