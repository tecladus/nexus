"""
NEXUS Client — script para publicar tareas al orquestador.

Ejemplo de uso:
    python client/submit.py "Explicá qué es Bitcoin"
    python client/submit.py "Listá 5 países" --model qwen2.5:7b --payment 3.0
    python client/submit.py --interactive
"""

from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from common.identity import NodeIdentity


def submit_one(
    orchestrator: str,
    prompt: str,
    model: str,
    payment: float,
    max_tokens: int,
    identity: NodeIdentity,
    wait_for_result: bool = True,
):
    """Envía una tarea y opcionalmente espera el resultado."""

    body = {
        "client_id": identity.node_id,
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "payment_nxs": payment,
        "verification_probability": 0.20,
    }

    print(f"\n📤 Enviando tarea al orquestador {orchestrator}...")
    print(f"   Modelo: {model}")
    print(f"   Prompt: \"{prompt}\"")
    print(f"   Pago: {payment} NXS")

    try:
        r = httpx.post(f"{orchestrator}/tasks/submit", json=body, timeout=10.0)
    except httpx.RequestError as e:
        print(f"❌ No pude contactar al orquestador: {e}")
        print(f"   ¿Está corriendo? Probá: python orchestrator/server.py")
        return None

    if r.status_code != 200:
        print(f"❌ El orquestador respondió {r.status_code}: {r.text}")
        return None

    data = r.json()
    task_id = data["task_id"]
    print(f"✓ Tarea publicada: {task_id}")

    if not wait_for_result:
        return task_id

    # Polling: esperar a que esté completa
    print(f"\n⏳ Esperando resultado...")
    start = time.time()
    last_status = None

    while time.time() - start < 120:  # timeout 2 minutos
        time.sleep(1.0)
        try:
            r = httpx.get(f"{orchestrator}/tasks/{task_id}", timeout=5.0)
            if r.status_code != 200:
                continue
            task = r.json()
            status = task.get("status")

            if status != last_status:
                print(f"   [{int(time.time() - start)}s] Status: {status}")
                last_status = status

            if status in ("paid", "verified_paid", "fraud_detected",
                           "no_miners_available", "miner_unreachable"):
                print(f"\n{'=' * 60}")
                print(f"RESULTADO FINAL ({status})")
                print(f"{'=' * 60}")

                if task.get("reveal"):
                    print(f"\n📝 Resultado:\n{task['reveal']['result']}")
                    print(f"\n📊 Metadata:")
                    meta = task['reveal'].get('metadata', {})
                    for k, v in meta.items():
                        print(f"   {k}: {v}")

                if task.get("commit"):
                    print(f"\n🔒 Commit hash: {task['commit']['hash'][:32]}...")

                print(f"\n🏷️  Asignado a minero: {task.get('assigned_miner', 'N/A')[:24]}...")
                return task
        except httpx.RequestError:
            pass

    print(f"\n⚠️  Timeout esperando la tarea {task_id}")
    return None


def main():
    parser = argparse.ArgumentParser(description="NEXUS Client")
    parser.add_argument("prompt", nargs="*", help="El prompt a enviar")
    parser.add_argument("--orchestrator", default="http://127.0.0.1:7000")
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--payment", type=float, default=2.0, help="NXS a pagar")
    parser.add_argument("--max-tokens", type=int, default=200)
    parser.add_argument("--identity-file", default="client_identity.json")
    parser.add_argument("--interactive", action="store_true",
                        help="Modo interactivo: pedir prompts en bucle")
    args = parser.parse_args()

    print("=" * 60)
    print("NEXUS Client v0.3")
    print("=" * 60)

    identity = NodeIdentity.load_or_create(Path(args.identity_file))

    # Verificar que el orquestador está alive
    try:
        r = httpx.get(f"{args.orchestrator}/", timeout=5.0)
        info = r.json()
        print(f"\n📡 Orquestador: {info.get('name')} v{info.get('version')}")
        print(f"   Mineros activos: {info.get('miners_active')}")
        if info.get('miners_active', 0) == 0:
            print(f"\n⚠️  No hay mineros activos en este orquestador.")
            print(f"   Arrancá un minero: python miner/server.py")
            return
    except httpx.RequestError:
        print(f"\n❌ No pude contactar al orquestador en {args.orchestrator}")
        return

    if args.interactive:
        print("\n💬 Modo interactivo. Escribí prompts; 'exit' para salir.\n")
        while True:
            try:
                prompt = input("Prompt> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not prompt or prompt.lower() in ("exit", "quit"):
                break
            submit_one(args.orchestrator, prompt, args.model, args.payment,
                        args.max_tokens, identity)
    else:
        if not args.prompt:
            print("\n❌ Falta el prompt. Ejemplo:")
            print(f"   python client/submit.py \"Explicá qué es Bitcoin\"")
            return
        prompt = " ".join(args.prompt)
        submit_one(args.orchestrator, prompt, args.model, args.payment,
                    args.max_tokens, identity)


if __name__ == "__main__":
    main()
