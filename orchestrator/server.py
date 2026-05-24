"""
NEXUS Orchestrator — servidor HTTP principal.

El orquestador es el "router" de la red:
- Mineros se registran en él (/miners/register)
- Clientes le mandan tareas (/tasks/submit)
- Él asigna tareas a mineros usando VRF (/internal)
- Recibe commits y reveals (/tasks/{id}/commit, /reveal)
- Eventualmente: invoca a validadores

Arquitectura: FastAPI + httpx async para comunicación entre nodos.

Endpoints públicos:
    POST /miners/register     — minero se registra
    POST /miners/heartbeat    — minero confirma que sigue activo
    GET  /miners              — listar mineros activos (debug/transparencia)

    POST /tasks/submit        — cliente publica una tarea
    GET  /tasks/{task_id}     — estado de una tarea
    POST /tasks/{task_id}/commit  — minero publica commit
    POST /tasks/{task_id}/reveal  — minero publica reveal

    GET  /health              — health check
    GET  /                    — info del nodo

Para correr:
    python orchestrator/server.py --port 7000
"""

from __future__ import annotations
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

# Agregar el directorio padre al path para importar common/
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import httpx
import uvicorn

from common.identity import NodeIdentity, verify_signature
from orchestrator.registry import (
    MinerRegistry, RegisteredMiner, select_miner_vrf,
    HEARTBEAT_TIMEOUT_SECONDS,
)


# ============================================================
# Schemas (Pydantic) — para validación automática de requests
# ============================================================

class RegisterRequest(BaseModel):
    """El minero envía esto para registrarse."""
    node_id: str
    endpoint: str
    gpu_model: str
    vram_gb: int
    cpu_cores: int
    preloaded_models: list[str]
    stake_nxs: float
    signature: str  # Firma del payload (sin la firma misma)


class HeartbeatRequest(BaseModel):
    node_id: str
    timestamp: float
    signature: str


class TaskSubmitRequest(BaseModel):
    """Cliente publica una tarea."""
    client_id: str
    model: str
    prompt: str
    max_tokens: int = 256
    payment_nxs: float = 5.0
    verification_probability: float = 0.10


class CommitRequest(BaseModel):
    miner_id: str
    commit_hash: str
    compute_time_ms: int
    signature: str


class RevealRequest(BaseModel):
    miner_id: str
    result: str
    nonce: str
    metadata: dict = Field(default_factory=dict)
    signature: str


# ============================================================
# Estado del orquestador
# ============================================================

class OrchestratorState:
    """Estado en memoria del orquestador."""

    def __init__(self, identity: NodeIdentity):
        self.identity = identity
        self.registry = MinerRegistry()
        self.tasks: dict[str, dict] = {}     # task_id -> dict con estado
        self.next_task_id = 1
        self.started_at = time.time()


# Variable global del estado (FastAPI patrón estándar)
state: Optional[OrchestratorState] = None


# ============================================================
# Funciones auxiliares
# ============================================================

def gen_task_id() -> str:
    """Generador simple de task_id. En producción usaríamos UUIDs."""
    tid = f"task_{state.next_task_id:08d}"
    state.next_task_id += 1
    return tid


def verify_register_signature(req: RegisterRequest) -> bool:
    """Verifica que el minero realmente firmó su registro."""
    # Construir el payload firmado (sin la firma misma)
    payload = json.dumps({
        "node_id": req.node_id,
        "endpoint": req.endpoint,
        "gpu_model": req.gpu_model,
        "stake_nxs": req.stake_nxs,
    }, sort_keys=True)
    return verify_signature(req.node_id, payload, req.signature)


