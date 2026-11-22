"""Stage 1: the separation stage on a fake separator: outputs, skip, settings, failure isolation."""

from pathlib import Path

import pytest

from fakes.songs import FakeWorld
from vocatron.core.errors import StageError
from vocatron.core.models import DEFAULT_VOCALS_MODEL, KARAOKE_MODEL, find_model
from vocatron.core.separation.file import STEM_NAMES, SeparationFile, stem_path
from vocatron.core.separation.job import StemGains
from vocatron.core.status import SongStatus
from vocatron.stages.batch import run_song
from vocatron.stages.config import Config, SeparationSettings
from vocatron.stages.separation import SeparationStage
from vocatron.stages.songs import discover
from vocatron.stages.stage import LOG_FILE

MUSIC = Path("/music")
AUDIO = MUSIC / "Artist - Title.mp3"
WORK = MUSIC / "karaoke" / "Artist - Title"
MODELS_DIR = Path(".cache/models")  # the default of ``Config()``, relative as in the fast tests


def run(world: FakeWorld, config: Config | None = None, *, force: bool = False) -> SongStatus:
    return world.run(AUDIO, config, force=force)


def separation_of(world: FakeWorld) -> SeparationFile:
    text = world.store.read_text(WORK / "separation.json")
    assert text is not None
    return SeparationFile.model_validate_json(text)


def with_settings(**settings: object) -> Config:
    return Config(separation=SeparationSettings.model_validate(settings))


def test_the_stage_writes_four_stems_and_separation_json(one: FakeWorld) -> None:
    status = run(one)
    assert status.state == "ok"
    for name in STEM_NAMES:
        assert one.store.size(WORK / stem_path(name)) is not None
    file = separation_of(one)
    assert file.stems == [stem_path(name) for name in STEM_NAMES]
    assert (file.keep_backing, file.device, file.sample_rate, file.samples) == (
        True,
        "cpu",
        44100,
        88200,
    )
    assert [(m.name, m.revision) for m in file.models] == [
        (DEFAULT_VOCALS_MODEL, find_model(DEFAULT_VOCALS_MODEL).revision),
        (KARAOKE_MODEL, find_model(KARAOKE_MODEL).revision),
    ]
    assert file.gains == StemGains()


def test_the_separator_gets_the_models_from_the_model_folder_with_their_pins(
    one: FakeWorld,
) -> None:
    run(one)
    (request,) = one.separator.requests
    (vocals,), karaoke = request.plan.vocals_models, request.plan.karaoke_model
    assert vocals.checkpoint.endswith("bs-roformer-leap/bs_roformer_leap_voc.ckpt")
    assert vocals.config.endswith("bs-roformer-leap/bs_leap_voc_conf.yaml")
    assert (vocals.chunk_size, vocals.num_overlap, vocals.precision) == (881559, 2, "fp16")
    assert karaoke.checkpoint.endswith("bs-roformer-karaoke/karaoke_bs_roformer_anvuew.ckpt")
    assert (karaoke.chunk_size, karaoke.num_overlap) == (640000, 4)
    assert str(MODELS_DIR) in vocals.checkpoint
    assert (request.audio, request.work_dir, request.duration) == (AUDIO, WORK, 180.0)
    assert request.log_path == WORK / LOG_FILE
    assert (request.device, request.plan.keep_backing) == ("auto", True)
    assert (request.timeout_factor_gpu, request.timeout_factor_cpu) == (2.0, 30.0)


def test_the_models_are_downloaded_on_first_use_and_declared_by_name(one: FakeWorld) -> None:
    assert SeparationStage().required_models(one.context(AUDIO), Config()) == (
        DEFAULT_VOCALS_MODEL,
        KARAOKE_MODEL,
    )
    run(one)
    names = {str(destination.parent.name) for _, destination in one.downloader.calls}
    assert names == {DEFAULT_VOCALS_MODEL, "bs-roformer-karaoke", "wav2vec2-de"}  # the last is next
    assert len(one.downloader.calls) == 4 + 5


def test_offline_without_the_models_the_stage_fails_with_the_command_to_run(one: FakeWorld) -> None:
    cfg = Config()
    status = run_song(one.song(AUDIO, cfg), cfg, one.engines, force=False, offline=True)
    assert status.state == "failed"
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("separation", "models-missing")
    assert "vocatron models download bs-roformer-leap bs-roformer-karaoke" in status.error.message
    assert one.separator.requests == []


def test_a_second_run_with_the_same_inputs_and_settings_skips_the_stage(one: FakeWorld) -> None:
    run(one)
    status = run(one)
    assert [o.action for o in status.stages] == ["skipped"] * 9
    assert len(one.separator.requests) == 1


