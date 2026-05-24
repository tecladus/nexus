"""
NEXUS Miner — servidor HTTP que recibe tareas y las ejecuta.

Flujo:
    1. Al arrancar, se registra con uno o más orquestadores
    2. Manda heartbeat cada 30 segundos
    3. Cuando recibe POST /tasks/execute, ejecuta inferencia con Ollama
    4. Envía commit al orquestador
    5. Envía reveal al orquestador
    6. Actualiza estadísticas locales (SQLite)

Para correr:
    python miner/server.py --port 7100 --orchestrator http://localhost:7000
"""

from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import secrets
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Optional

# Path para imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import httpx
import uvicorn

from common.identity import NodeIdentity
from miner.ollama_client import OllamaClient
from miner.executor import TaskExecutor
from miner.storage import MinerDB
from miner.protocol import (
    TaskMessage, TaskKind, DeterminismMode, LLMInferenceSpec,
)


# ============================================================
# Estado del minero
# ============================================================

class MinerState:
    def __init__(
        self,
        identity: NodeIdentity,
        ollama: OllamaClient,
        executor: TaskExecutor,
        db: MinerDB,
        my_endpoint: str,
        orchestrators: list[str],
        stake_nxs: float,
    ):
        self.identity = identity
        self.ollama = ollama
        self.executor = executor
        self.db = db
        self.my_endpoint = my_endpoint
        self.orchestrators = orchestrators
        self.stake_nxs = stake_nxs
        self.started_at = time.time()

        # Capabilities (descubiertas en startup)
        self.preloaded_models: list[str] = []
        self.gpu_model: str = "Unknown"
        self.vram_gb: int = 0
        self.cpu_cores: int = 0


state: Optional[MinerState] = None


# ============================================================
# Schemas
# ============================================================

class ExecuteTaskRequest(BaseModel):
    task_id: str
    spec: dict
    orchestrator_endpoint: str
    payment_nxs: float


# ============================================================
# Funciones auxiliares
# ============================================================

def detect_capabilities():
    """Detecta hardware del minero. Versión simplificada."""
    import os
    import platform

    # CPU cores
    cpu_count = os.cpu_count() or 1

    # GPU: por ahora hardcodeado/manual. En v0.4 vamos a usar pynvml.
    # Para esta versión, leemos de los modelos de Ollama (si los tiene
    # cargados, asumimos que tiene GPU suficiente).

    return {
        "cpu_cores": cpu_count,
        "gpu_model": "RTX 3060",  # placeholder; en v0.4 lo detectamos
        "vram_gb": 12,
        "platform": platform.system(),
    }