async def assign_task_to_miner(task_id: str):
    """
    Asigna una tarea a un minero usando VRF y se la envía vía HTTP.

    Esta función corre en background (no bloquea el response al cliente).
    """
    task = state.tasks.get(task_id)
    if not task:
        print(f"  ⚠️  assign_task: task {task_id} no existe")
        return

    model = task["spec"]["model"]
    # Buscar mineros capaces
    candidates = state.registry.find_capable(model, min_stake=0)  # min_stake=0 por ahora

    if not candidates:
        print(f"  ⚠️  Sin mineros disponibles para modelo {model}")
        task["status"] = "no_miners_available"
        return

    # VRF selección
    winner = select_miner_vrf(candidates, task_id=task_id, epoch_seed=str(int(time.time() / 60)))

    print(f"  🎯 Tarea {task_id} → minero {winner.short_id}... ({len(candidates)} candidatos)")

    task["assigned_miner"] = winner.node_id
    task["assigned_endpoint"] = winner.endpoint
    task["status"] = "assigned"

    winner.tasks_assigned += 1

    # Enviar la tarea al minero por HTTP
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{winner.endpoint}/tasks/execute",
                json={
                    "task_id": task_id,
                    "spec": task["spec"],
                    "orchestrator_endpoint": f"http://localhost:{state.port}",
                    "payment_nxs": task["payment_nxs"],
                },
            )
            if response.status_code == 200:
                print(f"  ✓ Minero {winner.short_id}... aceptó la tarea")
            else:
                print(f"  ❌ Minero respondió {response.status_code}: {response.text[:100]}")
                task["status"] = "miner_rejected"
                winner.tasks_failed += 1
    except httpx.RequestError as e:
        print(f"  ❌ Error contactando minero: {e}")
        task["status"] = "miner_unreachable"
        winner.tasks_failed += 1


# ============================================================
# FastAPI app
# ============================================================

app = FastAPI(
    title="NEXUS Orchestrator",
    description="Orquestador del protocolo NEXUS v0.3",
    version="0.3.0",
)


@app.get("/")
async def root():
    """Info del orquestador."""
    return {
        "name": "NEXUS Orchestrator",
        "version": "0.3.0",
        "node_id": state.identity.node_id,
        "uptime_seconds": int(time.time() - state.started_at),
        "miners_registered": state.registry.total_registered(),
        "miners_active": state.registry.count_active(),
        "tasks_total": len(state.tasks),
    }


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}


# ----- Mineros -----

@app.post("/miners/register")
async def register_miner(req: RegisterRequest):
    """Endpoint donde los mineros se registran."""
    # Verificar firma
    if not verify_register_signature(req):
        raise HTTPException(status_code=401, detail="Firma inválida")

    miner = RegisteredMiner(
        node_id=req.node_id,
        endpoint=req.endpoint,
        gpu_model=req.gpu_model,
        vram_gb=req.vram_gb,
        cpu_cores=req.cpu_cores,
        preloaded_models=req.preloaded_models,
        stake_nxs=req.stake_nxs,
        registered_at=time.time(),
    )
    state.registry.register(miner)

    print(f"  ✓ Minero registrado: {miner.short_id}... "
          f"(GPU: {miner.gpu_model}, modelos: {miner.preloaded_models})")

    return {
        "status": "registered",
        "node_id": miner.node_id,
        "heartbeat_timeout_seconds": HEARTBEAT_TIMEOUT_SECONDS,
    }


@app.post("/miners/heartbeat")
async def miner_heartbeat(req: HeartbeatRequest):
    """Minero confirma que sigue vivo."""
    # Verificar firma del heartbeat
    payload = f"heartbeat:{req.node_id}:{req.timestamp}"
    if not verify_signature(req.node_id, payload, req.signature):
        raise HTTPException(status_code=401, detail="Firma inválida")

    if not state.registry.heartbeat(req.node_id):
        raise HTTPException(status_code=404, detail="Minero no registrado")

    return {"status": "alive"}


@app.get("/miners")
async def list_miners():
    """Lista pública de mineros (transparencia del orquestador)."""
    miners = state.registry.all_active()
    return {
        "count": len(miners),
        "miners": [
            {
                "node_id": m.node_id,
                "short_id": m.short_id,
                "gpu_model": m.gpu_model,
                "vram_gb": m.vram_gb,
                "preloaded_models": m.preloaded_models,
                "stake_nxs": m.stake_nxs,
                "reputation_score": m.reputation_score,
                "tasks_assigned": m.tasks_assigned,
                "tasks_completed": m.tasks_completed,
                "last_heartbeat_ago": int(time.time() - m.last_heartbeat),
            }
            for m in miners
        ],
    }


# ----- Tareas -----

