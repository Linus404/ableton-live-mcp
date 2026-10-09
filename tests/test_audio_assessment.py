import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from audio_assessment import assess_audio
from audio_capture import validate_wav


@pytest.fixture
def capture(tmp_path, monkeypatch):
    tracks = []
    for name, role in (("Master", "program"), ("Lead", "contribution")):
        path = tmp_path / (name + ".wav")
        sf.write(path, np.zeros((48000, 2)), 48000, subtype="FLOAT")
        tracks.append({"name": name, "role": role, "outcome": "complete", "path": str(path), "wav": validate_wav(path)})
    interleaved_path = tmp_path / "interleaved.wav"
    sf.write(interleaved_path, np.zeros((48000, 4)), 48000, subtype="FLOAT")
    manifest = {"mode": "in_mix_native_arrangement", "complete": True, "cleanup_complete": True,
        "alignment": {"verified": True, "source": "physical experiment", "uncertainty_samples": 0},
        "provenance": {"disjoint_contributions": True, "in_mix_levels": True, "signal_path": "Post Mixer / Master Resampling", "verification": "physical checks"},
        "tracks": tracks, "interleaved_wav": validate_wav(interleaved_path), "interleaved_path": str(interleaved_path),
        "take_id": "test", "raw_untrimmed": True}
    monkeypatch.setitem(sys.modules, "in_mix_qualification", SimpleNamespace(verify_qualification=lambda manifest: {"verified": "test-only proof"}))
    path = tmp_path / "manifest.json"
    return manifest, path


def run(capture, **options):
    manifest, path = capture
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return assess_audio({"manifest_path": str(path), "listening_condition": {
        "kind": "assumed", "db_spl_at_0_dbfs_rms": 100, "source": "test assumption"}, **options})


def test_adapter_retains_evidence_and_passes_strict_analysis_contract(capture, monkeypatch):
    import audio_balance
    monkeypatch.setattr(audio_balance, "analyze_balance", lambda args: {"received": args})
    result = run(capture, gains_db={"Lead": -3})
    assert result["received"]["parts"][0]["gain_db"] == -3
    assert result["received"]["programme"]["name"] == "Master"
    assert "verification" not in result["received"]["provenance"]
    assert result["capture_evidence"]["provenance"]["verification"] == "physical checks"
    assert result["capture_evidence"]["tracks"] == capture[0]["tracks"]


def test_qualified_adapter_runs_real_offline_balance(capture):
    result = run(capture)
    assert result["programme"]["name"] == "Master"
    assert result["parts"][0]["original"]["whole_file"]["integrated_lufs"] is None
    assert result["parts"][0]["perceptual_prominence"]["coverage"]["complete"] is True
    assert result["capture_evidence"]["take_id"] == "test"


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(mode="raw_taps"),
    lambda m: m.update(complete=False),
    lambda m: m.update(cleanup_complete=False),
    lambda m: m.update(unsupported_tracks=[{"name": "Frozen", "outcome": "unsupported"}]),
    lambda m: m["alignment"].update(verified=False),
    lambda m: m["alignment"].update(uncertainty_samples=False),
    lambda m: m["alignment"].update(source=""),
    lambda m: m["provenance"].update(in_mix_levels=False),
    lambda m: m["tracks"][1].update(outcome="failed"),
    lambda m: m["tracks"][1].update(role="program"),
    lambda m: m["tracks"][1]["wav"].update(frames=5),
    lambda m: m["tracks"][1].update(name="Master"),
    lambda m: m["interleaved_wav"].update(channels=2),
])
def test_adapter_refuses_incomplete_or_inconsistent_evidence(capture, mutation):
    mutation(capture[0])
    with pytest.raises(ValueError):
        run(capture)


def test_adapter_cannot_bypass_certificate_verification(capture, monkeypatch):
    def refuse(manifest):
        raise ValueError("qualification certificate mismatch")
    monkeypatch.setitem(sys.modules, "in_mix_qualification", SimpleNamespace(verify_qualification=refuse))
    with pytest.raises(ValueError, match="certificate mismatch"):
        run(capture)


