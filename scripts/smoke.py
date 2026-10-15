"""Verify actual HTTP generation and an independent Python server process."""

import contextlib
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    work = ROOT / ".tools" / ("python-smoke-" + uuid.uuid4().hex)
    work.mkdir(parents=True)
    admin = secrets.token_urlsafe(32)
    runtime = secrets.token_urlsafe(32)
    environment = os.environ.copy()
    environment.update(
        FLOW_DATA=str(work / "data"), FLOW_ADMIN_TOKEN=admin, FLOW_RUNTIME_TOKEN=runtime
    )
    for name in ("FLOW_DATABASE_CONFIG", "FLOW_SERVICE_CONFIG"):
        environment.pop(name, None)
    processes = []
    with (
        contextlib.ExitStack() as stack,
        httpx.Client(timeout=15, trust_env=False) as client,
    ):

        def start(cwd, module, name, listen):
            log = stack.enter_context(
                (work / (name + ".log")).open("w", encoding="utf-8")
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    module,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(listen),
                ],
                cwd=cwd,
                env=environment,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            processes.append(process)
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError(f"{name} failed: {work / (name + '.log')}")
                try:
                    client.get(f"http://127.0.0.1:{listen}/__probe")
                    return
                except httpx.TransportError:
                    time.sleep(0.25)
            raise RuntimeError(f"{name} did not start")

        try:
            first, second = port(), port()
            start(ROOT, "flowstudio.app:app", "platform", first)
            url = f"http://127.0.0.1:{first}"
            headers = {"Authorization": "Bearer " + admin}
            workspace = (
                client.get(url + "/api/workspace?databaseId=main", headers=headers)
                .raise_for_status()
                .json()
            )
            project = workspace["projects"][0]
            process = next(
                p
                for u in project["units"]
                for p in u["processes"]
                if p["process_id"] == "SYS-001"
            )
            preview = (
                client.post(
                    url + f"/api/processes/{process['id']}/preview",
                    headers=headers,
                    json={"request": {"body": {"name": "Smoke"}}},
                )
                .raise_for_status()
                .json()
            )
            assert (
                preview["status"] == 200
                and preview["body"]["message"] == "Hello, Smoke"
            )
            archive = (
                client.post(
                    url + f"/api/projects/{project['id']}/generate",
                    headers=headers,
                    json={},
                )
                .raise_for_status()
                .content
            )
            zip_path = work / "generated.zip"
            zip_path.write_bytes(archive)
            generated = work / "generated"
            generated.mkdir()
            with zipfile.ZipFile(zip_path) as bundle:
                for item in bundle.infolist():
                    if (
                        not (generated / item.filename)
                        .resolve()
                        .is_relative_to(generated.resolve())
                    ):
                        raise RuntimeError("Unsafe ZIP path")
                assert "flowstudio/app.py" not in bundle.namelist()
                assert "flowstudio/typecheck.py" in bundle.namelist()
                bundle.extractall(generated)
            local = subprocess.check_output(
                [sys.executable, "-c", "import flowstudio;print(flowstudio.__file__)"],
                cwd=generated,
                text=True,
            ).strip()
            assert Path(local).is_relative_to(generated), (
                "Generated runtime imported the platform source"
            )
            start(generated, "app:app", "generated-runtime", second)
            endpoint = f"http://127.0.0.1:{second}/sys-001"
            assert client.post(endpoint, json={"name": "Smoke"}).status_code == 401
            response = client.post(
                endpoint,
                headers={"Authorization": "Bearer " + runtime},
                json={"name": "Smoke"},
            ).raise_for_status()
            assert response.json() == preview["body"]
            assert (
                client.get(f"http://127.0.0.1:{second}/api/workspace").status_code
                == 404
            )
            ROOT.joinpath("artifacts").mkdir(exist_ok=True)
            ROOT.joinpath("artifacts/python-project-server.zip").write_bytes(archive)
            print(
                "PASS: hierarchy -> preview -> project ZIP -> independent Python source -> protected generated API; platform routes absent."
            )
            print("Artifacts:", work)
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    main()
