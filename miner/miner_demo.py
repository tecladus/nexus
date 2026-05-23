"""
NEXUS Miner — Prototipo educativo v0.1

Este script demuestra el concepto central de verificación commit-reveal
que es el corazón del protocolo NEXUS.

NO usa AI real todavía (eso viene en la sesión 2), pero simula el flujo
completo de:
  1. Cliente publica una tarea
  2. Minero la ejecuta
  3. Minero publica COMMIT (hash del resultado)
  4. Validador opcionalmente verifica re-ejecutando
  5. Minero REVELA el resultado
  6. Sistema decide si pagar o aplicar slashing

Ejecutar:
    python miner_demo.py
"""

import hashlib
import secrets
import time
import random
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


# ============================================================
# Tipos básicos
# ============================================================

class TaskStatus(Enum):
    PUBLISHED = "published"
    ASSIGNED = "assigned"
    COMMITTED = "committed"
    REVEALED = "revealed"
    VERIFIED = "verified"
    PAID = "paid"
    SLASHED = "slashed"


@dataclass
class Task:
    """Una tarea computacional publicada por un cliente."""
    task_id: str
    description: str
    input_data: str          # En la versión real: prompt, datos, modelo
    expected_compute_ms: int  # Estimación de cuánto debería tardar
    payment_nxs: float        # Pago bloqueado en escrow
    verification_probability: float = 0.10  # 10% de chance de re-verificación
    status: TaskStatus = TaskStatus.PUBLISHED


@dataclass
class Miner:
    """Un minero de la red."""
    miner_id: str
    stake_nxs: float          # NXS bloqueados como garantía
    is_honest: bool = True    # Para simulación: ¿este minero es tramposo?
    earnings: float = 0.0
    total_slashed: float = 0.0


@dataclass
class Commit:
    """El commit que un minero publica antes de revelar."""
    task_id: str
    miner_id: str
    commit_hash: str          # H(result || nonce)
    timestamp: float


@dataclass
class Reveal:
    """El reveal del resultado real."""
    task_id: str
    miner_id: str
    result: str
    nonce: str                # El nonce usado en el commit


# ============================================================
# Funciones core (el "protocolo")
# ============================================================

