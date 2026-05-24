"""
Test de integración end-to-end usando un minero mock (sin Ollama).

Verifica que el orquestador, cliente y minero se hablan correctamente
vía HTTP, sin necesitar Ollama.

Para correr:
    pytest tests/test_integration.py -v
"""

import asyncio
import hashlib
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path

# Path setup
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest
import httpx
from fastapi import FastAPI, BackgroundTasks
import uvicorn

from common.identity import NodeIdentity


# ============================================================
# Mock miner: responde a /tasks/execute sin Ollama
# ============================================================

mock_app = FastAPI()
mock_state = {"identity": None, "orchestrator_url": None}


@mock_app.post("/tasks/execute")
async def mock_execute(payload: dict, background: BackgroundTasks):
    """Simulamos ejecución sin Ollama."""
    background.add_task(mock_run, payload)
    return {"status": "accepted", "task_id": payload["task_id"]}


@mock_app.get("/")
async def mock_root():
    return {"name": "Mock Miner"}


async def mock_run(payload: dict):
    """Ejecuta una "inferencia" falsa y envía commit + reveal."""
    task_id = payload["task_id"]
    orch = payload["orchestrator_endpoint"]

    # Simular trabajo
    await asyncio.sleep(0.1)

    # Resultado determinístico falso (basado en el prompt)
    prompt = payload["spec"]["prompt"]
    result = f"MOCK_ANSWER_FOR_{prompt[:20]}"
    nonce = secrets.token_hex(8)
    commit_hash = hashlib.sha256(f"{result}||{nonce}".encode()).hexdigest()

    identity: NodeIdentity = mock_state["identity"]

    # Mandar commit
    commit_payload = f"commit:{task_id}:{commit_hash}"
    commit_sig = identity.sign(commit_payload)

    async with httpx.AsyncClient() as client:
        await client.post(f"{orch}/tasks/{task_id}/commit", json={
            "miner_id": identity.node_id,
            "commit_hash": commit_hash,
            "compute_time_ms": 100,
            "signature": commit_sig,
        })

    await asyncio.sleep(0.05)

    # Mandar reveal
    reveal_payload = f"reveal:{task_id}:{result[:100]}"
    reveal_sig = identity.sign(reveal_payload)

    async with httpx.AsyncClient() as client:
        await client.post(f"{orch}/tasks/{task_id}/reveal", json={
            "miner_id": identity.node_id,
            "result": result,
            "nonce": nonce,
            "metadata": {"tokens": 10},
            "signature": reveal_sig,
        })


def run_orch():
    """Corre el orquestador en un thread."""
    # Hacer que el orquestador use una identidad de test
    import shutil, tempfile
    tmp = tempfile.mkdtemp()
    os.chdir(tmp)

    from orchestrator import server
    sys.argv = ["server.py", "--port", "17000"]
    try:
        server.main()
    except SystemExit:
        pass


def run_mock_miner(port: int):
    """Corre el mock miner en un thread."""
    uvicorn.run(mock_app, host="127.0.0.1", port=port, log_level="critical")


# ============================================================
# Tests
# ============================================================

@pytest.fixture(scope="module")
def services():
    """Arranca orquestador + mock miner."""
    # Crear identidades
    mock_state["identity"] = NodeIdentity.generate()

    # Lanzar orquestador
    t_orch = threading.Thread(target=run_orch, daemon=True)
    t_orch.start()

    # Lanzar mock miner
    t_miner = threading.Thread(target=run_mock_miner, args=(17100,), daemon=True)
    t_miner.start()

    # Esperar que arranquen
    time.sleep(2.5)

    # Verificar que el orquestador está vivo
    for _ in range(10):
        try:
            r = httpx.get("http://127.0.0.1:17000/health", timeout=1.0)
            if r.status_code == 200:
                break
        except httpx.RequestError:
            time.sleep(0.5)
    else:
        pytest.skip("Orquestador no arrancó")

    # Registrar el mock miner en el orquestador
    identity = mock_state["identity"]
    payload = json.dumps({
        "node_id": identity.node_id,
        "endpoint": "http://127.0.0.1:17100",
        "gpu_model": "Mock GPU",
        "stake_nxs": 1000.0,
    }, sort_keys=True)

    r = httpx.post("http://127.0.0.1:17000/miners/register", json={
        "node_id": identity.node_id,
        "endpoint": "http://127.0.0.1:17100",
        "gpu_model": "Mock GPU",
        "vram_gb": 12,
        "cpu_cores": 8,
        "preloaded_models": ["qwen2.5:7b", "llama3.1:8b"],
        "stake_nxs": 1000.0,
        "signature": identity.sign(payload),
    })
    assert r.status_code == 200, f"Register falló: {r.text}"

    yield {"orchestrator": "http://127.0.0.1:17000"}


def test_orchestrator_health(services):
    r = httpx.get(f"{services['orchestrator']}/health")
    assert r.status_code == 200


def test_list_miners(services):
    r = httpx.get(f"{services['orchestrator']}/miners")
    data = r.json()
    assert data["count"] >= 1


def test_register_with_bad_signature_fails(services):
    """Verifica que el orquestador rechaza firmas inválidas."""
    r = httpx.post(f"{services['orchestrator']}/miners/register", json={
        "node_id": "ff" * 32,
        "endpoint": "http://fake",
        "gpu_model": "Fake",
        "vram_gb": 1,
        "cpu_cores": 1,
        "preloaded_models": [],
        "stake_nxs": 1.0,
        "signature": "00" * 64,  # firma inválida
    })
    assert r.status_code == 401


def test_full_task_flow(services):
    """Test end-to-end: cliente publica → orquestador asigna → mock ejecuta → pago."""
    client_id = NodeIdentity.generate()

    r = httpx.post(f"{services['orchestrator']}/tasks/submit", json={
        "client_id": client_id.node_id,
        "model": "qwen2.5:7b",
        "prompt": "test integration",
        "max_tokens": 50,
        "payment_nxs": 2.0,
        "verification_probability": 0.0,
    })
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    # Esperar a que se complete
    for _ in range(30):
        time.sleep(0.5)
        r = httpx.get(f"{services['orchestrator']}/tasks/{task_id}")
        task = r.json()
        if task["status"] in ("paid", "verified_paid", "fraud_detected"):
            break
    else:
        pytest.fail(f"Task no completó. Estado final: {task.get('status')}")

    assert task["status"] == "paid"
    assert task["commit"] is not None
    assert task["reveal"] is not None
    assert task["reveal"]["result"].startswith("MOCK_ANSWER_FOR_")
