"""Retain a sequential final strict runtime health check for the experiment."""
import json
from pathlib import Path
import subprocess
import sys
from ableton_paths import state_dir

fixture=json.loads((state_dir()/"audio_remaining_current.json").read_text())
command=[str(Path(sys.executable).with_name("ableton-live-mcp-validate.exe")),"--timeout","3","--strict-timeout"]
p=subprocess.run(command,text=True,capture_output=True,timeout=30)
result=json.loads(p.stdout)
Path(fixture["folder"],"final_health.json").write_text(json.dumps({"command":command,"exit_code":p.returncode,"result":result},indent=2),encoding="utf-8")
assert p.returncode==0 and result["remote_script"]["runtime_current"] and result["remote_script"]["live_mutations_safe"]
print("Final strict health current/safe:",result["ping"]["remote_script"]["process_id"])
