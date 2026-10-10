"""Independent public-result checks; reads retained evidence and never calls Live."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf
from ableton_paths import state_dir

fixture=json.loads((state_dir()/"audio_remaining_current.json").read_text())
folder=Path(fixture["folder"])
manifest=json.loads(Path(fixture["manifest_path"]).read_text())
read=lambda n,k:json.loads((folder/(str(n)+"_live_audio_"+k+".json")).read_text())
compat,scenario=read(4,"compatibility"),read(5,"compatibility")
stereo,single=read(6,"stereo"),read(7,"stereo")
integrity,pulses=read(8,"integrity"),read(9,"integrity")
development,no_balance=read(10,"development"),read(11,"development")
data=[sf.read(x["path"],always_2d=True,dtype="float64")[0] for x in manifest["tracks"]]
sr=44100
summary={"compatibility":{},"stereo":{},"integrity":{},"development":{}}
for name,start,end in [("harmonic",1,3),("beating",3,5),("alternating",5,7)]:
    selected=[i for i,w in enumerate(compat["measured_facts"]["windows"]) if start<=w["start_seconds"] and w["end_seconds"]<=end]
    windows=[compat["measured_facts"]["windows"][i] for i in selected]
    joint=sum(w["pairs"][0]["timing"]["joint_active_seconds"] for w in windows)
    exposed=sum(w["target_exposed_from_all_seconds"] for w in windows)
    rough=[compat["perceptual_estimates"]["windows"][i]["pairs"][0]["roughness"]["original"] for i in selected]
    relationships=windows[0]["pairs"][0]["partial_relationships"]["pairs"]
    summary["compatibility"][name]={"joint_seconds":joint,"exposed_seconds":exposed,
        "roughness":float(np.mean([x for x in rough if x is not None])),"first_relationship":relationships[0]}
assert summary["compatibility"]["harmonic"]["joint_seconds"]==2
assert summary["compatibility"]["alternating"]["joint_seconds"]==0
assert summary["compatibility"]["alternating"]["exposed_seconds"]==1
assert summary["compatibility"]["harmonic"]["first_relationship"]["nearest_integer_ratio"]==[3,2]
for name,f in [("harmonic",660),("beating",450)]:
    distance=.24*abs(f-440)/(.0207*440+18.96)
    oracle=(math.exp(-3.5*distance)-math.exp(-5.75*distance))/2
    assert abs(summary["compatibility"][name]["roughness"]-oracle)<1e-5
    summary["compatibility"][name]["independent_kernel_value"]=oracle
assert summary["compatibility"]["beating"]["roughness"]>summary["compatibility"]["harmonic"]["roughness"]
for original,changed in zip(compat["perceptual_estimates"]["windows"],scenario["perceptual_estimates"]["windows"]):
    assert original["pairs"][0]["roughness"]["original"]==changed["pairs"][0]["roughness"]["original"]
section=next(x for x in single["source"]["sections"] if x["name"]=="frequency_selective_stereo")
metrics=section["broadband"]
assert abs(metrics["lr_normalized_real_cross_power"]+.6)<1e-5
assert abs(metrics["mono_fold_power_change_db"]+6.989700043)<1e-5
bands=section["spectrum"]["bands"]
summary["stereo"]["side_heavy_target"]={"broadband":metrics,"bands":bands}
assert single["perceptual_estimates"]["status"]=="unavailable"
modeled=[w for w in stereo["perceptual_estimates"]["windows"] if 7<=w["start_seconds"]<9]
summary["stereo"]["folded_prominence"]=[{k:w[k] for k in ["start_seconds","mono_minus_stereo_threshold_excess_db"]} | {"stereo_components":w["stereo"]["active_component_count"],"mono_components":w["mono"]["active_component_count"]} for w in modeled]
assert all(w["mono_minus_stereo_threshold_excess_db"]<0 for w in modeled)
for report,source in [(integrity,data[1]),(pulses,data[0])]:
    whole=report["measured_facts"]["whole_file"]
    assert abs(whole["levels"]["rms_dbfs"]-20*np.log10(np.sqrt(np.mean(source*source))))<.001
    assert abs(whole["dc"]["max_abs_mean_linear"]-np.max(np.abs(np.mean(source,axis=0))))<1e-12
    assert whole["clipping_observations"]["per_channel_sample_counts"]==[0,0]
peak_section=integrity["measured_facts"]["sections"][0]["measurement"]
sample_db=peak_section["levels"]["sample_peak_dbfs"]
tp=peak_section["true_peak_estimate"]["dbtp"]
assert abs(sample_db-20*np.log10(.2/math.sqrt(2)))<.001
assert abs(tp-20*np.log10(.2))<.2 # disclosed zero-extension/FIR boundary deviation, not certified tolerance
assert tp-sample_db>2.8
jumps=pulses["measured_facts"]["whole_file"]["discontinuity_candidates"]
assert jumps["total_count"]==2
assert abs(jumps["values"][0]["time_seconds"]-10.25)<1/sr
center=round(10.25*sr)
indices=np.arange(center-256,center+257)
times=center+np.arange(-256,257)/64
sinc=np.sinc(times[:,None]-indices[None,:])
reconstruction=sinc @ data[0][indices]
independent_pulse_db=float(20*np.log10(np.max(np.abs(reconstruction))))
reported_pulse_db=pulses["measured_facts"]["whole_file"]["true_peak_estimate"]["dbtp"]
assert abs(independent_pulse_db-reported_pulse_db)<.03
summary["integrity"]={"quarter_rate_sample_peak_dbfs":sample_db,"quarter_rate_estimate_dbtp":tp,
    "ideal_continuous_sine_dbtp":20*np.log10(.2),"whole_true_peak_estimate":integrity["measured_facts"]["whole_file"]["true_peak_estimate"],
    "jump_candidates":jumps,"delivery":integrity["delivery"],
    "pulse_independent_64x_local_513_sample_sinc_peak_db":independent_pulse_db,
    "pulse_reported_4x_fir_peak_dbtp":reported_pulse_db,
    "target_whole_dc":pulses["measured_facts"]["whole_file"]["dc"],
    "intentional_silence_intervals":integrity["measured_facts"]["whole_file"]["silence_candidates"]}
for section in development["measured_facts"]["sections"]:
    samples=data[2][round(section["start_seconds"]*sr):round(section["end_seconds"]*sr)]
    rms=20*np.log10(np.sqrt(np.mean(samples*samples)))
    crest=20*np.log10(np.max(np.abs(samples))/np.sqrt(np.mean(samples*samples)))
    assert abs(section["metrics"]["rms_dbfs"]-rms)<.001
    assert abs(section["metrics"]["crest_factor_db"]-crest)<.001
    assert len(section["balance"])==2
    summary["development"][section["name"]]=section["metrics"]
assert development["expectation_departures"][0]["status"]=="within_declared_expectation"
assert no_balance["expectation_departures"]==[]
assert summary["development"]["harmonic"]["effective_occupied_band_count"]==2
assert summary["development"]["beating"]["effective_occupied_band_count"]==1
summary["coverage"]={"compatibility":compat["coverage"],"stereo":stereo["coverage"],"development":development["coverage"]}
summary["hashes"]=[{"path":e["path"],"sha256":hashlib.sha256(Path(e["path"]).read_bytes()).hexdigest()} for e in manifest["tracks"]]
(folder/"public_independent_assertions.json").write_text(json.dumps(summary,indent=2,allow_nan=False),encoding="utf-8")
print(json.dumps({"compatibility":summary["compatibility"],"stereo_prominence":summary["stereo"]["folded_prominence"],
    "integrity":{"sample":sample_db,"estimate":tp,"jumps":jumps["values"]},"development":summary["development"]},indent=2))
print("Independent physical/public assertions passed:",folder/"public_independent_assertions.json")