async def register_with_orchestrators():
    """Registrarse con todos los orquestadores configurados."""
    payload = json.dumps({
        "node_id": state.identity.node_id,
        "endpoint": state.my_endpoint,
        "gpu_model": state.gpu_model,
        "stake_nxs": state.stake_nxs,
    }, sort_keys=True)
    signature = state.identity.sign(payload)

    body = {
        "node_id": state.identity.node_id,
        "endpoint": state.my_endpoint,
        "gpu_model": state.gpu_model,
        "vram_gb": state.vram_gb,
        "cpu_cores": state.cpu_cores,
        "preloaded_models": state.preloaded_models,
        "stake_nxs": state.stake_nxs,
        "signature": signature,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        for orch_url in state.orchestrators:
            try:
                r = await client.post(f"{orch_url}/miners/register", json=body)
                if r.status_code == 200:
                    print(f"  ✓ Registrado en {orch_url}")
                else:
                    print(f"  ❌ {orch_url} respondió {r.status_code}: {r.text[:80]}")
            except httpx.RequestError as e:
                print(f"  ❌ No pude contactar {orch_url}: {e}")


async def heartbeat_loop():
    """Manda heartbeat cada 30 segundos a todos los orquestadores."""
    while True:
        await asyncio.sleep(30)
        timestamp = time.time()
        payload = f"heartbeat:{state.identity.node_id}:{timestamp}"
        signature = state.identity.sign(payload)

        body = {
            "node_id": state.identity.node_id,
            "timestamp": timestamp,
            "signature": signature,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            for orch_url in state.orchestrators:
                try:
                    await client.post(f"{orch_url}/miners/heartbeat", json=body)
                except httpx.RequestError:
                    pass  # silently fail; mejor que llenar logs


async def execute_and_report(task_id: str, spec: dict, orchestrator_endpoint: str, payment_nxs: float):
    """
    En background:
    1. Ejecuta la inferencia
    2. Manda el commit
    3. Manda el reveal
    """
    print(f"  ⚙️  Ejecutando {task_id} ({spec.get('model')}: \"{spec.get('prompt', '')[:40]}...\")")

    # Registrar en DB local
    state.db.record_task_received(task_id, "via_orchestrator", "llm_inference", spec, payment_nxs)
    state.db.increment_executed(state.identity.node_id)

    # Construir TaskMessage para el executor
    task_msg = TaskMessage(
        task_id=task_id,
        client_id="via_orchestrator",
        kind=TaskKind.LLM_INFERENCE,
        spec=spec,
        payment_nxs=payment_nxs,
    )

    try:
        result = state.executor.execute(task_msg)
    except Exception as e:
        print(f"  ❌ Falló la inferencia: {e}")
        return

    print(f"  ✓ Inferencia OK ({result.inference.compute_time_ms} ms, "
          f"{result.inference.tokens_per_second:.1f} tok/s)")

    # Guardar commit local
    state.db.record_commit(task_id, result.commit_message.commit_hash,
                            result.inference.compute_time_ms)

    # Mandar commit al orquestador
    commit_payload = f"commit:{task_id}:{result.commit_message.commit_hash}"
    commit_signature = state.identity.sign(commit_payload)
    commit_body = {
        "miner_id": state.identity.node_id,
        "commit_hash": result.commit_message.commit_hash,
        "compute_time_ms": result.inference.compute_time_ms,
        "signature": commit_signature,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(
                f"{orchestrator_endpoint}/tasks/{task_id}/commit",
                json=commit_body,
            )
            if r.status_code != 200:
                print(f"  ❌ Commit rechazado: {r.status_code} {r.text[:80]}")
                return
            print(f"  📤 Commit enviado al orquestador")
        except httpx.RequestError as e:
            print(f"  ❌ Error enviando commit: {e}")
            return

    # Esperar un toque (en producción habría un timeout para reveal)
    await asyncio.sleep(0.5)

    # Mandar reveal
    state.db.record_reveal(task_id, result.result_text, result.nonce,
                            result.reveal_message.metadata)

    reveal_payload = f"reveal:{task_id}:{result.result_text[:100]}"
    reveal_signature = state.identity.sign(reveal_payload)
    reveal_body = {
        "miner_id": state.identity.node_id,
        "result": result.result_text,
        "nonce": result.nonce,
        "metadata": result.reveal_message.metadata,
        "signature": reveal_signature,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(
                f"{orchestrator_endpoint}/tasks/{task_id}/reveal",
                json=reveal_body,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("payment_released"):
                    state.db.record_payment(task_id, state.identity.node_id, payment_nxs)
                    print(f"  💰 Pago liberado: {payment_nxs} NXS")
                else:
                    print(f"  ⚠️  Reveal aceptado pero pago no liberado: {data}")
            else:
                print(f"  ❌ Reveal rechazado: {r.status_code} {r.text[:80]}")
        except httpx.RequestError as e:
            print(f"  ❌ Error enviando reveal: {e}")


# ============================================================
# App
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Setup al arrancar y cleanup al parar."""
    # Startup
    print(f"\n🔌 Registrándose con orquestadores...")
    await register_with_orchestrators()

    # Lanzar el loop de heartbeat
    task = asyncio.create_task(heartbeat_loop())

    yield  # acá corre el server

    # Shutdown
    task.cancel()


app = FastAPI(
    title="NEXUS Miner",
    description="Minero del protocolo NEXUS v0.3",
    version="0.3.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    stats = state.db.get_stats(state.identity.node_id) or {}
    return {
        "name": "NEXUS Miner",
        "version": "0.3.0",
        "node_id": state.identity.node_id,
        "endpoint": state.my_endpoint,
        "uptime_seconds": int(time.time() - state.started_at),
        "gpu_model": state.gpu_model,
        "preloaded_models": state.preloaded_models,
        "stats": {
            "tasks_executed": stats.get("total_tasks_executed", 0),
            "tasks_paid": stats.get("total_tasks_paid", 0),
            "total_earned_nxs": stats.get("total_earned_nxs", 0.0),
        },
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/tasks/execute")
async def execute_task(req: ExecuteTaskRequest, background: BackgroundTasks):
    """
    Endpoint que llama el orquestador para asignar una tarea.
    Aceptamos rápido y procesamos en background.
    """
    background.add_task(
        execute_and_report,
        req.task_id,
        req.spec,
        req.orchestrator_endpoint,
        req.payment_nxs,
    )
    return {"status": "accepted", "task_id": req.task_id}


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="NEXUS Miner Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7100)
    parser.add_argument("--orchestrator", action="append", default=[],
                        help="URL del orquestador (puede repetirse)")
    parser.add_argument("--identity-file", default="miner_identity.json")
    parser.add_argument("--db", default="nexus_miner.db")
    parser.add_argument("--stake", type=float, default=1000.0,
                        help="NXS de stake (declarado, en v0.3 no se valida on-chain)")
    args = parser.parse_args()

    if not args.orchestrator:
        args.orchestrator = ["http://127.0.0.1:7000"]

    print("=" * 60)
    print("NEXUS Miner Server v0.3")
    print("=" * 60)

    # Identidad
    identity = NodeIdentity.load_or_create(Path(args.identity_file))

    # Ollama
    print("\n🔍 Verificando Ollama...")
    ollama = OllamaClient()
    if not ollama.is_alive():
        print("❌ Ollama no está corriendo. Arrancalo primero.")
        sys.exit(1)
    models = ollama.list_models()
    print(f"  ✓ Modelos disponibles: {models}")

    # Storage
    db = MinerDB(Path(args.db))

    # Executor
    executor = TaskExecutor(ollama, miner_id=identity.node_id)

    # Capabilities
    caps = detect_capabilities()

    global state
    state = MinerState(
        identity=identity,
        ollama=ollama,
        executor=executor,
        db=db,
        my_endpoint=f"http://{args.host}:{args.port}",
        orchestrators=args.orchestrator,
        stake_nxs=args.stake,
    )
    state.preloaded_models = models
    state.gpu_model = caps["gpu_model"]
    state.vram_gb = caps["vram_gb"]
    state.cpu_cores = caps["cpu_cores"]

    print(f"\n🚀 Minero arrancando en {state.my_endpoint}")
    print(f"   Node ID: {identity.short_id}...")
    print(f"   Orquestadores: {state.orchestrators}")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
