"""
NEXUS Protocol Schemas v0.1

Define la estructura de todos los mensajes del protocolo. Cada mensaje
incluye `protocol_version` para futura compatibilidad.

Estos schemas son la "interfaz" entre nodos. Si dos nodos están en
versiones distintas pero ambas soportan v0.1, se pueden hablar.

Diseño: usamos dataclasses con `to_dict()` / `from_dict()` en vez de
JSON Schema o Pydantic para mantener cero dependencias en este punto.
En versiones futuras vamos a migrar a algo más robusto (probablemente
protobuf cuando pasemos a Rust).
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Any


PROTOCOL_VERSION = "0.1.0"


# ============================================================
# Enums
# ============================================================

class VerificationLevel(Enum):
    """Nivel de verificación que pide el cliente para su tarea."""
    FAST = "fast"           # Probabilística (default, más barato)
    REDUNDANT = "redundant" # N mineros independientes
    TEE = "tee"             # Trusted Execution Environment
    ZK = "zk"               # Zero-knowledge proof (futuro)


class TaskKind(Enum):
    """Tipo de trabajo computacional."""
    LLM_INFERENCE = "llm_inference"
    LLM_FINETUNE = "llm_finetune"
    IMAGE_GENERATION = "image_generation"
    RENDER_FRAME = "render_frame"
    SCIENTIFIC_COMPUTE = "scientific_compute"


class TaskStatus(Enum):
    """Estados por los que pasa una tarea."""
    PUBLISHED = "published"
    ASSIGNED = "assigned"
    COMMITTED = "committed"
    REVEALED = "revealed"
    VERIFIED = "verified"
    PAID = "paid"
    SLASHED = "slashed"
    EXPIRED = "expired"


class DeterminismMode(Enum):
    """
    Cómo manejar el no-determinismo de los LLMs.

    EXACT: temperatura=0, comparación byte-a-byte (más estricto)
    SEMANTIC: comparación por similaridad de embeddings (más flexible, más complejo)
    """
    EXACT = "exact"
    SEMANTIC = "semantic"


# ============================================================
# Mensaje base
# ============================================================

@dataclass
class Message:
    """Base de todos los mensajes del protocolo."""
    protocol_version: str = PROTOCOL_VERSION
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Convertir Enums a sus valores string
        return _convert_enums(d)


def _convert_enums(obj: Any) -> Any:
    """Convierte recursivamente Enums a sus valores."""
    if isinstance(obj, dict):
        return {k: _convert_enums(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_enums(v) for v in obj]
    if isinstance(obj, Enum):
        return obj.value
    return obj


# ============================================================
# Specs específicos por tipo de tarea
# ============================================================

@dataclass
class LLMInferenceSpec:
    """Especificación de una tarea de inferencia de LLM."""
    model: str                  # ej. "qwen2.5:7b"
    prompt: str
    max_tokens: int = 512
    determinism: DeterminismMode = DeterminismMode.EXACT
    # Si determinism == EXACT, estos son los parámetros forzados:
    # temperature = 0.0
    # top_k = 1
    # top_p = 1.0
    # seed = task_id_hash (para reproducibilidad)
    system_prompt: Optional[str] = None


# ============================================================
# Mensajes del protocolo
# ============================================================

@dataclass
class TaskMessage(Message):
    """Una tarea publicada por un cliente, lista para ser asignada."""
    task_id: str = ""
    client_id: str = ""
    kind: TaskKind = TaskKind.LLM_INFERENCE
    spec: dict = field(default_factory=dict)  # serializado de LLMInferenceSpec u otro
    payment_nxs: float = 0.0
    deadline_seconds: int = 300  # 5 minutos por defecto
    verification_level: VerificationLevel = VerificationLevel.FAST
    verification_probability: float = 0.10
    min_miner_stake: float = 500.0


@dataclass
class CommitMessage(Message):
    """Minero publica el commit de su resultado."""
    task_id: str = ""
    miner_id: str = ""
    commit_hash: str = ""
    compute_time_ms: int = 0


@dataclass
class RevealMessage(Message):
    """Minero revela el resultado real tras el commit."""
    task_id: str = ""
    miner_id: str = ""
    result: str = ""
    nonce: str = ""
    metadata: dict = field(default_factory=dict)  # tokens generados, modelo usado, etc.


@dataclass
class VerificationMessage(Message):
    """Validador atestigua si la verificación pasó."""
    task_id: str = ""
    validator_id: str = ""
    verified: bool = False
    expected_result_hash: Optional[str] = None
    notes: str = ""


# ============================================================
# Capabilities profile del minero
# ============================================================

@dataclass
class MinerCapabilities(Message):
    """Lo que un minero declara que puede hacer."""
    miner_id: str = ""
    gpu_model: str = ""
    vram_gb: int = 0
    cpu_model: str = ""
    cpu_cores: int = 0
    ram_gb: int = 0
    preloaded_models: list = field(default_factory=list)
    supported_task_kinds: list = field(default_factory=list)
    bandwidth_mbps: int = 0
    stake_nxs: float = 0.0


# ============================================================
# Utilidades de serialización
# ============================================================

def parse_message(json_str: str) -> dict:
    """
    Parsea un mensaje JSON y verifica versión del protocolo.
    Devuelve dict (no convierte a dataclass automáticamente porque
    necesitamos saber el tipo primero).
    """
    data = json.loads(json_str)

    # Verificar versión
    version = data.get("protocol_version", "unknown")
    if version != PROTOCOL_VERSION:
        # Por ahora solo warning; en futuro: manejar compatibilidad
        print(f"⚠️  Protocol version mismatch: got {version}, expected {PROTOCOL_VERSION}")

    return data


if __name__ == "__main__":
    # Mini demo: imprimir un mensaje de ejemplo de cada tipo
    print("=" * 60)
    print("NEXUS Protocol Schemas v" + PROTOCOL_VERSION)
    print("=" * 60)

    # Ejemplo de TaskMessage
    spec = LLMInferenceSpec(
        model="qwen2.5:7b",
        prompt="Explicá en una oración qué es Bitcoin.",
        max_tokens=200,
        determinism=DeterminismMode.EXACT,
    )

    task = TaskMessage(
        task_id="task_abc123",
        client_id="client_alice",
        kind=TaskKind.LLM_INFERENCE,
        spec=asdict(spec),
        payment_nxs=5.0,
        deadline_seconds=300,
        verification_level=VerificationLevel.FAST,
    )

    print("\n📨 Ejemplo de TaskMessage:")
    print(task.to_json())

    # Ejemplo de CommitMessage
    commit = CommitMessage(
        task_id="task_abc123",
        miner_id="miner_bob",
        commit_hash="a1b2c3d4e5f6...",
        compute_time_ms=1234,
    )
    print("\n📨 Ejemplo de CommitMessage:")
    print(commit.to_json())