def hash_sha256(data: str) -> str:
    """Hash SHA-256 estándar."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def generate_commit(result: str, nonce: str) -> str:
    """
    Genera el commit hash: H(result || nonce)

    El nonce previene que un atacante pueda inferir el resultado
    haciendo brute force sobre outputs posibles.
    """
    return hash_sha256(f"{result}||{nonce}")


def verify_commit(commit_hash: str, result: str, nonce: str) -> bool:
    """Verifica que un reveal coincide con el commit publicado."""
    return generate_commit(result, nonce) == commit_hash


def execute_task(task: Task, miner: Miner) -> str:
    """
    Ejecuta la tarea. Esta es la parte que en la versión real va a ser
    inferencia de IA. Acá lo simulamos.

    Si el minero es deshonesto, devuelve basura.
    """
    # Simular tiempo de cómputo
    time.sleep(task.expected_compute_ms / 1000.0)

    if miner.is_honest:
        # El "resultado correcto" es determinístico: hash del input
        return f"RESULT[{hash_sha256(task.input_data)[:16]}]"
    else:
        # Minero tramposo devuelve basura
        return f"TRAMPA[{secrets.token_hex(8)}]"


def re_execute_for_verification(task: Task) -> str:
    """
    Un validador re-ejecuta la tarea para verificar.
    Asumimos el validador es honesto.
    """
    return f"RESULT[{hash_sha256(task.input_data)[:16]}]"


def should_verify(probability: float) -> bool:
    """Decide aleatoriamente si verificar esta tarea."""
    return random.random() < probability


# ============================================================
# Lógica económica
# ============================================================

def pay_miner(miner: Miner, payment: float) -> None:
    """Libera el pago al minero."""
    miner.earnings += payment
    print(f"  💰 Pago liberado: {payment:.2f} NXS → {miner.miner_id}")


def slash_miner(miner: Miner, reason: str) -> None:
    """Aplica slashing: confisca todo el stake del minero."""
    slashed_amount = miner.stake_nxs
    miner.total_slashed += slashed_amount
    miner.stake_nxs = 0
    print(f"  ⚠️  SLASHING: {slashed_amount:.2f} NXS confiscados a {miner.miner_id} ({reason})")


# ============================================================
# El flujo completo de una tarea
# ============================================================

def process_task(task: Task, miner: Miner, verbose: bool = True) -> dict:
    """
    Ejecuta el flujo completo commit-reveal-verify-pay/slash.

    Devuelve un dict con el resultado de la simulación.
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"📋 Tarea: {task.task_id} — {task.description}")
        print(f"   Pago: {task.payment_nxs} NXS")
        print(f"   Minero: {miner.miner_id} (stake: {miner.stake_nxs} NXS, honesto: {miner.is_honest})")

    # PASO 1: Minero ejecuta la tarea
    task.status = TaskStatus.ASSIGNED
    result = execute_task(task, miner)
    if verbose:
        print(f"  ✓ Tarea ejecutada. Resultado (oculto al inicio): {result[:30]}...")

    # PASO 2: Minero publica COMMIT (no revela aún)
    nonce = secrets.token_hex(16)  # 128 bits de aleatoriedad
    commit_hash = generate_commit(result, nonce)
    commit = Commit(
        task_id=task.task_id,
        miner_id=miner.miner_id,
        commit_hash=commit_hash,
        timestamp=time.time()
    )
    task.status = TaskStatus.COMMITTED
    if verbose:
        print(f"  🔒 Commit publicado on-chain: {commit_hash[:16]}...")

    # PASO 3: Decisión probabilística de verificación
    will_verify = should_verify(task.verification_probability)
    if verbose:
        print(f"  🎲 ¿Se verifica esta tarea? {'SÍ' if will_verify else 'NO'} "
              f"(probabilidad: {task.verification_probability*100:.0f}%)")

    # PASO 4: Minero REVELA el resultado
    reveal = Reveal(
        task_id=task.task_id,
        miner_id=miner.miner_id,
        result=result,
        nonce=nonce
    )
    task.status = TaskStatus.REVEALED

    # PASO 5: Verificar que el reveal coincide con el commit
    if not verify_commit(commit.commit_hash, reveal.result, reveal.nonce):
        # Esto NUNCA debería pasar si el minero juega bien
        # Si pasa, el minero intentó cambiar el resultado después del commit
        slash_miner(miner, "commit no coincide con reveal")
        return {"outcome": "slashed_invalid_commit", "miner_earnings": miner.earnings}

    # PASO 6: Verificación profunda (si fue elegida)
    if will_verify:
        expected = re_execute_for_verification(task)
        if reveal.result == expected:
            task.status = TaskStatus.VERIFIED
            pay_miner(miner, task.payment_nxs)
            return {"outcome": "verified_and_paid", "miner_earnings": miner.earnings}
        else:
            # ¡Minero tramposo agarrado!
            slash_miner(miner, "resultado incorrecto detectado en verificación")
            return {"outcome": "slashed_wrong_result", "miner_earnings": miner.earnings}
    else:
        # No verificada, se paga (esto es donde un minero deshonesto se la zafa)
        task.status = TaskStatus.PAID
        pay_miner(miner, task.payment_nxs)
        return {"outcome": "paid_without_verification", "miner_earnings": miner.earnings}


# ============================================================
# Simulación: ¿realmente NO conviene hacer trampa?
# ============================================================

