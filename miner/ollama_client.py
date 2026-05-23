"""
Cliente HTTP para Ollama.

Ollama corre como servicio local en el puerto 11434 y expone una API REST.
Este módulo es el "puente" entre el minero NEXUS y el runtime de IA.

Documentación oficial de la API:
https://github.com/ollama/ollama/blob/main/docs/api.md
"""

from __future__ import annotations
import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional


OLLAMA_DEFAULT_URL = "http://localhost:11434"


@dataclass
class InferenceResult:
    """Resultado de una inferencia."""
    text: str                    # El texto generado por el modelo
    model: str                   # Modelo usado
    prompt_tokens: int           # Tokens del prompt
    completion_tokens: int       # Tokens generados
    total_duration_ns: int       # Duración total en nanosegundos
    eval_duration_ns: int        # Solo el tiempo de generación

    @property
    def compute_time_ms(self) -> int:
        return self.total_duration_ns // 1_000_000

    @property
    def tokens_per_second(self) -> float:
        if self.eval_duration_ns == 0:
            return 0.0
        return self.completion_tokens / (self.eval_duration_ns / 1e9)


class OllamaError(Exception):
    """Error genérico hablando con Ollama."""
    pass


class OllamaClient:
    """Cliente minimalista para Ollama."""

    def __init__(self, base_url: str = OLLAMA_DEFAULT_URL, timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_alive(self) -> bool:
        """Verifica si Ollama está corriendo."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def list_models(self) -> list[str]:
        """Lista los modelos descargados localmente."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            raise OllamaError(f"No pude listar modelos: {e}")

    def generate(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.0,
        top_k: int = 1,
        top_p: float = 1.0,
        seed: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> InferenceResult:
        """
        Genera una respuesta del modelo.

        Para resultados DETERMINÍSTICOS (necesarios para commit-reveal con
        verificación byte-a-byte) usar:
            temperature=0.0, top_k=1, top_p=1.0, seed=algun_int_fijo

        Esto fuerza al modelo a elegir siempre el token más probable,
        descartando aleatoriedad.
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,  # esperar respuesta completa
            "options": {
                "temperature": temperature,
                "top_k": top_k,
                "top_p": top_p,
                "num_predict": max_tokens,
            },
        }

        if seed is not None:
            payload["options"]["seed"] = seed

        if system_prompt:
            payload["system"] = system_prompt

        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                result = json.loads(raw)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise OllamaError(f"HTTP {e.code}: {body}")
        except Exception as e:
            raise OllamaError(f"Error en request: {e}")

        if "response" not in result:
            raise OllamaError(f"Respuesta inesperada de Ollama: {result}")

        return InferenceResult(
            text=result["response"],
            model=result.get("model", model),
            prompt_tokens=result.get("prompt_eval_count", 0),
            completion_tokens=result.get("eval_count", 0),
            total_duration_ns=result.get("total_duration", 0),
            eval_duration_ns=result.get("eval_duration", 0),
        )


# ============================================================
# Demo / test manual
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Probando cliente Ollama")
    print("=" * 60)

    client = OllamaClient()

    if not client.is_alive():
        print("\n❌ Ollama no está corriendo.")
        print("   Arrancá Ollama y reintentá. En Windows debería iniciar")
        print("   automáticamente; podés probar con: ollama serve")
        exit(1)

    print("\n✓ Ollama está corriendo en", client.base_url)

    models = client.list_models()
    print(f"\n📦 Modelos descargados: {models}")

    if not models:
        print("\n⚠️  No hay modelos descargados.")
        print("   Ejecutá: ollama pull qwen2.5:7b")
        exit(1)

    # Usar el primer modelo disponible
    model = models[0]
    prompt = "¿Qué es Bitcoin? Respondé en una sola oración."

    print(f"\n🧠 Modelo: {model}")
    print(f"💬 Prompt: {prompt}")
    print("\n⏳ Generando (modo determinístico)...")

    start = time.time()
    result = client.generate(
        model=model,
        prompt=prompt,
        max_tokens=200,
        temperature=0.0,
        top_k=1,
        seed=42,
    )
    elapsed = time.time() - start

    print(f"\n📝 Respuesta:\n{result.text}")
    print(f"\n📊 Estadísticas:")
    print(f"   Tokens prompt: {result.prompt_tokens}")
    print(f"   Tokens generados: {result.completion_tokens}")
    print(f"   Tiempo total: {result.compute_time_ms} ms")
    print(f"   Velocidad: {result.tokens_per_second:.1f} tokens/segundo")
    print(f"   Wall clock: {elapsed:.2f} s")

    # Verificar determinismo: ejecutar 2 veces el mismo prompt
    print(f"\n🔬 Test de determinismo (2 inferencias idénticas)...")
    r1 = client.generate(model=model, prompt=prompt, max_tokens=100,
                          temperature=0.0, top_k=1, seed=42)
    r2 = client.generate(model=model, prompt=prompt, max_tokens=100,
                          temperature=0.0, top_k=1, seed=42)

    if r1.text == r2.text:
        print(f"   ✓ Determinismo confirmado: outputs idénticos")
    else:
        print(f"   ⚠️  Outputs distintos. Esto es problema para verificación EXACT.")
        print(f"      Output 1: {r1.text[:80]}...")
        print(f"      Output 2: {r2.text[:80]}...")
