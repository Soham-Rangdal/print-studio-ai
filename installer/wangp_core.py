"""Fallback install of WanGP's Python environment, used when WanGP's own 1-click installer stops.

Its installer fails as a whole if one optional download fails (for example the face-tools wheels hosted on
GitHub, which time out on some networks). This does the same steps, but skips the GitHub-hosted wheels (face
and body features that Print Studio doesn't use) and tries each speed-up extra on its own.
Run from the Wan2GP folder with Python 3.11:   py -3.11 <path>\\wangp_core.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.getcwd())
import setup  # noqa: E402  WanGP's own installer module

config = json.load(open("setup_config.json", encoding="utf-8"))
gpu, vendor = setup.get_gpu_info()
key = setup.get_profile_key(gpu, vendor)
if key is None or vendor != "NVIDIA":
    sys.exit(f"Print Studio needs an NVIDIA RTX graphics card (found: {gpu}).")
p = config["gpu_profiles"][key]
print(f"[*] Graphics card: {gpu} -> WanGP profile {key}", flush=True)

env = os.path.join(os.getcwd(), "env_venv")
py = os.path.join(env, "Scripts", "python.exe")
pip = f'"{py}" -m pip install'


def run(cmd, required=False):
    print(f"\n>>> {cmd}", flush=True)
    ok = subprocess.run(cmd, shell=True).returncode == 0
    if required and not ok:
        sys.exit(f"Failed: {cmd}")
    return ok


if not os.path.isfile(py):
    run(f'"{sys.executable}" -m venv "{env}"', required=True)
if subprocess.run(f'"{py}" -c "import torch"', shell=True).returncode != 0:
    run(f"{pip} {setup.resolve_torch_cmd(config, p['torch'])}", required=True)

reqs = open("requirements.txt", encoding="utf-8").read().splitlines()
kept = [r for r in reqs if not ("@ https://github.com/" in r and "linux" not in r)]
with open("requirements-core.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(kept) + "\n")
run(f"{pip} -r requirements-core.txt", required=True)

comp = config["components"]
if p.get("triton"):
    run(f"{pip} {setup.resolve_cmd(comp['triton'][p['triton']]['cmd'])}")
if p.get("sage"):
    cmd = setup.resolve_cmd(comp["sage"][p["sage"]]["cmd"]).replace("{py}", "cp311")
    if cmd.startswith("http") or cmd.startswith("sageattention"):
        run(f"{pip} {cmd}")
for k in p.get("kernels", []):
    try:                                            # optional speed-ups: never stop the install
        k = setup.kernel_variant(k, p["torch"], p["python"], [])
        if k and k in comp["kernels"]:
            run(f"{pip} {setup.resolve_cmd(comp['kernels'][k]['cmd'])}")
    except Exception as e:  # noqa: BLE001
        print(f"[!] skipped kernel {k}: {e}", flush=True)

m = setup.EnvsManager()
if "env_venv" not in m.list_envs():
    m.add_env("env_venv", "venv", env)
m.set_active("env_venv")
setup.create_wgp_config(key, config)
print("\n[*] WanGP environment ready.", flush=True)
