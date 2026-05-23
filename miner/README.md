# NEXUS Miner

Cliente minero del protocolo NEXUS. Recibe tareas de la red, las ejecuta en hardware local (GPU/CPU), y publica resultados con verificación criptográfica.

## Estado actual

**v0.1 — Prototipo educativo de commit-reveal**

El archivo `miner_demo.py` demuestra el corazón del protocolo: cómo un minero ejecuta una tarea, publica un commit criptográfico del resultado, y se enfrenta a verificación probabilística que hace que la honestidad sea estrictamente más rentable que la trampa.

## Ejecutar la demo

```bash
python3 miner_demo.py
```

Vas a ver:

1. **Demo 1**: Un minero honesto procesando 3 tareas detalladamente
2. **Demo 2**: Un minero tramposo siendo descubierto y perdiendo su stake
3. **Simulación estadística**: 1000 tareas cada uno comparando ambos comportamientos

## Lo que demuestra

El output final muestra que:

- Minero honesto: balance positivo proporcional al trabajo hecho
- Minero tramposo: balance NEGATIVO porque el slashing > ganancias por trampa

Esto valida empíricamente el diseño económico descrito en [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md), sección 5.1.

## Próximas versiones

- v0.2: Integración con un modelo LLM real (Llama 3.1 8B) corriendo localmente
- v0.3: Comunicación P2P con orquestador (libp2p)
- v0.4: Cliente Rust de alta performance
