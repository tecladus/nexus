"""
NEXUS Miner — punto de entrada principal v0.2

Este es el "main" del minero. Integra:
- protocol.py     (schemas de mensajes)
- ollama_client.py (runtime de IA)
- executor.py     (ejecución de tareas)
- storage.py      (persistencia local)

Por ahora simula el ciclo completo localmente (sin red P2P todavía,
eso viene en la sesión 3). Pero ya hace inferencia REAL.

Uso:
    python3 main.py                  # demo interactivo
    python3 main.py --benchmark      # benchmark de tu hardware
"""

from __future__ import annotations
import argparse
import secrets
import sys
import time
from dataclasses import asdict
from pathlib import Path

from protocol import (
    TaskMessage, TaskKind, VerificationLevel, DeterminismMode,
    LLMInferenceSpec, PROTOCOL_VERSION,
)
from ollama_client import OllamaClient
from executor import TaskExecutor, generate_commit_hash
from storage import MinerDB


def print_banner():
    print(r"""
╔═══════════════════════════════════════════════════════════╗
║   _   _ _______  ___   _ ____    Miner v0.2              ║
║  | \ | | ____\ \/ / | | / ___|   Protocol v""" + PROTOCOL_VERSION + r"""           ║
║  |  \| |  _|  \  /| | | \___ \                            ║
║  | |\  | |___ /  \| |_| |___) |  Decentralized AI compute ║
║  |_| \_|_____/_/\_\\___/|____/                            ║
╚═══════════════════════════════════════════════════════════╝
""")


def preflight_checks(ollama: OllamaClient) -> str:
    """Verifica que todo esté listo. Devuelve el modelo a usar."""
    print("🔍 Verificando entorno...\n")

    # Check 1: Ollama corriendo
    if not ollama.is_alive():
        print("❌ Ollama no está corriendo.")
        print("   Solución: Abrí Ollama (en Windows debería estar en el system tray)")
        print("   o ejecutá en una terminal: ollama serve")
        sys.exit(1)
    print("✓ Ollama está activo")

    # Check 2: hay al menos un modelo
    models = ollama.list_models()
    if not models:
        print("❌ No hay modelos descargados.")
        print("   Solución: ollama pull qwen2.5:7b")
        sys.exit(1)
    print(f"✓ Modelos disponibles: {', '.join(models)}")

    # Preferir qwen2.5:7b, fallback al primero
    model = "qwen2.5:7b" if "qwen2.5:7b" in models else models[0]
    print(f"✓ Usando modelo: {model}\n")

    return model


def demo_full_cycle(executor: TaskExecutor, db: MinerDB, model: str):
    """Demo del ciclo completo: tarea → commit → reveal → verify → pago."""
    print("=" * 60)
    print("DEMO: ciclo completo de una tarea NEXUS")
    print("=" * 60)

    # Crear tarea como si viniera de un cliente
    spec = LLMInferenceSpec(
        model=model,
        prompt="Explicá qué es la criptografía asimétrica en 3 oraciones cortas.",
        max_tokens=250,
        determinism=DeterminismMode.EXACT,
    )

    task_id = f"task_{secrets.token_hex(6)}"
    task = TaskMessage(
        task_id=task_id,
        client_id="demo_client",
        kind=TaskKind.LLM_INFERENCE,
        spec=asdict(spec),
        payment_nxs=5.0,
        verification_level=VerificationLevel.FAST,
        verification_probability=0.30,  # 30% para que se note la verificación
    )

    miner_id = executor.miner_id

    # 1. Recibir tarea
    print(f"\n📥 [1/5] Cliente publica tarea: {task_id}")
    print(f"        Prompt: \"{spec.prompt}\"")
    db.record_task_received(task_id, task.client_id, task.kind.value,
                             task.spec, task.payment_nxs)
    db.increment_executed(miner_id)

    # 2. Ejecutar
    print(f"\n⚙️  [2/5] Ejecutando inferencia con {model}...")
    start = time.time()
    result = executor.execute(task)
    elapsed = time.time() - start

    print(f"        ✓ Listo en {elapsed:.2f}s — "
          f"{result.inference.tokens_per_second:.1f} tok/s")
    print(f"        Tokens generados: {result.inference.completion_tokens}")

    # 3. Publicar commit
    print(f"\n🔒 [3/5] Publicando COMMIT on-chain (simulado):")
    print(f"        Hash: {result.commit_message.commit_hash[:32]}...")
    db.record_commit(task_id, result.commit_message.commit_hash,
                      result.inference.compute_time_ms)

    # 4. Revelar resultado
    print(f"\n🔓 [4/5] Publicando REVEAL:")
    print(f"        Resultado: \"{result.result_text[:80]}...\"")
    db.record_reveal(task_id, result.result_text, result.nonce,
                      result.reveal_message.metadata)

    # 5. Simular verificación
    import random
    will_verify = random.random() < task.verification_probability
    print(f"\n🎲 [5/5] ¿Validador re-ejecuta para verificar? "
          f"{'SÍ (30% probabilidad)' if will_verify else 'NO'}")

    if will_verify:
        print(f"        Re-ejecutando con mismo task_id, mismo modelo, mismo seed...")
        verify_result = executor.execute(task)

        if verify_result.result_text == result.result_text:
            print(f"        ✅ MATCH — verificación exitosa")
            db.record_payment(task_id, miner_id, task.payment_nxs)
            print(f"\n💰 Pago liberado: {task.payment_nxs} NXS")
        else:
            print(f"        ❌ NO MATCH — outputs distintos")
            print(f"           Esperado: {verify_result.result_text[:60]}...")
            print(f"           Obtenido: {result.result_text[:60]}...")
            print(f"        ⚠️  Esto indicaría minero deshonesto en producción")
            db.record_slashing(task_id, miner_id, 1000.0, "result mismatch")
    else:
        db.record_payment(task_id, miner_id, task.payment_nxs)
        print(f"\n💰 Pago liberado: {task.payment_nxs} NXS (sin verificación esta vez)")

    # Stats finales
    stats = db.get_stats(miner_id)
    print(f"\n📊 Stats acumulados del minero {miner_id}:")
    print(f"   Total ejecutadas: {stats['total_tasks_executed']}")
    print(f"   Pagadas: {stats['total_tasks_paid']}")
    print(f"   Slashed: {stats['total_tasks_slashed']}")
    print(f"   Total ganado: {stats['total_earned_nxs']} NXS")