@pytest.mark.parametrize("name", STEM_NAMES)
def test_a_deleted_stem_runs_only_this_stage_again(one: FakeWorld, name: str) -> None:
    run(one)
    one.store.delete(WORK / stem_path(name))
    status = run(one)
    assert [(o.stage, o.action) for o in status.stages] == [
        ("probe", "skipped"),
        ("lyrics", "skipped"),
        ("separation", "ran"),
        ("tempo", "skipped"),  # the stem came back the same
        ("alignment", "skipped"),
        ("syllables", "skipped"),
        ("layout", "skipped"),
        ("render", "skipped"),
        ("cdg", "skipped"),
    ]
    assert len(one.separator.requests) == 2
    assert one.store.size(WORK / stem_path(name)) is not None
    log = "\n".join(one.store.log_lines(WORK / LOG_FILE))
    assert f"separation: {stem_path(name)} missing" in log


def test_the_stage_declares_its_stems_as_outputs() -> None:
    assert SeparationStage().extra_outputs == tuple(stem_path(name) for name in STEM_NAMES)


def test_force_runs_the_stage_again(one: FakeWorld) -> None:
    run(one)
    run(one, force=True)
    assert len(one.separator.requests) == 2


def test_changed_audio_runs_the_stage_again(one: FakeWorld) -> None:
    run(one)
    one.store.add(AUDIO, b"another recording")
    run(one)
    assert len(one.separator.requests) == 2


def test_no_backing_reruns_only_this_stage(one: FakeWorld) -> None:
    run(one)
    status = run(one, with_settings(keep_backing=False))
    assert [(o.stage, o.action) for o in status.stages] == [
        ("probe", "skipped"),
        ("lyrics", "skipped"),
        ("separation", "ran"),
        ("tempo", "ran"),  # only because the fake stems differ with the setting
        ("alignment", "ran"),
        ("syllables", "ran"),
        ("layout", "ran"),
        ("render", "ran"),
        ("cdg", "ran"),
    ]
    assert separation_of(one).keep_backing is False
    assert one.separator.requests[-1].plan.keep_backing is False
    assert one.store.read_text(WORK / stem_path("karaoke")) == "karaoke backing=False"


@pytest.mark.parametrize(
    "settings", [{"device": "cpu"}, {"timeout_factor_gpu": 5.0}, {"timeout_factor_cpu": 99.0}]
)
def test_device_and_timeouts_do_not_change_the_result_so_they_rerun_nothing(
    one: FakeWorld, settings: dict[str, object]
) -> None:
    run(one)
    status = run(one, with_settings(**settings))
    assert [o.action for o in status.stages] == ["skipped"] * 9
    assert len(one.separator.requests) == 1


def test_the_device_setting_reaches_the_separator(one: FakeWorld) -> None:
    run(one, with_settings(device="cpu", timeout_factor_cpu=10.0))
    (request,) = one.separator.requests
    assert (request.device, request.timeout_factor_cpu) == ("cpu", 10.0)


def test_the_fingerprint_names_the_models_with_their_inference_settings_and_keep_backing(
    one: FakeWorld,
) -> None:
    declared = SeparationStage().declared_settings(one.context(AUDIO), Config())
    dumped = declared.model_dump()
    assert dumped["keep_backing"] is True
    assert dumped["models"][0]["inference"] == {
        "chunk_size": 881559,
        "num_overlap": 2,
        "precision": "fp16",
    }
    assert [m["name"] for m in dumped["models"]] == [DEFAULT_VOCALS_MODEL, KARAOKE_MODEL]


def test_a_stem_the_separator_did_not_write_fails_the_song(one: FakeWorld) -> None:
    one.separator.skip = {"backing"}
    status = run(one)
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("separation", "separation-failed")
    assert "stems/backing.flac" in status.error.message