def test_adapter_requires_listener_and_known_gain_names(capture):
    with pytest.raises(ValueError, match="listening_condition"):
        assess_audio({"manifest_path": str(capture[1])})
    with pytest.raises(ValueError, match="gains_db"):
        run(capture, gains_db={"Absent": 2})


def test_adapter_refuses_replaced_channel_copy_with_matching_metadata(capture):
    path = capture[0]["tracks"][1]["path"]
    sf.write(path, np.ones((48000, 2)) * 0.1, 48000, subtype="FLOAT")
    with pytest.raises(ValueError, match="interleaved recorder channels"):
        run(capture)


def test_adapter_refuses_replaced_interleaved_recording(capture):
    sf.write(capture[0]["interleaved_path"], np.zeros((47999, 4)), 48000, subtype="FLOAT")
    with pytest.raises(ValueError, match="interleaved recording metadata"):
        run(capture)


def test_adapter_uses_finalized_normalized_recording_and_preserves_raw_evidence(capture):
    manifest, path = capture
    manifest["normalized_interleaved_path"] = manifest["interleaved_path"]
    manifest["interleaved_path"] = str(path.parent / "unfinalized_raw.wav")
    manifest["normalization"] = {"samples_preserved": True, "raw_original_finalized": False}
    result = run(capture)
    assert result["capture_evidence"]["interleaved_path"] == manifest["interleaved_path"]
    assert result["capture_evidence"]["normalized_interleaved_path"] == manifest["normalized_interleaved_path"]
    assert result["capture_evidence"]["normalization"] == manifest["normalization"]


def test_adapter_preserves_native_pcm32_least_significant_bits(capture, monkeypatch):
    import audio_balance
    monkeypatch.setattr(audio_balance, "analyze_balance", lambda args: {"received": args})
    manifest, _ = capture
    # Adjacent PCM32 values collapse to the same float32 value, but not float64.
    samples = np.full((48000, 2), 0.5 + 2 ** -31, dtype="float64")
    for track in manifest["tracks"]:
        sf.write(track["path"], samples, 48000, subtype="PCM_32")
        track["wav"] = validate_wav(track["path"])
    sf.write(manifest["interleaved_path"], np.concatenate([samples, samples], axis=1), 48000, subtype="DOUBLE")
    manifest["interleaved_wav"] = validate_wav(manifest["interleaved_path"])
    assert run(capture)["received"]["programme"]["name"] == "Master"
    changed = samples.copy()
    changed[0, 0] = 0.5
    sf.write(manifest["tracks"][1]["path"], changed, 48000, subtype="PCM_32")
    with pytest.raises(ValueError, match="interleaved recorder channels"):
        run(capture)


def group_partition(capture):
    manifest, _ = capture
    manifest["requested"] = {}
    manifest["tracks"][1].update(ref={"id": 2, "path": "live_set tracks 1"}, kind="group")
    manifest["unsupported_tracks"] = [{"ref": {"id": 3, "path": "live_set tracks 0"},
        "name": "Child", "reason": "nonterminal_or_nonmaster_route", "outcome": "unsupported"}]
    manifest["routing_profile"] = {"tracks": [
        {"ref": {"id": 2}, "name": "Lead", "kind": "group", "output_type": "Main", "output_channel": ""},
        {"ref": {"id": 3}, "name": "Child", "kind": "track", "parent_ref": {"id": 2},
         "is_grouped": True, "output_type": "Lead", "output_channel": ""}]}
    return manifest


def test_default_group_partition_preserves_qualified_routed_child_exclusion(capture):
    manifest = group_partition(capture)
    result = run(capture)
    assert result["capture_evidence"]["unsupported_tracks"] == manifest["unsupported_tracks"]
    assert result["capture_evidence"]["routing_profile"] == manifest["routing_profile"]


