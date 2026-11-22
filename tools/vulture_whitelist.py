"""Names that vulture cannot see being used (framework entry points).

Each entry carries the reason it is needed. Keep this file short.
"""

from zipfile import ZipInfo

import profile_pictures
from vocatron.core import ffmpeg_cmd, mp4_tags, presets, scene
from vocatron.core.alignment.file import AlignedLine
from vocatron.core.alignment.job import AcousticJob
from vocatron.core.ass import parse
from vocatron.core.cdg import CdgScreen
from vocatron.core.cdg.file import CdgFile, CdgValues
from vocatron.core.layout import rules, sample
from vocatron.core.lyrics.versions import Candidate
from vocatron.core.profiles import model as profile
from vocatron.core.separation.file import SeparationFile
from vocatron.core.song import SongInfo
from vocatron.core.stage_file import Fingerprint
from vocatron.core.status import SongStatus
from vocatron.stages import bench
from vocatron.stages.alignment import (
    Pinned,
    RailParameters,
    SecondVoiceParameters,
    VoiceParameters,
)
from vocatron.stages.cdg import CdgSettings
from vocatron.stages.config import Settings

_ = (
    # Read back by the tests of the MP4 tags (stage 1 and 2), no stage needs it.
    mp4_tags.read_tags,
    # Pydantic reads model_config from every model class.
    Settings.model_config,
    Fingerprint.model_config,
    # Fields are read by Pydantic (validation, JSON output), not by name in the code.
    SongInfo.source_file,
    Candidate.album,  # kept from the LRCLIB record for the stage file of a later story
    SongStatus.stages,
    SongStatus.updated,
    SeparationFile.sample_rate,  # written to separation.json for the sync, read from the file
    # Written to alignment.json for the later stages and the benchmark, read from the file.
    AlignedLine.first_word,
    AlignedLine.word_count,
    # The numbers of the search are in the fingerprint: Pydantic dumps them, no code reads them.
    Pinned.min_confidence,
    Pinned.letter_seconds,
    RailParameters.max_spread,
    RailParameters.min_near_share,
    RailParameters.margin,
    RailParameters.min_lines,
    SecondVoiceParameters.backing_margin,  # in the fingerprint, read by nothing else
    SecondVoiceParameters.lead_silent_share,
    SecondVoiceParameters.lead_deaf,
    SecondVoiceParameters.free_share,
    SecondVoiceParameters.slot_seconds,
    SecondVoiceParameters.slot_reach,
    VoiceParameters.silence_db,
    VoiceParameters.voice_percentile,
    VoiceParameters.voice_margin_db,
    CdgSettings.layout_version,  # the layout code's version in the CD+G stage's fingerprint
    VoiceParameters.floor_percentile,
    VoiceParameters.floor_margin_db,
    VoiceParameters.min_contrast_db,
    VoiceParameters.min_voiced_share,
    VoiceParameters.max_voiced_share,
    VoiceParameters.min_confident_seconds,
    VoiceParameters.confident_word,
    VoiceParameters.close_hole_seconds,
    VoiceParameters.min_voiced_seconds,
    VoiceParameters.min_letter_seconds,
    VoiceParameters.max_letter_seconds,
    VoiceParameters.edge_reach_seconds,
    VoiceParameters.held_tail_seconds,
    VoiceParameters.min_fill_share,
    VoiceParameters.keep_voiced_share,
    VoiceParameters.keep_next_seconds,
    VoiceParameters.keep_direct_seconds,
    VoiceParameters.silent_confidence,
    VoiceParameters.silent_share,
    VoiceParameters.min_judged_seconds,
    VoiceParameters.max_hold_seconds,
    VoiceParameters.snap_seconds,
    VoiceParameters.after_previous_seconds,
    VoiceParameters.open_end_seconds,
    VoiceParameters.late_seconds,
    # The stage 3 test (tests/bench) is the user of the benchmark driver; vulture sees only src.
    bench.run_bench,
    bench.read_run,
    bench.write_run,
    # The tests of the tools are their users; vulture sees only src and tools.
    profile_pictures.overview_stale,
    # Pydantic calls model validators after validation.
    SongStatus.check_current,
    AcousticJob._complete,
    profile.Font._min_below_size,
    profile.CdgLook._min_below_size,
    profile.Scroll._min_glide_within_glide,
    profile.Profile._block_in_line_mode,
    profile.LeadIn._ordered,
    profile.Breaks._ordered,
    profile.Title._ordered,
    profile.Title._short_follows_min,
    profile.Profile._mode_settings_fit,
    profile.Profile._scroll_settings_fit,
    profile.BackgroundMotion._two_to_four,
    # Profile keys that only the YAML file and the schema name: one value is allowed for now
    # (the font is the bundled one), and the description
    # is for the person who reads the file.
    profile.Font.family,
    profile.Profile.description,
    presets.Preset.description,  # one line for the person who reads the preset
    # The scene queries and the parts of the ASS parser that the renderer does not need are the
    # oracle of the fast tests: the writer is checked by reading its output back, and the layout
    # by asking the scene what is visible.
    scene.Scene.visible_at,
    scene.Scene.preview_row,  # the layout sets it, the tests and the renderers read it
    scene.LineElement.wipe_front,
    scene.Rect.overlaps,
    parse.Event.sweep_end,
    parse.Event.fade_out_ms,
    parse.Event.fade_in_ms,
    # The stage 2 tests (tests/slow) draw single frames with it; vulture sees only src.
    ffmpeg_cmd.frame_command,
    # Written to cdg.json for the person who reads it (the values the file was made with and the
    # name of the fallback step), read from the file.
    CdgValues.lead_in_min,
    CdgFile.step_name,
    # The three samples laid out in a given preset are the fixtures of the layout tests (they use
    # them through tests/fakes); the profile check uses the songs (``sample_pieces``).
    sample.sample_scene,
    sample.entchen_scene,
    sample.duet_scene,
    # The attributes of a zip member that make its bytes the same everywhere: zipfile reads them.
    ZipInfo.create_system,
    ZipInfo.external_attr,
    ZipInfo.compress_type,
    # The decoder shows a frame in colours for the tests of the CD+G output, which decode their
    # own packets back; the analysis works on indices.
    CdgScreen.rgb_frame,
    # The call of a rule is typed by this protocol; Python calls it, vulture cannot see that.
    rules.Rule.__call__,
)