def test_a_failure_of_one_song_leaves_the_next_song_untouched(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    world.add_song(MUSIC / "b.mp3")
    cfg = Config()
    songs = discover(MUSIC, cfg, world.engines)
    world.separator.fail_with = StageError("out-of-memory", "GPU is full")
    bad = run_song(songs[0], cfg, world.engines, force=False)
    world.separator.fail_with = None
    good = run_song(songs[1], cfg, world.engines, force=False)
    assert (bad.state, good.state) == ("failed", "ok")
    assert bad.error is not None
    assert (bad.error.stage, bad.error.kind, bad.error.message) == (
        "separation",
        "out-of-memory",
        "GPU is full",
    )


def test_warnings_of_the_separator_are_logged_and_recorded(one: FakeWorld) -> None:
    one.separator.warnings = ["no usable GPU was found; separating on the CPU, about 20x slower"]
    status = run(one)
    assert status.state == "ok"  # a warning is no reason for review
    assert separation_of(one).warnings == one.separator.warnings
    log = "\n".join(one.store.log_lines(WORK / LOG_FILE))
    assert "separation: warning: no usable GPU was found" in log


def test_the_gains_are_recorded_in_the_stage_file(one: FakeWorld) -> None:
    one.separator.gains = StemGains(instrumental=0.6, karaoke=0.55)
    run(one)
    gains = separation_of(one).gains
    assert (gains.instrumental, gains.karaoke, gains.lead) == (0.6, 0.55, 1.0)


def test_an_ensemble_hands_both_vocals_models_to_the_separator_with_their_targets(
    one: FakeWorld,
) -> None:
    config = with_settings(model=["bs-roformer-ep317", "bs-roformer-leap-inst"])
    assert SeparationStage().required_models(one.context(AUDIO), config) == (
        "bs-roformer-ep317",
        "bs-roformer-leap-inst",
        KARAOKE_MODEL,
    )
    assert run(one, config).state == "ok"
    (request,) = one.separator.requests
    first, second = request.plan.vocals_models
    assert (first.target, second.target) == ("vocals", "instrumental")
    assert second.checkpoint.endswith("bs-roformer-leap-inst/Xe/bs_leap_xe_inst.ckpt")
    assert [m.name for m in separation_of(one).models] == [
        "bs-roformer-ep317",
        "bs-roformer-leap-inst",
        KARAOKE_MODEL,
    ]


def test_the_ensemble_the_karaoke_input_and_the_karaoke_model_each_re_run_the_stage(
    one: FakeWorld,
) -> None:
    run(one)
    for settings in (
        {"model": ["bs-roformer-ep317", "bs-roformer-leap"]},
        {"karaoke_input": "mix"},
        {"karaoke_model": "bs-roformer-karaoke-frazer"},
    ):
        status = run(one, with_settings(**settings))
        assert [o.action for o in status.stages if o.stage == "separation"] == ["ran"], settings


def test_the_karaoke_input_and_model_reach_the_separator(one: FakeWorld) -> None:
    run(one, with_settings(karaoke_input="mix", karaoke_model="bs-roformer-karaoke-frazer"))
    (request,) = one.separator.requests
    assert request.plan.karaoke_input == "mix"
    assert request.plan.karaoke_model.name == "bs-roformer-karaoke-frazer"
    assert (request.plan.karaoke_model.chunk_size, request.plan.karaoke_model.num_overlap) == (
        882000,
        4,
    )


def test_the_default_order_keeps_the_fingerprint_it_had_before_the_new_settings(
    one: FakeWorld,
) -> None:
    declared = (
        SeparationStage().declared_settings(one.context(AUDIO), Config()).model_dump(mode="json")
    )
    assert set(declared) == {"models", "keep_backing"}
    mixed = SeparationStage().declared_settings(
        one.context(AUDIO), with_settings(karaoke_input="mix")
    )
    assert mixed.model_dump(mode="json")["karaoke_input"] == "mix"


@pytest.mark.parametrize(
    "settings",
    [
        {"model": ["bs-roformer-ep317"]},
        {"model": ["bs-roformer-ep317", "bs-roformer-leap", "mel-band-deux"]},
        {"model": ["bs-roformer-ep317", "wav2vec2-de"]},
        {"model": ["bs-roformer-leap", "bs-roformer-leap"]},
        {"karaoke_model": "bs-roformer-ep317"},
        {"karaoke_input": "song"},
    ],
)
def test_wrong_separation_settings_are_errors(settings: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="separation|model|karaoke"):
        SeparationSettings.model_validate(settings)


def test_the_candidates_say_what_their_first_output_is() -> None:
    targets = {
        name: find_model(name).inference.get("target", "vocals")
        for name in ("bs-roformer-leap-inst", "mel-band-deux", "mel-band-flowersv10")
    }
    assert targets == {
        "bs-roformer-leap-inst": "instrumental",
        "mel-band-deux": "vocals",
        "mel-band-flowersv10": "instrumental",
    }


def test_a_non_commercial_model_is_warned_about_in_the_log_and_the_file(one: FakeWorld) -> None:
    assert run(one, with_settings(model="mel-band-deux")).state == "ok"
    (warning,) = separation_of(one).warnings
    assert "mel-band-deux" in warning
    assert "non-commercial" in warning
    log = "\n".join(one.store.log_lines(WORK / LOG_FILE))
    assert f"separation: warning: {warning}" in log


def test_the_default_models_give_no_licence_warning(one: FakeWorld) -> None:
    assert run(one).state == "ok"
    assert separation_of(one).warnings == []