@pytest.mark.parametrize("mutation", [
    lambda m: m["requested"].update(track_refs=[{"id": 3}]),
    lambda m: m["requested"].update(track_refs=[{"path": "live_set tracks 0"}]),
    lambda m: m["requested"].update(track_refs=[{"id": "3"}]),
    lambda m: m.pop("requested"),
    lambda m: m["unsupported_tracks"][0].update(reason="frozen"),
    lambda m: m["routing_profile"]["tracks"][1].update(output_type="Ext. Out"),
    lambda m: m["routing_profile"]["tracks"][1].update(output_type="No Output"),
    lambda m: m["routing_profile"]["tracks"][1].update(output_type="Main"),
    lambda m: m["routing_profile"]["tracks"][1].update(output_type="Group"),
    lambda m: m["routing_profile"]["tracks"][1].update(output_channel="Sidechain"),
    lambda m: m["routing_profile"]["tracks"][1].update(is_grouped=False),
    lambda m: m["routing_profile"]["tracks"].append({"ref": {"id": 4}, "name": "Lead", "kind": "group"}),
    lambda m: m["routing_profile"]["tracks"][0].update(output_type="Ext. Out"),
    lambda m: m["unsupported_tracks"][0]["ref"].pop("path"),
])
def test_partition_never_drops_selected_external_unpinned_or_ambiguous_sources(capture, mutation):
    manifest = group_partition(capture)
    mutation(manifest)
    with pytest.raises(ValueError):
        run(capture)


def test_nested_group_partition_requires_entire_actual_output_route_chain(capture):
    manifest = group_partition(capture)
    child = manifest["routing_profile"]["tracks"][1]
    child.update(parent_ref={"id": 4}, output_type="Inner")
    manifest["routing_profile"]["tracks"].append({"ref": {"id": 4}, "name": "Inner", "kind": "group",
        "parent_ref": {"id": 2}, "is_grouped": True, "output_type": "Lead", "output_channel": ""})
    assert run(capture)["capture_evidence"]["unsupported_tracks"] == manifest["unsupported_tracks"]
    manifest["routing_profile"]["tracks"][2]["output_type"] = "No Output"
    with pytest.raises(ValueError):
        run(capture)


@pytest.mark.parametrize("reason", ["nonterminal_or_nonmaster_route", "no_audio_output_or_unknown_capability"])
def test_default_non_audio_control_track_preserves_proven_false_capability(capture, reason):
    manifest = group_partition(capture)
    manifest["unsupported_tracks"][0]["reason"] = reason
    row = manifest["routing_profile"]["tracks"][1]
    row.update(has_audio_output=False, is_grouped=False, parent_ref=None, output_type="No Output")
    result = run(capture)
    assert result["capture_evidence"]["routing_profile"]["tracks"][1]["has_audio_output"] is False
    assert result["capture_evidence"]["unsupported_tracks"] == manifest["unsupported_tracks"]


@pytest.mark.parametrize("capability", [None, True, 0, "false"])
def test_unknown_or_audio_capable_sources_cannot_masquerade_as_non_audio(capture, capability):
    manifest = group_partition(capture)
    manifest["unsupported_tracks"][0]["reason"] = "no_audio_output_or_unknown_capability"
    manifest["routing_profile"]["tracks"][1].update(has_audio_output=capability, output_type="No Output")
    with pytest.raises(ValueError, match="proven non-audio"):
        run(capture)


@pytest.mark.parametrize("requested", [{"id": 3}, {"path": "live_set tracks 0"}])
def test_explicitly_selected_non_audio_source_is_never_silently_excluded(capture, requested):
    manifest = group_partition(capture)
    manifest["requested"]["track_refs"] = [requested]
    manifest["routing_profile"]["tracks"][1].update(has_audio_output=False, output_type="No Output")
    with pytest.raises(ValueError, match="explicitly selected"):
        run(capture)


@pytest.mark.parametrize("selection", [[{"path": "song tracks 00"}], [{"path": "song tracks +0"}],
                                       [{"path": "song tracks -2"}], []])
@pytest.mark.parametrize("non_audio", [False, True])
def test_explicit_regular_selection_aliases_cannot_hide_group_or_non_audio_exclusions(capture, selection, non_audio):
    manifest = group_partition(capture)
    manifest["requested"]["track_refs"] = selection
    if non_audio:
        manifest["routing_profile"]["tracks"][1].update(has_audio_output=False, output_type="No Output")
    with pytest.raises(ValueError, match="explicitly selected regular"):
        run(capture)
