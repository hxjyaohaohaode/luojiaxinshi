"""Validate the standalone shared-host Compose contract without starting Docker services.

Only `docker compose version` and `docker compose ... config` are executed.
The temporary environment contains synthetic values, never deployment secrets.
An unavailable Docker/Compose CLI is a failure, not a skipped successful check.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import traceback


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root: Path, *, mode: str = "loopback", diagnostics: dict | None = None) -> dict:
    if diagnostics is None:
        diagnostics = {}
    records = []
    # Keep completed observations even when a later contract assertion fails.
    # Only the explicitly synthetic environment below is rendered.
    diagnostics.update(checks=records, verifier_sha256=sha(Path(__file__)), mode=mode)
    templates = {"loopback": "compose.shared-host.yaml", "proxy-network": "compose.proxy-network.yaml"}
    if mode not in templates:
        raise ValueError("Unknown shared-host mode: " + mode)
    template = root / templates[mode]
    diagnostics["template"] = template.name
    if not template.is_file():
        raise RuntimeError(template.name + " is missing")
    diagnostics["template_sha256"] = sha(template)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("COMPOSE_", "CAMPUS_")) and key != "APP_ORIGIN"}
    version = subprocess.run(["docker", "compose", "version", "--short"], env=env,
                             text=True, capture_output=True, timeout=30)
    diagnostics["docker_compose_version"] = version.stdout.strip()
    diagnostics["version_command"] = {"exit_code": version.returncode,
                                      "stdout": version.stdout, "stderr": version.stderr}
    if version.returncode:
        raise RuntimeError("Docker Compose CLI is unavailable: " + version.stderr.strip())
    with tempfile.TemporaryDirectory(prefix="campus-compose-config-") as temporary:
        directory = Path(temporary)
        application = directory / "application.env"
        application.write_text("# Synthetic configuration; no credentials or provider calls.\n")
        fixture = {
            "CAMPUS_PROJECT_NAME": "campus-config-a",
            "CAMPUS_IMAGE": "campus-config-fixture:synthetic",
            "CAMPUS_ENV_FILE": str(application),
            "APP_ORIGIN": "https://campus-fixture.example.invalid",
            "CAMPUS_TRUSTED_PROXY_IPS": "198.51.100.10",
            "CAMPUS_LOOPBACK_PORT": "49123",
            "CAMPUS_MEMORY_LIMIT": "768m",
            "CAMPUS_CPU_LIMIT": "0.5",
            "CAMPUS_PIDS_LIMIT": "96",
            "CAMPUS_TMPFS_SIZE": "128m",
            "CAMPUS_LOG_MAX_SIZE": "10m",
            "CAMPUS_LOG_MAX_FILES": "3",
        }
        if mode == "proxy-network":
            del fixture["CAMPUS_LOOPBACK_PORT"]
            fixture["CAMPUS_PROXY_NETWORK"] = "campus-config-proxy"

        def config(values: dict, label: str, expect_success: bool = True) -> dict | None:
            path = directory / (label + ".env")
            path.write_text("".join(key + "=" + value + "\n" for key, value in values.items()))
            result = subprocess.run(
                ["docker", "compose", "--env-file", str(path), "--project-directory", str(root),
                 "-f", str(template), "config", "--format", "json"],
                env=env, text=True, capture_output=True, timeout=30,
            )
            record = {"case": label, "exit_code": result.returncode,
                      "expected_success": expect_success,
                      "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
                      "stdout": result.stdout,
                      "stderr": result.stderr}
            records.append(record)
            if not expect_success:
                if result.returncode == 0:
                    raise AssertionError(label + " unexpectedly accepted a missing required variable")
                assert label.removeprefix("missing-") in result.stderr
                return None
            if result.returncode:
                raise AssertionError(label + " rejected the synthetic configuration: " + result.stderr.strip())
            record["configuration"] = json.loads(result.stdout)
            return record["configuration"]

        first = config(fixture, "project-a")
        second_values = {**fixture, "CAMPUS_PROJECT_NAME": "campus-config-b"}
        if mode == "loopback":
            second_values["CAMPUS_LOOPBACK_PORT"] = "49124"
        second = config(second_values, "project-b")
        for data, project, port in [(first, "campus-config-a", "49123"), (second, "campus-config-b", "49124")]:
            assert data["name"] == project
            assert set(data["services"]) == {"app"}, "A shared-host configuration must not create its own proxy"
            app = data["services"]["app"]
            assert app["image"] == fixture["CAMPUS_IMAGE"] and app["pull_policy"] == "never"
            assert "build" not in app and "container_name" not in app
            assert app["user"] == "10001:10001" and app["read_only"] is True
            assert app["cap_drop"] == ["ALL"] and app["security_opt"] == ["no-new-privileges:true"]
            assert not app.get("privileged", False) and app.get("network_mode") != "host"
            if mode == "loopback":
                assert len(app["ports"]) == 1
                binding = app["ports"][0]
                assert binding["host_ip"] == "127.0.0.1" and str(binding["published"]) == port
                assert binding["target"] == 8765 and binding["protocol"] == "tcp"
            else:
                assert not app.get("ports"), "The proxy-network mode must not publish any host port"
            # compose-go UnitBytes.MarshalJSON emits a decimal string. Accept
            # that canonical form or the identical integer, never another
            # budget, a float representation, a boolean, or human unit text.
            assert str(app["mem_limit"]) == str(768 * 1024 * 1024), (
                f"mem_limit must represent exactly 805306368 bytes; observed "
                f"{app['mem_limit']!r} ({type(app['mem_limit']).__name__})")
            assert float(app["cpus"]) == 0.5, f"cpus must equal 0.5; observed {app['cpus']!r}"
            assert app["pids_limit"] == 96 and app["tmpfs"] == ["/tmp:size=128m,mode=1777"]
            assert app["logging"] == {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}
            assert app["environment"]["APP_ORIGIN"] == fixture["APP_ORIGIN"]
            assert app["environment"]["FORWARDED_ALLOW_IPS"] == fixture["CAMPUS_TRUSTED_PROXY_IPS"]
            assert app["environment"]["APP_ENV"] == "production"
            assert app["environment"]["APP_HOST"] == "0.0.0.0" and app["environment"]["APP_PORT"] == "8765"
            assert app["environment"]["DATA_DIR"] == "/data"
            assert app["healthcheck"]["test"][0] == "CMD" and "/api/health" in app["healthcheck"]["test"][-1]
            assert len(app["volumes"]) == 1
            mount = app["volumes"][0]
            assert mount["type"] == "volume" and mount["source"] == "campus-data" and mount["target"] == "/data"
            assert set(data["volumes"]) == {"campus-data"}
            assert data["volumes"]["campus-data"]["name"] == project + "_campus-data"
            assert not data["volumes"]["campus-data"].get("external", False)
            if mode == "loopback":
                assert set(app["networks"]) == {"campus-private"} and set(data["networks"]) == {"campus-private"}
                network = data["networks"]["campus-private"]
                assert network["name"] == project + "_campus-private" and network["driver"] == "bridge"
                assert not network.get("enable_ipv6", False) and not network.get("external", False)
                assert network["driver_opts"]["com.docker.network.bridge.gateway_mode_ipv4"] == "nat"
            else:
                assert set(app["networks"]) == {"campus-proxy"} and set(data["networks"]) == {"campus-proxy"}
                assert app["networks"]["campus-proxy"]["aliases"] == [project + "-app"], "Use only the project-specific proxy alias"
                network = data["networks"]["campus-proxy"]
                expected_network = {"name": fixture["CAMPUS_PROXY_NETWORK"], "external": True}
                # Compose 5.1.3 may emit an empty IPAM object for an external
                # network. Accept only that normalization, never IPAM settings
                # or any additional network-management fields.
                assert network in (expected_network, {**expected_network, "ipam": {}}), "Use the explicit pre-existing proxy network without managing its lifecycle"
        assert first["volumes"]["campus-data"]["name"] != second["volumes"]["campus-data"]["name"]
        if mode == "loopback":
            assert first["networks"]["campus-private"]["name"] != second["networks"]["campus-private"]["name"]
        else:
            assert first["networks"]["campus-proxy"]["name"] == second["networks"]["campus-proxy"]["name"]
            assert first["services"]["app"]["networks"]["campus-proxy"]["aliases"] != second["services"]["app"]["networks"]["campus-proxy"]["aliases"]
        for required in fixture:
            config({key: value for key, value in fixture.items() if key != required}, "missing-" + required, False)
    return {
        "result": "passed", "mode": mode, "template": template.name,
        "synthetic_config_only": True, "services_started": False,
        "docker_compose_version": version.stdout.strip(),
        "template_sha256": sha(template), "verifier_sha256": sha(Path(__file__)),
        "checks": records, "configured_projects": 2, "missing_required_variables_rejected": len(fixture),
        "scope": "Two synthetic Compose config renderings and required-variable rejection only; no Docker daemon, actual network existence or membership, connectivity, image, host resource, firewall, TLS, or deployment acceptance is claimed.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mode", choices=("loopback", "proxy-network"), default="loopback")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    diagnostics = {}
    try:
        record = verify(args.root.resolve(), mode=args.mode, diagnostics=diagnostics)
        code = 0
    except (OSError, RuntimeError, AssertionError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        record = {**diagnostics, "result": "failed", "synthetic_config_only": True, "services_started": False,
                  "error": type(error).__name__ + ": " + str(error), "traceback": traceback.format_exc()}
        code = 1
    record["verified_at"] = datetime.now(timezone.utc).isoformat()
    text = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(text)
    print(text, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
