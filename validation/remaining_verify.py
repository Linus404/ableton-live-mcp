"""Independent sample-domain oracle for the retained physical goals 5-8 take."""
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import correlate
from ableton_paths import state_dir


fixture = json.loads((state_dir() / "audio_remaining_current.json").read_text())
folder = Path(fixture["folder"])
manifest = json.loads(Path(fixture["manifest_path"]).read_text())
entries = manifest["tracks"]
assert len(entries) == 3 and manifest["complete"] and manifest["cleanup_complete"]
raw = [sf.read(e["path"], always_2d=True, dtype="float64")[0] for e in entries]
inputs = [sf.read(p, always_2d=True, dtype="float64")[0] for p in fixture["source_paths"]]
inputs.append(inputs[0] + inputs[1])
sr = fixture["sample_rate"]
evidence = {"manifest_path": fixture["manifest_path"], "files": [], "markers": []}
for path in fixture["source_paths"] + [e["path"] for e in entries]:
    info = sf.info(path)
    evidence["files"].append({"path": path, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                              "frames": info.frames, "subtype": info.subtype, "sample_rate": info.samplerate})
assert len(set(len(x) for x in raw)) == 1
for index, (original, recording) in enumerate(zip(inputs, raw)):
    for second in [.5, 11.5]:
        expected = int(second * sr)
        template = original[expected:expected + 2048]
        left, right = max(0, expected - 5000), expected + 5000 + 2048
        correlations = sum(correlate(recording[left:right, channel], template[:, channel], mode="valid", method="fft") for channel in range(2))
        peak = int(np.argmax(correlations))
        frame = left + peak
        aligned = recording[frame:frame + 2048]
        gain = float(np.sum(template * aligned) / np.sum(template * template))
        residual = float(np.max(np.abs(aligned - gain * template)))
        evidence["markers"].append({"source_index": index, "source_frame": expected, "recorded_frame": frame,
                                    "gain": gain, "max_residual": residual,
                                    "adjacent_absolute_ratio": float(correlations[peak] / max(abs(correlations[peak - 1]), abs(correlations[peak + 1])))})
        assert frame == expected, "Measured nonzero acquisition offset; investigate before declaring alignment"
        assert residual < 2e-7 and .999 < gain < 1.001
summed = raw[0] + raw[1]
gain = float(np.sum(summed * raw[2]) / np.sum(summed * summed))
residual = float(np.max(np.abs(raw[2] - summed)))
evidence["programme_sum"] = {"fitted_master_gain": gain, "max_unscaled_sum_residual": residual,
                              "allowed_pcm24_bound": 3 / 2**23, "frames": len(summed)}
assert abs(gain - 1) < 1e-5 and residual <= 3 / 2**23
evidence["scope"] = "Take-specific direct empty-device routes; PDC off as observed, no global certificate. Exact two-marker integer alignment plus PCM24-bounded actual sum, no shifting/gain/resampling."
evidence["oracles"] = {}
for name, start, end in [("harmonic",1,3),("beating",3,5),("alternating",5,7),("frequency_selective_stereo",7,9),("impact",9,11)]:
    parts = [x[int(start*sr):int(end*sr)] for x in raw]
    rms = [float(np.sqrt(np.mean(x*x))) for x in parts]
    def correlation(x):
        return float(np.sum(x[:,0]*x[:,1])/np.sqrt(np.sum(x[:,0]**2)*np.sum(x[:,1]**2)))
    power = float(np.mean(parts[0]**2))
    mono = float(np.mean(np.mean(parts[0],axis=1)**2))
    evidence["oracles"][name] = {"rms":rms,"target_lr_correlation":correlation(parts[0]),
                                  "target_fold_delta_db":float(10*np.log10(mono/power))}
# Interior of quarter-rate tone: its ideal continuous amplitude is .2 despite .141421 sample peak.
tone = raw[1][int(9.1*sr):int(9.9*sr)]
evidence["oracles"]["intersample"] = {"sample_peak":float(np.max(np.abs(tone))),
    "analytic_peak":.2,"analytic_peak_dbtp":float(20*np.log10(.2)),"source_frequency_hz":sr/4,
    "phase_radians":float(np.pi/4),"interior_seconds":[9.1,9.9]}
assert abs(np.max(np.abs(tone))-.2/np.sqrt(2)) < 2e-7
out = folder / "independent_physical.json"
out.write_text(json.dumps(evidence,indent=2,allow_nan=False),encoding="utf-8")
print(json.dumps({"evidence":str(out),"markers":evidence["markers"],"sum":evidence["programme_sum"],"oracles":evidence["oracles"]},indent=2))