def run_simulation(num_tasks: int = 1000, miner_honest: bool = True):
    """
    Corre N tareas con un minero (honesto o tramposo) y muestra
    si en promedio le conviene jugar limpio o trampear.
    """
    print(f"\n{'#'*60}")
    print(f"# SIMULACIÓN: {num_tasks} tareas, minero {'HONESTO' if miner_honest else 'TRAMPOSO'}")
    print(f"{'#'*60}")

    miner = Miner(
        miner_id="miner_001",
        stake_nxs=1000.0,    # Stake inicial: 1000 NXS
        is_honest=miner_honest
    )

    payment_per_task = 10.0  # Cada tarea paga 10 NXS
    verification_prob = 0.10  # 10% de chance de verificación

    outcomes = {"paid": 0, "slashed": 0, "skipped": 0}

    for i in range(num_tasks):
        if miner.stake_nxs <= 0:
            # Sin stake no puede minar más
            outcomes["skipped"] = num_tasks - i
            break

        task = Task(
            task_id=f"task_{i:04d}",
            description=f"Tarea #{i}",
            input_data=f"datos_de_entrada_{i}",
            expected_compute_ms=1,  # Casi instantáneo para simulación
            payment_nxs=payment_per_task,
            verification_probability=verification_prob,
        )

        result = process_task(task, miner, verbose=False)

        if "paid" in result["outcome"]:
            outcomes["paid"] += 1
        elif "slashed" in result["outcome"]:
            outcomes["slashed"] += 1
            break  # Sin stake no sigue

    # Resultados
    print(f"\n📊 Resultados después de {num_tasks} tareas:")
    print(f"   Tareas pagadas: {outcomes['paid']}")
    print(f"   Slashing: {outcomes['slashed']}")
    print(f"   No ejecutadas (sin stake): {outcomes['skipped']}")
    print(f"   Ganancias totales: {miner.earnings:.2f} NXS")
    print(f"   Stake confiscado: {miner.total_slashed:.2f} NXS")
    print(f"   Balance neto: {miner.earnings - miner.total_slashed:.2f} NXS")

    return miner


# ============================================================
# Entry point
# ============================================================

def main():
    print("=" * 60)
    print("NEXUS — Prototipo de Verificación Commit-Reveal v0.1")
    print("=" * 60)

    # Demo 1: Un minero honesto procesando 3 tareas (verbose)
    print("\n\n🟢 DEMO 1: Minero honesto, 3 tareas verbose")
    miner_honest = Miner(miner_id="alice", stake_nxs=1000.0, is_honest=True)

    for i in range(3):
        task = Task(
            task_id=f"demo1_task_{i}",
            description=f"Inferencia simulada #{i}",
            input_data=f"prompt: explicame la pregunta {i}",
            expected_compute_ms=100,
            payment_nxs=5.0,
            verification_probability=0.30,  # 30% para ver más verificaciones en demo
        )
        process_task(task, miner_honest, verbose=True)

    print(f"\n  Alice ganó: {miner_honest.earnings:.2f} NXS")

    # Demo 2: Un minero tramposo
    print("\n\n🔴 DEMO 2: Minero tramposo, 3 tareas verbose")
    miner_cheater = Miner(miner_id="bob_cheater", stake_nxs=1000.0, is_honest=False)

    for i in range(3):
        task = Task(
            task_id=f"demo2_task_{i}",
            description=f"Inferencia simulada #{i}",
            input_data=f"prompt: tarea importante {i}",
            expected_compute_ms=100,
            payment_nxs=5.0,
            verification_probability=0.30,
        )
        process_task(task, miner_cheater, verbose=True)
        if miner_cheater.stake_nxs <= 0:
            print("\n  Bob se quedó sin stake. No puede seguir minando.")
            break

    print(f"\n  Bob ganó: {miner_cheater.earnings:.2f} NXS")
    print(f"  Bob perdió por slashing: {miner_cheater.total_slashed:.2f} NXS")

    # Simulación estadística grande
    print("\n\n" + "=" * 60)
    print("SIMULACIONES ESTADÍSTICAS (1000 tareas cada una)")
    print("=" * 60)

    honest_result = run_simulation(num_tasks=1000, miner_honest=True)
    cheater_result = run_simulation(num_tasks=1000, miner_honest=False)

    # Análisis final
    print("\n\n" + "=" * 60)
    print("📈 CONCLUSIÓN")
    print("=" * 60)
    print(f"Minero honesto: balance neto = {honest_result.earnings - honest_result.total_slashed:.2f} NXS")
    print(f"Minero tramposo: balance neto = {cheater_result.earnings - cheater_result.total_slashed:.2f} NXS")
    print()
    print("Esto demuestra empíricamente que el diseño económico hace")
    print("que la honestidad sea estrictamente más rentable que la trampa,")
    print("incluso cuando la verificación es solo probabilística (10%).")


if __name__ == "__main__":
    main()
