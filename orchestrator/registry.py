"""
MinerRegistry — el orquestador mantiene un registro de mineros disponibles.

Cuando un minero se conecta, hace "register" enviando sus capabilities firmadas.
El orquestador valida la firma y agrega al minero al registro.

Periódicamente cada minero hace "heartbeat" para indicar que sigue vivo.
Si pasa demasiado tiempo sin heartbeat, el minero se marca inactivo.
"""

from __future__ import annotations
import time
import hashlib
from dataclasses import dataclass, field
from typing import Optional


# Cuánto tiempo sin heartbeat hasta considerar a un minero offline
HEARTBEAT_TIMEOUT_SECONDS = 60


@dataclass
class RegisteredMiner:
    """Representación interna de un minero en el registro del orquestador."""
    node_id: str
    endpoint: str              # URL donde el minero escucha (ej. "http://192.168.0.10:7100")
    gpu_model: str
    vram_gb: int
    cpu_cores: int
    preloaded_models: list[str]
    stake_nxs: float
    registered_at: float
    last_heartbeat: float = field(default_factory=time.time)
    reputation_score: float = 1.0

    # Stats que el orquestador trackea
    tasks_assigned: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0

    @property
    def is_active(self) -> bool:
        """¿Está vivo según el último heartbeat?"""
        return (time.time() - self.last_heartbeat) < HEARTBEAT_TIMEOUT_SECONDS

    @property
    def short_id(self) -> str:
        return self.node_id[:12]

    def supports_model(self, model: str) -> bool:
        """¿Este minero tiene el modelo precargado?"""
        return model in self.preloaded_models


class MinerRegistry:
    """Registro en memoria de los mineros conectados."""

    def __init__(self):
        self._miners: dict[str, RegisteredMiner] = {}

    def register(self, miner: RegisteredMiner) -> None:
        """Agrega o actualiza un minero."""
        self._miners[miner.node_id] = miner

    def heartbeat(self, node_id: str) -> bool:
        """Actualiza el last_heartbeat. Devuelve False si el minero no existe."""
        if node_id not in self._miners:
            return False
        self._miners[node_id].last_heartbeat = time.time()
        return True

    def get(self, node_id: str) -> Optional[RegisteredMiner]:
        return self._miners.get(node_id)

    def all_active(self) -> list[RegisteredMiner]:
        """Mineros que están activos (con heartbeat reciente)."""
        return [m for m in self._miners.values() if m.is_active]

    def find_capable(self, model: str, min_stake: float = 0.0) -> list[RegisteredMiner]:
        """Mineros que pueden ejecutar una tarea con cierto modelo + stake mínimo."""
        return [
            m for m in self.all_active()
            if m.supports_model(model) and m.stake_nxs >= min_stake
        ]

    def count_active(self) -> int:
        return sum(1 for m in self._miners.values() if m.is_active)

    def total_registered(self) -> int:
        return len(self._miners)


# ============================================================
# Selección VRF
# ============================================================

def select_miner_vrf(
    candidates: list[RegisteredMiner],
    task_id: str,
    epoch_seed: str = "",
) -> Optional[RegisteredMiner]:
    """
    Selección verificable y reproducible.

    Cualquiera con la misma lista de candidates + task_id + epoch_seed
    llega al MISMO minero. Esto previene que el orquestador favorezca
    a sus mineros amigos.

    Implementación simple para v0.3:
        H(task_id || epoch_seed || node_id) determina el "score" de cada minero
        Gana el de score más alto.

    Es resistente a manipulación porque:
    - El orquestador no puede elegir task_id (lo da el cliente)
    - El orquestador no puede cambiar el resultado de SHA-256
    - Si quisiera favorecer a un minero, tendría que cambiar la lista
      de candidates, pero esa lista es pública (cualquiera puede ver
      qué mineros están registrados via API)

    En v1.0 reemplazaremos esto con una VRF criptográfica real (Ed25519-VRF).
    """
    if not candidates:
        return None

    # Calcular score de cada candidato
    scored = []
    for miner in candidates:
        seed = f"{task_id}||{epoch_seed}||{miner.node_id}"
        score_bytes = hashlib.sha256(seed.encode("utf-8")).digest()
        # Tomar los primeros 8 bytes como un int
        score = int.from_bytes(score_bytes[:8], "big")
        scored.append((score, miner))

    # Ordenar y devolver el ganador
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


# ============================================================
# Demo
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("MinerRegistry — demo")
    print("=" * 60)

    registry = MinerRegistry()

    # Simular 5 mineros registrándose
    for i in range(5):
        miner = RegisteredMiner(
            node_id=f"{i:064x}",  # node_id fake de 64 chars
            endpoint=f"http://localhost:710{i}",
            gpu_model="RTX 3060",
            vram_gb=12,
            cpu_cores=24,
            preloaded_models=["qwen2.5:7b", "llama3.1:8b"] if i % 2 == 0 else ["qwen2.5:7b"],
            stake_nxs=500.0 + (i * 100),
            registered_at=time.time(),
        )
        registry.register(miner)

    print(f"\n📊 Total registrados: {registry.total_registered()}")
    print(f"   Activos: {registry.count_active()}")

    # Buscar capaces de correr llama3.1
    capable = registry.find_capable("llama3.1:8b", min_stake=500.0)
    print(f"\n🔍 Mineros que pueden correr llama3.1:8b con stake >= 500:")
    for m in capable:
        print(f"   - {m.short_id}... (stake: {m.stake_nxs} NXS)")

    # Selección VRF: misma tarea siempre elige al mismo minero
    print(f"\n🎲 VRF: corriendo 3 veces la misma selección (debe dar lo mismo)")
    all_miners = registry.all_active()
    for run in range(3):
        winner = select_miner_vrf(all_miners, task_id="task_abc123", epoch_seed="block_42")
        print(f"   Run {run+1}: ganador {winner.short_id}...")

    # Pero distintas tareas eligen distintos mineros (distribución pareja)
    print(f"\n📈 Distribución sobre 1000 tareas distintas:")
    counts = {m.node_id: 0 for m in all_miners}
    for i in range(1000):
        winner = select_miner_vrf(all_miners, task_id=f"task_{i}", epoch_seed="block_42")
        counts[winner.node_id] += 1

    for node_id, count in counts.items():
        print(f"   {node_id[:12]}...: {count} tareas ({count/10:.1f}%)")
