"""
TaskExecutor — el corazón del minero NEXUS.

Toma una TaskMessage del protocolo, ejecuta el trabajo real (inferencia
con Ollama), genera el commit criptográfico, y produce el reveal.

Maneja el problema del NO-DETERMINISMO de los LLMs forzando:
- temperature = 0.0
- top_k = 1
- top_p = 1.0
- seed derivado del task_id (reproducible)

Esto hace que el mismo task_id + mismo modelo → mismo output exacto,
lo que permite verificación byte-a-byte.
"""

from __future__ import annotations
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from protocol import (
    TaskMessage,
    CommitMessage,
    RevealMessage,
    TaskKind,
    DeterminismMode,
    LLMInferenceSpec,
)
from ollama_client import OllamaClient, InferenceResult, OllamaError


def hash_sha256(data: str) -> str:
    """Hash SHA-256, hex digest."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def derive_seed(task_id: str) -> int:
    """
    Deriva un seed determinístico a partir del task_id.

    Esto asegura que dos mineros ejecutando la misma tarea usen
    el mismo seed, lo que es necesario para que sus outputs coincidan
    byte-a-byte (asumiendo el mismo modelo y modo EXACT).
    """
    h = hashlib.sha256(task_id.encode("utf-8")).digest()
    # Tomamos los primeros 8 bytes como un int sin signo
    # Ollama acepta seeds positivos
    return int.from_bytes(h[:8], byteorder="big") & 0x7FFFFFFF


def generate_commit_hash(result: str, nonce: str) -> str:
    """H(result || nonce). El nonce previene preimage attacks."""
    return hash_sha256(f"{result}||{nonce}")


@dataclass
class ExecutionResult:
    """Lo que devuelve el ejecutor: todo lo necesario para los próximos pasos."""
    task_id: str
    result_text: str
    commit_message: CommitMessage
    reveal_message: RevealMessage
    inference: InferenceResult       # datos crudos de la inferencia
    nonce: str                       # guardado para reveal posterior


class TaskExecutor:
    """
    Ejecuta tareas del protocolo NEXUS.

    Uso típico:
        executor = TaskExecutor(ollama_client, miner_id="my_miner_001")
        result = executor.execute(task_message)
        # publicar result.commit_message
        # ... esperar timeout ...
        # publicar result.reveal_message
    """

    def __init__(self, ollama: OllamaClient, miner_id: str):
        self.ollama = ollama
        self.miner_id = miner_id

    def execute(self, task: TaskMessage) -> ExecutionResult:
        """Ejecuta la tarea y devuelve commit + reveal listos para publicar."""
        if task.kind != TaskKind.LLM_INFERENCE.value and task.kind != TaskKind.LLM_INFERENCE:
            raise NotImplementedError(
                f"En v0.1 solo soportamos LLM_INFERENCE. Recibí: {task.kind}"
            )

        # Parsear spec
        spec_dict = task.spec
        spec = LLMInferenceSpec(
            model=spec_dict["model"],
            prompt=spec_dict["prompt"],
            max_tokens=spec_dict.get("max_tokens", 512),
            determinism=DeterminismMode(spec_dict.get("determinism", "exact")),
            system_prompt=spec_dict.get("system_prompt"),
        )

        # Configurar parámetros según modo de determinismo
        if spec.determinism == DeterminismMode.EXACT:
            temperature = 0.0
            top_k = 1
            top_p = 1.0
            seed = derive_seed(task.task_id)
        else:
            # SEMANTIC: usamos temperatura moderada
            temperature = 0.7
            top_k = 40
            top_p = 0.9
            seed = None  # genuinamente aleatorio

        # Ejecutar inferencia
        start = time.time()
        try:
            inference = self.ollama.generate(
                model=spec.model,
                prompt=spec.prompt,
                max_tokens=spec.max_tokens,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                seed=seed,
                system_prompt=spec.system_prompt,
            )
        except OllamaError as e:
            raise RuntimeError(f"Fallo en inferencia para {task.task_id}: {e}")

        wall_time_ms = int((time.time() - start) * 1000)

        # Generar nonce y commit
        nonce = secrets.token_hex(16)  # 128 bits
        commit_hash = generate_commit_hash(inference.text, nonce)

        # Construir mensajes
        commit_msg = CommitMessage(
            task_id=task.task_id,
            miner_id=self.miner_id,
            commit_hash=commit_hash,
            compute_time_ms=wall_time_ms,
        )

        reveal_msg = RevealMessage(
            task_id=task.task_id,
            miner_id=self.miner_id,
            result=inference.text,
            nonce=nonce,
            metadata={
                "model": inference.model,
                "prompt_tokens": inference.prompt_tokens,
                "completion_tokens": inference.completion_tokens,
                "tokens_per_second": round(inference.tokens_per_second, 2),
                "determinism": spec.determinism.value,
                "seed": seed,
            },
        )

        return ExecutionResult(
            task_id=task.task_id,
            result_text=inference.text,
            commit_message=commit_msg,
            reveal_message=reveal_msg,
            inference=inference,
            nonce=nonce,
        )


# ============================================================
# Demo de ejecución end-to-end
# ============================================================

if __name__ == "__main__":
    from dataclasses import asdict
    from protocol import VerificationLevel

    print("=" * 60)
    print("NEXUS Miner — ejecución de tarea REAL con Ollama")
    print("=" * 60)

    # Setup
    ollama = OllamaClient()
    if not ollama.is_alive():
        print("\n❌ Ollama no está corriendo. Arrancalo primero.")
        exit(1)

    models = ollama.list_models()
    if not models:
        print("\n❌ No hay modelos. Ejecutá: ollama pull qwen2.5:7b")
        exit(1)

    model = "qwen2.5:7b" if "qwen2.5:7b" in models else models[0]
    print(f"\n✓ Usando modelo: {model}")

    executor = TaskExecutor(ollama, miner_id="local_miner_001")

    # Crear una tarea de ejemplo (en producción vendría del orquestador)
    spec = LLMInferenceSpec(
        model=model,
        prompt="Listá tres ventajas de las criptomonedas descentralizadas. Sé conciso.",
        max_tokens=300,
        determinism=DeterminismMode.EXACT,
    )

    task = TaskMessage(
        task_id="task_demo_001",
        client_id="client_demo",
        kind=TaskKind.LLM_INFERENCE,
        spec=asdict(spec),
        payment_nxs=5.0,
        verification_level=VerificationLevel.FAST,
    )

    print(f"\n📋 Tarea recibida: {task.task_id}")
    print(f"   Modelo: {spec.model}")
    print(f"   Prompt: {spec.prompt}")
    print(f"   Pago: {task.payment_nxs} NXS")

    print(f"\n⚙️  Ejecutando inferencia...")
    result = executor.execute(task)

    print(f"\n📝 Resultado del modelo:")
    print("-" * 60)
    print(result.result_text)
    print("-" * 60)

    print(f"\n🔒 COMMIT (lo que se publica primero on-chain):")
    print(f"   {result.commit_message.commit_hash}")

    print(f"\n📊 Metadata:")
    print(f"   Tokens generados: {result.inference.completion_tokens}")
    print(f"   Tiempo: {result.inference.compute_time_ms} ms")
    print(f"   Velocidad: {result.inference.tokens_per_second:.1f} tok/s")

    print(f"\n🔓 REVEAL (se publica después del commit):")
    print(f"   Nonce: {result.nonce}")
    print(f"   Result hash: {hash_sha256(result.result_text)[:32]}...")

    # Verificación: ejecutar otra vez la misma tarea y comparar
    print(f"\n🔬 Test de reproducibilidad (¿otro minero llegaría al mismo resultado?)...")
    result2 = executor.execute(task)

    if result.result_text == result2.result_text:
        print(f"   ✓ Outputs IDÉNTICOS — verificación byte-a-byte es viable")
    else:
        print(f"   ⚠️  Outputs distintos — necesitaríamos verificación semántica")
        print(f"      Diferencia detectada en posición {_first_diff(result.result_text, result2.result_text)}")


def _first_diff(a: str, b: str) -> int:
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            return i
    return min(len(a), len(b))
