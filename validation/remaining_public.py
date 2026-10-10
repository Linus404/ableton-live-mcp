"""Fresh public stdio acceptance on unchanged, retained actual Live recordings."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys

from ableton_paths import state_dir

fixture = json.loads((state_dir() / "audio_remaining_current.json").read_text())
folder = Path(fixture["folder"])
manifest = json.loads(Path(fixture["manifest_path"]).read_text())
paths = [x["path"] for x in manifest["tracks"]]
alignment = {"verified": True, "source": str(folder / "independent_physical.json") + "; two markers every source/programme at exact frame, neighboring lags rejected", "uncertainty_samples": 0}
provenance = {"disjoint_contributions": True, "in_mix_levels": True,
    "signal_path": "Owned independent empty-device audio tracks, native Post Mixer receivers at actual unity gains, zero sends, unity unprocessed Main Resampling. Whole-frame sum verified within PCM24 bound; take-specific evidence, PDC observed off, no global certificate."}
listener = {"kind": "assumed", "db_spl_at_0_dbfs_rms": 100,
            "source": "Explicit monitor assumption, not measured/calibrated SPL"}
sections = [{"name": name, "start_seconds": start, "end_seconds": end} for name,start,end in
    [("harmonic",1,3),("beating",3,5),("alternating",5,7),("frequency_selective_stereo",7,9),("impact",9,11)]]
sources = [{"name": name, "path": path, "signal_path": signal} for name,path,signal in zip(
    ["target","competitor","programme"],paths,["Actual owned target native Post Mixer at unity", "Actual owned competitor native Post Mixer at unity", "Actual unprocessed unity Main native Resampling"]) ]
calls = []
compat = {"target":sources[0],"competitors":[sources[1]],"alignment":alignment,"provenance":provenance,
          "listening_condition":listener,"window_seconds":.5,"max_windows":120,"sections":sections,
          "brief":{"description":"Controlled harmonic/beating, simultaneous/alternating and side-heavy target experiments; numerical compatibility evidence, no listener approval."}}
calls.append(("compatibility",compat))
calls.append(("compatibility",dict(compat, target=dict(sources[0],gain_db=-6))))
stereo = {"source":sources[2],"target":{"name":"target","path":paths[0]},
          "competitors":[{"name":"competitor","path":paths[1]}],"alignment":alignment,
          "provenance":provenance,"listening_condition":listener,"window_seconds":.5,"sections":sections}
calls.append(("stereo",stereo))
calls.append(("stereo",{"source":sources[0],"sections":sections,"window_seconds":.5}))
integrity = {"source":sources[1],"sections":[{"name":"quarter_rate_interior","start_seconds":9.1,"end_seconds":9.9}],
             "silence_threshold_dbfs":-90,"min_silence_seconds":.1,
             "delivery":{"description":"Controlled retained recording-file checks; deliberately strict peak bound, not released master certification",
                         "sample_rate":44100,"channels":2,"subtype":"PCM_24","max_true_peak_dbtp":-20,"max_abs_dc":.001}}
calls.append(("integrity",integrity))
calls.append(("integrity",{"source":sources[0],"sections":[{"name":"dc_and_pulse","start_seconds":10,"end_seconds":10.5}],
                           "discontinuity_threshold":.25,"silence_threshold_dbfs":-90,"min_silence_seconds":.1}))
balance = {"programme":{"name":"programme","path":paths[2]},"parts":[{"name":x["name"],"path":x["path"]} for x in sources[:2]],
           "alignment":alignment,"provenance":provenance,"listening_condition":listener,"window_seconds":.5,"window_step_seconds":.5}
development = {"source":sources[2],"sections":sections,
    "brief":{"description":"Intentional harmonic versus beating sections at equal power, alternating lower-RMS exposure, side-heavy contrast and denser pulse section. Preserve those contrasts."},
    "expected_contrasts":[{"from_section":"harmonic","to_section":"beating","metric":"rms_dbfs","expected_delta":0,"tolerance":.01}],
    "balance":balance}
calls.append(("development",development))
calls.append(("development",{"source":sources[2],"sections":sections}))
# Gate refusals through the same public dispatch, using the real retained paths.
calls.append(("compatibility",dict(compat,alignment=dict(alignment,verified=False))))
calls.append(("stereo",{k:v for k,v in stereo.items() if k!="listening_condition"}))
summary={"track_limit":256,"clip_slot_limit":0,"device_limit":8,"include_return_tracks":True,"include_master_track":True}
requests=[{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"remaining-real-live-validator","version":"1"}}},
          {"jsonrpc":"2.0","id":2,"method":"tools/list"},
          {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"live_set_summary","arguments":summary}}]
for i,(name,args) in enumerate(calls,4):
    requests.append({"jsonrpc":"2.0","id":i,"method":"tools/call","params":{"name":"live_audio_"+name,"arguments":args}})
requests.append({"jsonrpc":"2.0","id":len(requests)+1,"method":"tools/call","params":{"name":"live_set_summary","arguments":summary}})
root=Path(__file__).resolve().parents[1]
save=lambda path,data: Path(path).write_text(json.dumps(data,indent=2,allow_nan=False),encoding="utf-8")
archive=folder/"public_runtime_sources"
archive.mkdir(exist_ok=True)
source_files=[root/"src"/name for name in ["server.py","audio_analysis.py","audio_capture.py","audio_tonal.py","audio_dynamics.py","audio_masking.py","audio_balance.py","audio_compatibility.py","audio_stereo.py","audio_integrity.py","audio_development.py"]]
hashes={}
for path in source_files:
    content=path.read_bytes()
    hashes[str(path)]=hashlib.sha256(content).hexdigest()
    (archive/path.name).write_bytes(content)
save(folder/"public_source_hashes.json",hashes)
save(folder/"public_requests.json",requests)
p=subprocess.run([sys.executable,str(root/"src/server.py")],cwd=root,input="".join(json.dumps(x)+"\n" for x in requests),text=True,encoding="utf-8",capture_output=True,timeout=240)
assert p.returncode==0,p.stderr
responses=[json.loads(x) for x in p.stdout.splitlines() if x.strip()]
save(folder/"public_responses.json",responses)
assert len(responses)==len(requests)
assert all(hashlib.sha256(path.read_bytes()).hexdigest()==hashes[str(path)] for path in source_files),"Source changed during public calls; rerun when stable"
assert responses[2]["result"]["structuredContent"]==responses[-1]["result"]["structuredContent"],"Live summary changed"
for request,response in zip(requests,responses):
    name=request.get("params",{}).get("name",request["method"])
    if name.startswith("live_audio_"):
        report=response.get("result",{}).get("structuredContent")
        print(request["id"],name,"ERROR" if "error" in response else "PASS",response.get("error",{}),"keys",list(report or {}))
        if report is not None:
            save(folder/(str(request["id"])+"_"+name+".json"),report)
print("Retained:",folder,"; before/after full compact Live summaries equal")
