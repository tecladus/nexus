"""
NEXUS Identity — identidad criptográfica de un nodo.

Cada nodo (minero, orquestador, validador) tiene un par de claves Ed25519.
La clave pública es su node_id (en formato hex). La privada firma sus mensajes.

Ed25519 es lo que usan Tor, SSH moderno, Bitcoin (versión schnorr), Solana, etc.
Es rápido (firma en ~50μs), las claves son chicas (32 bytes), y es seguro.

Para v0.3 implementamos lo mínimo: generar identidad, firmar, verificar.
En versiones futuras agregamos: rotación de claves, multi-firma, key derivation.
"""

from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, asdict

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


@dataclass
class NodeIdentity:
    """
    Identidad de un nodo NEXUS.

    - private_key_bytes: 32 bytes que firman mensajes (SECRETO)
    - public_key_bytes: 32 bytes que actúan como node_id (PÚBLICO)
    - node_id: representación hex de la public_key (legible)
    """
    _private_key: Ed25519PrivateKey
    _public_key: Ed25519PublicKey

    @property
    def node_id(self) -> str:
        """ID del nodo: hex de los 32 bytes de la public key."""
        raw = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return raw.hex()

    @property
    def short_id(self) -> str:
        """Versión corta del ID para mostrar en logs (primeros 12 chars)."""
        return self.node_id[:12]

    def sign(self, message: str | bytes) -> str:
        """Firma un mensaje. Devuelve la firma en hex."""
        if isinstance(message, str):
            message = message.encode("utf-8")
        signature = self._private_key.sign(message)
        return signature.hex()

    def save_to_file(self, path: Path) -> None:
        """
        Guarda la identidad en un archivo JSON.
        ⚠️ El archivo contiene la clave privada. Mantenelo seguro.
        """
        private_bytes = self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        data = {
            "node_id": self.node_id,
            "private_key_hex": private_bytes.hex(),
            "warning": "NO COMPARTAS ESTE ARCHIVO. Contiene tu clave privada.",
        }
        path.write_text(json.dumps(data, indent=2))
        # En Linux/Mac restringimos permisos. En Windows este chmod no hace nada
        # pero tampoco rompe.
        try:
            path.chmod(0o600)
        except Exception:
            pass

    @classmethod
    def generate(cls) -> NodeIdentity:
        """Genera una identidad nueva (par de claves aleatorio)."""
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        return cls(_private_key=private_key, _public_key=public_key)

    @classmethod
    def load_from_file(cls, path: Path) -> NodeIdentity:
        """Carga una identidad desde archivo JSON."""
        data = json.loads(path.read_text())
        private_bytes = bytes.fromhex(data["private_key_hex"])
        private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
        public_key = private_key.public_key()
        return cls(_private_key=private_key, _public_key=public_key)

    @classmethod
    def load_or_create(cls, path: Path) -> NodeIdentity:
        """
        Atajo: si existe el archivo, carga; si no, genera y guarda.
        Este es el patrón que van a usar todos los nodos al arrancar.
        """
        if path.exists():
            identity = cls.load_from_file(path)
            print(f"  🔑 Identidad cargada: {identity.short_id}...")
            return identity
        else:
            identity = cls.generate()
            identity.save_to_file(path)
            print(f"  🔑 Identidad NUEVA generada: {identity.short_id}...")
            print(f"     Guardada en: {path}")
            return identity


def verify_signature(node_id: str, message: str | bytes, signature_hex: str) -> bool:
    """
    Verifica que un mensaje fue firmado por el nodo con ese node_id.

    Cualquiera puede llamar esta función — no necesita la clave privada.
    Solo necesita: el ID del firmante, el mensaje original, y la firma.
    """
    if isinstance(message, str):
        message = message.encode("utf-8")

    try:
        public_bytes = bytes.fromhex(node_id)
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        signature = bytes.fromhex(signature_hex)
        public_key.verify(signature, message)
        return True
    except (InvalidSignature, ValueError):
        return False


# ============================================================
# Demo
# ============================================================

if __name__ == "__main__":
    import tempfile
    print("=" * 60)
    print("NEXUS Identity — demo")
    print("=" * 60)

    # 1. Generar una identidad nueva
    print("\n1️⃣  Generando identidad...")
    alice = NodeIdentity.generate()
    print(f"   Alice's node_id: {alice.node_id}")
    print(f"   (32 bytes = 64 caracteres hex)")
    print(f"   Short: {alice.short_id}")

    # 2. Firmar un mensaje
    print("\n2️⃣  Firmando un mensaje...")
    message = "Hola, este mensaje viene de Alice"
    signature = alice.sign(message)
    print(f"   Mensaje: \"{message}\"")
    print(f"   Firma: {signature[:32]}... ({len(signature)} chars hex)")

    # 3. Verificar la firma (cualquiera puede hacer esto)
    print("\n3️⃣  Verificando la firma...")
    is_valid = verify_signature(alice.node_id, message, signature)
    print(f"   ¿Firma válida? {is_valid} ✅" if is_valid else f"   ¿Firma válida? {is_valid} ❌")

    # 4. Intentar verificar con un mensaje DIFERENTE (debe fallar)
    print("\n4️⃣  Verificando con mensaje alterado (esperamos que falle)...")
    altered = "Hola, este mensaje viene de Alice... y le debe $1000"
    is_valid = verify_signature(alice.node_id, altered, signature)
    print(f"   ¿Firma válida con mensaje alterado? {is_valid}")
    print(f"   ✅ Correcto: la firma protege contra tampering" if not is_valid else "   ❌ ERROR")

    # 5. Persistencia
    print("\n5️⃣  Test de persistencia (guardar y cargar)...")
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = Path(f.name)

    alice.save_to_file(tmp_path)
    alice_loaded = NodeIdentity.load_from_file(tmp_path)
    print(f"   Original:  {alice.node_id}")
    print(f"   Cargada:   {alice_loaded.node_id}")
    print(f"   ¿Coinciden? {alice.node_id == alice_loaded.node_id}")

    # La firma de la identidad cargada debería verificar igual
    sig2 = alice_loaded.sign("test")
    print(f"   Firma cruzada válida: {verify_signature(alice.node_id, 'test', sig2)}")

    tmp_path.unlink()
    print("\n✓ Demo completo")