@app.post("/tasks/submit")
async def submit_task(req: TaskSubmitRequest, background: BackgroundTasks):
    """Cliente publica una tarea."""
    if state.registry.count_active() == 0:
        raise HTTPException(status_code=503, detail="No hay mineros activos")

    task_id = gen_task_id()
    task = {
        "task_id": task_id,
        "client_id": req.client_id,
        "spec": {
            "model": req.model,
            "prompt": req.prompt,
            "max_tokens": req.max_tokens,
            "determinism": "exact",
        },
        "payment_nxs": req.payment_nxs,
        "verification_probability": req.verification_probability,
        "status": "published",
        "submitted_at": time.time(),
        "assigned_miner": None,
        "commit": None,
        "reveal": None,
    }
    state.tasks[task_id] = task

    print(f"📥 Tarea {task_id} de cliente {req.client_id[:12]}...: \"{req.prompt[:50]}...\"")

    # Asignar en background para no bloquear la respuesta
    background.add_task(assign_task_to_miner, task_id)

    return {
        "task_id": task_id,
        "status": "published",
        "message": "Tarea recibida, asignando minero...",
    }


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Estado de una tarea."""
    task = state.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


@app.post("/tasks/{task_id}/commit")
async def receive_commit(task_id: str, req: CommitRequest):
    """Minero publica el commit hash de su resultado."""
    task = state.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    if task.get("assigned_miner") != req.miner_id:
        raise HTTPException(status_code=403, detail="Minero no asignado a esta tarea")

    # Verificar firma del commit
    payload = f"commit:{task_id}:{req.commit_hash}"
    if not verify_signature(req.miner_id, payload, req.signature):
        raise HTTPException(status_code=401, detail="Firma inválida")

    task["commit"] = {
        "hash": req.commit_hash,
        "compute_time_ms": req.compute_time_ms,
        "received_at": time.time(),
    }
    task["status"] = "committed"

    print(f"🔒 Commit recibido para {task_id}: {req.commit_hash[:16]}...")
    return {"status": "committed"}


@app.post("/tasks/{task_id}/reveal")
async def receive_reveal(task_id: str, req: RevealRequest):
    """Minero revela el resultado real."""
    import hashlib

    task = state.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    if not task.get("commit"):
        raise HTTPException(status_code=400, detail="No hay commit previo")

    if task.get("assigned_miner") != req.miner_id:
        raise HTTPException(status_code=403, detail="Minero no asignado")

    # Verificar firma del reveal
    payload = f"reveal:{task_id}:{req.result[:100]}"
    if not verify_signature(req.miner_id, payload, req.signature):
        raise HTTPException(status_code=401, detail="Firma inválida")

    # Verificar que el reveal coincide con el commit
    expected_hash = hashlib.sha256(f"{req.result}||{req.nonce}".encode()).hexdigest()
    if expected_hash != task["commit"]["hash"]:
        # ¡Minero intentó cambiar el resultado!
        task["status"] = "fraud_detected"
        miner = state.registry.get(req.miner_id)
        if miner:
            miner.tasks_failed += 1
            miner.reputation_score *= 0.5  # penalización
        raise HTTPException(
            status_code=400,
            detail=f"Hash mismatch: el reveal no coincide con el commit. "
                   f"Esto sería slashing en producción."
        )

    # Verificación pasó
    task["reveal"] = {
        "result": req.result,
        "nonce": req.nonce,
        "metadata": req.metadata,
        "received_at": time.time(),
    }

    # Decidir si verificar profundamente (probabilístico)
    import random
    will_verify = random.random() < task["verification_probability"]

    if will_verify:
        task["status"] = "pending_verification"
        print(f"🔓 Reveal recibido para {task_id}. Marcado para verificación (re-ejecución)")
        # En v0.3 simplificado: marcamos pero no re-ejecutamos.
        # En sesión 4 vamos a tener validadores que rotan.
        # Por ahora, simulamos que pasó verificación
        task["status"] = "verified_paid"
    else:
        task["status"] = "paid"
        print(f"💰 Reveal aceptado para {task_id} (sin verificación esta vez). Pago liberado.")

    # Update miner stats
    miner = state.registry.get(req.miner_id)
    if miner:
        miner.tasks_completed += 1

    return {
        "status": task["status"],
        "verified": will_verify,
        "payment_released": True,
    }


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="NEXUS Orchestrator")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7000, help="Puerto (default: 7000)")
    parser.add_argument("--identity-file", default="orchestrator_identity.json",
                        help="Archivo de identidad del nodo")
    args = parser.parse_args()

    global state
    print("=" * 60)
    print("NEXUS Orchestrator v0.3")
    print("=" * 60)

    identity_path = Path(args.identity_file)
    identity = NodeIdentity.load_or_create(identity_path)

    state = OrchestratorState(identity)
    state.port = args.port  # útil para que el orquestador comunique su URL a mineros

    print(f"\n🚀 Iniciando servidor en http://{args.host}:{args.port}")
    print(f"   Docs interactivos: http://{args.host}:{args.port}/docs")
    print(f"   Node ID: {identity.node_id}")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
