"""Owned, sequential goals 5-8 Live experiment; retained evidence is not a certificate."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

import numpy as np
import soundfile as sf
from ableton_paths import state_dir
from audio_capture import _require_runtime
from bridge import AbletonBridgeClient
from in_mix_capture import capture_in_mix


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def prepare(b):
    prior = b.request("audio_capture_snapshot", {})
    assert not prior["transport"]["playing"]
    token = uuid.uuid4().hex
    folder = state_dir() / "audio_remaining_validation" / token
    folder.mkdir(parents=True)
    sr = 44100
    t = np.arange(12 * sr) / sr
    a, c = np.zeros((len(t), 2)), np.zeros((len(t), 2))
    def tone(data, start, end, frequency, amplitude, phase=0, opposite=False):
        mask = (t >= start) & (t < end)
        v = amplitude * np.sin(2 * np.pi * frequency * t[mask] + phase)
        data[mask, 0] += v
        data[mask, 1] += -v if opposite else v
    for start, end, frequency in [(1, 3, 660), (3, 5, 450)]:
        tone(a, start, end, 440, .04)
        tone(c, start, end, frequency, .04)
    for start in np.arange(5, 7, .5):
        tone(a, start, start + .25, 440, .04)
        tone(c, start + .25, start + .5, 440, .04)
    tone(a, 7, 9, 220, .02)
    tone(a, 7, 9, 3000, .04, opposite=True)
    tone(c, 7, 9, 3000, .01)
    tone(c, 9, 10, sr / 4, .2, phase=np.pi / 4)
    for start in np.arange(9, 11, .25):
        mask = (t >= start) & (t < start + .12)
        v = .12 * np.sin(2 * np.pi * 180 * t[mask]) * np.exp(-(t[mask] - start) * 25)
        a[mask] += v[:, None]
    a[(t >= 10) & (t < 10.5)] += .01
    a[int(10.25 * sr)] += .4
    markers = []
    for n, data in enumerate([a, c]):
        marker = np.random.default_rng(912 + n).uniform(-.02, .02, (2048, 2))
        for second in [.5, 11.5]:
            frame = int(second * sr)
            data[frame:frame + len(marker)] += marker
        markers.append(marker)
    paths = []
    for name, data in [("target", a), ("competitor", c)]:
        path = folder / (name + ".wav")
        sf.write(path, data, sr, subtype="FLOAT")
        paths.append(str(path))
    # Persist the token before any Live mutation so cleanup can recover partial setup.
    fixture = {"token": token, "folder": str(folder), "prior": prior,
               "source_paths": paths, "sample_rate": sr, "source_refs": []}
    save(folder / "fixture.json", fixture)
    save(state_dir() / "audio_remaining_current.json", fixture)
    for name, path in zip(["target", "competitor"], paths):
        code = "\n".join([
            "this._audio_capture_guard()", "assert not song.is_playing",
            "registry=getattr(this,'_audio_remaining_owned',None)",
            "if registry is None:registry=this._audio_remaining_owned={}",
            "owned=registry.setdefault(" + repr(token) + ",[])",
            "song.create_audio_track(-1)", "t=song.tracks[-1]", "owned.append(t)",
            "t.name=" + repr("MCP Remaining " + token + " " + name),
            "t.arm=False", "t.mute=False", "t.solo=False",
            "t.mixer_device.volume.value=.85", "t.mixer_device.panning.value=0",
            "for send in t.mixer_device.sends:send.value=send.min",
            "clip=t.create_audio_clip(" + repr(path) + ",0)",
            "clip.warping=False", "clip.looping=False",
            "result=this._audio_capture_ref(t)"])
        fixture["source_refs"].append(b.request("exec", {"code": code}))
        save(folder / "fixture.json", fixture)
        save(state_dir() / "audio_remaining_current.json", fixture)
    print(json.dumps({"prepared": True, "folder": str(folder), "refs": fixture["source_refs"]}))


def capture(b, fixture):
    args = {"start_beat": 0, "length_beats": 13 * fixture["prior"]["transport"]["tempo"] / 60,
            "track_refs": fixture["source_refs"], "include_returns": False,
            "include_master": True, "max_duration_seconds": 90,
            "output_directory": str(Path(fixture["folder"]) / "capture")}
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "live_audio_capture_in_mix", "arguments": args}}
    result = capture_in_mix(b, args)
    response = {"direct_python_wrapper": True, "result": {"structuredContent": result}}
    save(Path(fixture["folder"]) / "capture.json", {"request": request, "response": response})
    fixture["manifest_path"] = result.get("manifest_path")
    save(state_dir() / "audio_remaining_current.json", fixture)
    save(Path(fixture["folder"]) / "fixture.json", fixture)
    print(json.dumps({k: result.get(k) for k in ["complete", "cleanup_complete", "manifest_path", "error"]}))


def cleanup(b, fixture):
    prior = fixture["prior"]
    code = "\n".join([
        "assert not song.is_playing", "owned=getattr(this,'_audio_remaining_owned',{}).get(" + repr(fixture["token"]) + ",[])",
        "removed=[]", "for t in list(owned)[::-1]:",
        "    index=next((i for i,x in enumerate(song.tracks) if this._same_live_object(t,x)),None)",
        "    if index is not None:removed.append(t.name);song.delete_track(index)",
        "getattr(this,'_audio_remaining_owned',{}).pop(" + repr(fixture["token"]) + ",None)",
        "song.view.selected_track=this._resolve(" + repr(prior["selected_track"]) + ")",
        "song.current_song_time=" + repr(prior["transport"]["time"]),
        "result={'removed':removed}"])
    save(Path(fixture["folder"]) / "cleanup.json", b.request("exec", {"code": code}))
    after = b.request("audio_capture_snapshot", {})
    save(Path(fixture["folder"]) / "restored.json", after)
    assert after == prior, "Original snapshot differs; inspect restored.json"
    print("Owned sources removed; original snapshot exactly restored")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "capture", "cleanup"])
    args = parser.parse_args()
    b = AbletonBridgeClient()
    try:
        _require_runtime(b)
        if args.action == "prepare":
            prepare(b)
        else:
            fixture = json.loads((state_dir() / "audio_remaining_current.json").read_text())
            (capture if args.action == "capture" else cleanup)(b, fixture)
    finally:
        b.close()
