"""
Tests del minero NEXUS.

Ejecutar:
    pytest tests/ -v

Algunos tests requieren Ollama corriendo. Se skipean si no está disponible.
"""

import sys
import tempfile
from pathlib import Path

# Agregar el módulo miner al path
sys.path.insert(0, str(Path(__file__).parent.parent / "miner"))

import pytest
from protocol import (
    TaskMessage, CommitMessage, RevealMessage,
    TaskKind, VerificationLevel, DeterminismMode,
    LLMInferenceSpec, PROTOCOL_VERSION,
)
from executor import (
    generate_commit_hash, hash_sha256, derive_seed,
)
from storage import MinerDB
from ollama_client import OllamaClient
from dataclasses import asdict


# ============================================================
# Tests de criptografía / commit-reveal
# ============================================================

class TestCommitReveal:

    def test_hash_is_deterministic(self):
        """SHA-256 sobre el mismo input siempre da el mismo hash."""
        assert hash_sha256("hola") == hash_sha256("hola")

    def test_hash_changes_with_input(self):
        """Inputs distintos → hashes distintos."""
        assert hash_sha256("hola") != hash_sha256("Hola")

    def test_commit_includes_nonce(self):
        """El commit debe depender del nonce, no solo del resultado."""
        result = "respuesta fija"
        c1 = generate_commit_hash(result, "nonce_1")
        c2 = generate_commit_hash(result, "nonce_2")
        assert c1 != c2

    def test_commit_verifies_correct_reveal(self):
        """Un reveal correcto reproduce el commit."""
        result = "el resultado"
        nonce = "abc123"
        commit = generate_commit_hash(result, nonce)
        # Verificación: recomputar commit con el reveal
        assert generate_commit_hash(result, nonce) == commit

    def test_commit_rejects_tampered_reveal(self):
        """Si cambia el resultado, el commit no coincide."""
        nonce = "abc123"
        original_commit = generate_commit_hash("respuesta_A", nonce)
        # Intento de fraude: cambiar el resultado
        forged_commit = generate_commit_hash("respuesta_B", nonce)
        assert original_commit != forged_commit


class TestSeedDerivation:

    def test_same_task_id_same_seed(self):
        """Determinismo: mismo task_id → mismo seed."""
        assert derive_seed("task_001") == derive_seed("task_001")

    def test_different_task_ids_different_seeds(self):
        """task_ids distintos → seeds distintos (con alta probabilidad)."""
        assert derive_seed("task_001") != derive_seed("task_002")

    def test_seed_is_valid_int(self):
        """El seed debe ser un int positivo dentro del rango de Ollama."""
        seed = derive_seed("any_task_id")
        assert isinstance(seed, int)
        assert 0 < seed < 2**31  # int positivo de 32 bits


# ============================================================
# Tests de schemas del protocolo
# ============================================================

class TestProtocol:

    def test_task_message_serialization(self):
        """Una TaskMessage se serializa a JSON válido."""
        spec = LLMInferenceSpec(model="qwen2.5:7b", prompt="test")
        task = TaskMessage(
            task_id="t1",
            client_id="c1",
            kind=TaskKind.LLM_INFERENCE,
            spec=asdict(spec),
            payment_nxs=5.0,
        )
        json_str = task.to_json()
        assert PROTOCOL_VERSION in json_str
        assert "qwen2.5:7b" in json_str
        assert "llm_inference" in json_str

    def test_commit_message_has_required_fields(self):
        commit = CommitMessage(
            task_id="t1",
            miner_id="m1",
            commit_hash="abc",
            compute_time_ms=100,
        )
        d = commit.to_dict()
        assert "protocol_version" in d
        assert "timestamp" in d
        assert d["commit_hash"] == "abc"


# ============================================================
# Tests de persistencia
# ============================================================

class TestStorage:

    @pytest.fixture
    def db(self):
        """DB temporal por test."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = Path(f.name)
        db = MinerDB(tmp_path)
        yield db
        tmp_path.unlink()

    def test_record_full_task_flow(self, db):
        """Flujo completo: received → committed → revealed → paid."""
        db.record_task_received("t1", "alice", "llm_inference",
                                  {"model": "qwen"}, 5.0)
        task = db.get_task("t1")
        assert task["status"] == "received"

        db.record_commit("t1", "hash123", 100)
        task = db.get_task("t1")
        assert task["status"] == "committed"
        assert task["commit_hash"] == "hash123"

        db.record_reveal("t1", "resultado", "nonce", {"tokens": 10})
        task = db.get_task("t1")
        assert task["status"] == "revealed"

        db.record_payment("t1", "miner1", 5.0)
        task = db.get_task("t1")
        assert task["status"] == "paid"

    def test_stats_accumulation(self, db):
        """Los stats acumulan correctamente."""
        db.record_task_received("t1", "alice", "llm_inference", {}, 5.0)
        db.record_payment("t1", "m1", 5.0)

        db.record_task_received("t2", "alice", "llm_inference", {}, 3.0)
        db.record_payment("t2", "m1", 3.0)

        stats = db.get_stats("m1")
        assert stats["total_tasks_paid"] == 2
        assert stats["total_earned_nxs"] == 8.0

    def test_slashing(self, db):
        """Slashing se registra correctamente."""
        db.record_task_received("t1", "alice", "llm_inference", {}, 5.0)
        db.record_slashing("t1", "m1", 1000.0, "test reason")

        stats = db.get_stats("m1")
        assert stats["total_tasks_slashed"] == 1
        assert stats["total_slashed_nxs"] == 1000.0


# ============================================================
# Tests de integración (requieren Ollama)
# ============================================================

@pytest.fixture(scope="module")
def ollama():
    """Cliente Ollama, skipea tests si no está corriendo."""
    client = OllamaClient()
    if not client.is_alive():
        pytest.skip("Ollama no está corriendo")
    if not client.list_models():
        pytest.skip("No hay modelos descargados")
    return client


class TestOllamaIntegration:

    def test_ollama_alive(self, ollama):
        assert ollama.is_alive()

    def test_can_list_models(self, ollama):
        models = ollama.list_models()
        assert len(models) > 0

    def test_deterministic_inference(self, ollama):
        """Mismo prompt + mismo seed → mismo output."""
        model = ollama.list_models()[0]
        r1 = ollama.generate(
            model=model, prompt="Hola", max_tokens=20,
            temperature=0.0, top_k=1, seed=42,
        )
        r2 = ollama.generate(
            model=model, prompt="Hola", max_tokens=20,
            temperature=0.0, top_k=1, seed=42,
        )
        assert r1.text == r2.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