def benchmark(executor: TaskExecutor, model: str, num_tasks: int = 5):
    """Mini-benchmark: ejecuta N tareas y mide performance."""
    print("=" * 60)
    print(f"BENCHMARK: {num_tasks} inferencias con {model}")
    print("=" * 60)

    prompts = [
        "Listá 5 países de Sudamérica.",
        "¿Cuál es la fórmula química del agua?",
        "Explicá qué es una blockchain en una oración.",
        "Traducí 'Good morning' al español.",
        "¿Cuánto es 17 * 23?",
    ]

    total_tokens = 0
    total_time_ms = 0
    times = []

    for i, prompt in enumerate(prompts[:num_tasks], 1):
        spec = LLMInferenceSpec(model=model, prompt=prompt, max_tokens=150)
        task = TaskMessage(
            task_id=f"bench_{i:03d}",
            client_id="benchmark",
            kind=TaskKind.LLM_INFERENCE,
            spec=asdict(spec),
            payment_nxs=1.0,
        )

        print(f"\n[{i}/{num_tasks}] Prompt: {prompt}")
        start = time.time()
        result = executor.execute(task)
        elapsed_ms = int((time.time() - start) * 1000)

        print(f"        Respuesta: {result.result_text[:70].strip()}...")
        print(f"        {result.inference.completion_tokens} tokens en {elapsed_ms} ms "
              f"({result.inference.tokens_per_second:.1f} tok/s)")

        total_tokens += result.inference.completion_tokens
        total_time_ms += elapsed_ms
        times.append(elapsed_ms)

    # Stats
    avg_tps = (total_tokens / total_time_ms) * 1000 if total_time_ms > 0 else 0

    print(f"\n{'=' * 60}")
    print(f"📊 RESULTADOS")
    print(f"{'=' * 60}")
    print(f"   Tareas completadas: {num_tasks}")
    print(f"   Tokens totales: {total_tokens}")
    print(f"   Tiempo total: {total_time_ms / 1000:.2f} s")
    print(f"   Promedio: {sum(times) / len(times):.0f} ms/tarea")
    print(f"   Velocidad: {avg_tps:.1f} tokens/segundo promedio")
    print(f"\n💡 Estimación: tu hardware podría procesar ~{int(3600000 / (sum(times)/len(times)))} tareas/hora")
    print(f"   A 1 NXS por tarea ≈ {int(3600000 / (sum(times)/len(times)))} NXS/hora teóricos brutos")


def main():
    parser = argparse.ArgumentParser(description="NEXUS Miner v0.2")
    parser.add_argument("--benchmark", action="store_true",
                        help="Correr benchmark en vez del demo")
    parser.add_argument("--db", type=str, default="nexus_miner.db",
                        help="Path al archivo de la base de datos")
    parser.add_argument("--miner-id", type=str, default="local_001",
                        help="ID de este minero")
    args = parser.parse_args()

    print_banner()

    ollama = OllamaClient()
    model = preflight_checks(ollama)

    db = MinerDB(Path(args.db))
    executor = TaskExecutor(ollama, miner_id=args.miner_id)

    if args.benchmark:
        benchmark(executor, model)
    else:
        demo_full_cycle(executor, db, model)

    print(f"\n✓ Datos persistidos en: {args.db}")
    print(f"  Podés inspeccionarla con: sqlite3 {args.db}")


if __name__ == "__main__":
    main()
