# NEXUS Miner

Cliente minero del protocolo NEXUS. Recibe tareas de la red, las ejecuta en hardware local (GPU/CPU), y publica resultados con verificación criptográfica.

## Estado actual

**v0.2 — Inferencia real con Ollama**

Ya no es simulación: el minero ejecuta inferencia real de LLMs en tu GPU local usando Ollama como runtime. El protocolo commit-reveal funciona end-to-end con outputs reales.

## Módulos

| Archivo | Qué hace |
|---|---|
| `protocol.py` | Schemas de mensajes del protocolo (TaskMessage, CommitMessage, etc.) |
| `ollama_client.py` | Cliente HTTP para Ollama (sin dependencias externas) |
| `executor.py` | Ejecuta tareas, genera commits, maneja determinismo |
| `storage.py` | Persistencia local con SQLite |
| `main.py` | Punto de entrada que integra todo |

## Requisitos

1. **Python 3.10+**
2. **Ollama** corriendo en `localhost:11434` ([instalar](https://ollama.com/download))
3. **Al menos un modelo descargado**, recomendado:
   ```bash
   ollama pull qwen2.5:7b
   ```

## Ejecutar

**Demo del ciclo completo** (recibir tarea → ejecutar → commit → reveal → verify → pago):
```bash
python3 main.py
```

**Benchmark de tu hardware**:
```bash
python3 main.py --benchmark
```

**Inspeccionar la base de datos**:
```bash
sqlite3 nexus_miner.db
> SELECT task_id, status, payment_nxs FROM tasks ORDER BY received_at DESC;
> SELECT * FROM miner_stats;
```

## Tests

```bash
pip install pytest
pytest tests/ -v
```

## Cómo funciona el determinismo

Los LLMs son no-determinísticos por defecto. Para que dos mineros lleguen al
mismo output (necesario para verificación byte-a-byte), forzamos:

- `temperature = 0.0` (sin aleatoriedad)
- `top_k = 1` (siempre el token más probable)
- `seed = sha256(task_id)[:8]` (mismo seed para todos los mineros de la misma tarea)

Esto se aplica en modo `EXACT`. En modo `SEMANTIC` (futuro), permitimos
variación y comparamos por similaridad de embeddings.

## Próximas versiones

- v0.3: Comunicación P2P con orquestador (libp2p)
- v0.4: Cliente Rust de alta performance
- v0.5: Integración con smart contracts en testnet
