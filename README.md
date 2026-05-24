# NEXUS

**NEural eXchange Utility System** — una red descentralizada donde GPUs y CPUs ociosas se conectan para ejecutar trabajo computacional útil (inferencia de IA, fine-tuning, renderizado), y los operadores reciben recompensas en el token nativo NXS.

> ⚠️ **Estado actual**: Diseño y prototipo temprano. Esto no es un producto de producción. No invierta dinero real ni use con datos sensibles hasta auditoría completa.

## Idea central

En vez de gastar electricidad calculando hashes inútiles (Bitcoin) o bloqueando capital (Proof of Stake), NEXUS mina haciendo **trabajo computacional que alguien necesita**:

- Inferencia de modelos de IA (correr LLMs, modelos de imagen, etc.)
- Fine-tuning sobre modelos base
- Renderizado 3D distribuido
- Simulaciones científicas paralelizables

## Cómo funciona (alto nivel)

```
Cliente → publica tarea + paga en NXS (escrow)
       ↓
Orquestador → asigna a minero(s) elegibles
       ↓
Minero → ejecuta el trabajo en su GPU/CPU
       ↓
Validador → verifica probabilísticamente el resultado
       ↓
Smart contract → libera pago al minero (o aplica slashing si tramposeó)
```

## Por qué podría funcionar

- **Demanda real y creciente**: el mercado de inferencia de IA crece exponencialmente
- **Oferta ociosa enorme**: millones de GPUs gamer subutilizadas
- **Tecnología madurando**: ZK proofs, TEEs, federated learning ya son viables
- **Precedente parcial**: Bittensor, Akash, Render validaron pedazos del problema

## Estructura del repo

```
nexus/
├── docs/              # Documentación técnica
│   └── ARCHITECTURE.md  # El diseño completo (LEER PRIMERO)
├── common/            # Módulos compartidos (identidad Ed25519)
├── miner/             # Cliente minero (Python + FastAPI)
├── orchestrator/      # Nodo orquestador (Python + FastAPI)
├── client/            # Script para enviar tareas
├── contracts/         # Smart contracts (Solidity, próximamente)
├── tests/             # Tests automatizados (17 tests)
└── scripts/           # Utilidades varias
```

## Cómo correr la red completa

Necesitás 3 terminales abiertas:

**Terminal 1 — Orquestador**:
```bash
python orchestrator/server.py --port 7000
```

**Terminal 2 — Minero** (requiere Ollama corriendo):
```bash
python miner/server.py --port 7100 --orchestrator http://127.0.0.1:7000
```

**Terminal 3 — Cliente** (publica una tarea):
```bash
python client/submit.py "Explicá qué es Bitcoin en 3 oraciones"
```

Mirá cómo el cliente espera el resultado, mientras en la terminal 1 ves el orquestador asignando, y en la terminal 2 ves el minero ejecutando.

## Roadmap

- [x] Sesión 1: Arquitectura técnica + setup inicial
- [x] Sesión 2: Prototipo del minero funcional con inferencia de IA real
- [x] Sesión 3: Orquestador + comunicación HTTP entre nodos (P2P real)
- [ ] Sesión 4: Smart contracts en testnet
- [ ] Sesión 5: Integración end-to-end
- [ ] Sesión 6+: Whitepaper, web, comunidad

## Licencia

MIT — ver [LICENSE](LICENSE)

## Disclaimer

Este es un proyecto experimental de investigación y desarrollo. No constituye consejo financiero. Las criptomonedas son volátiles y de alto riesgo. Antes de lanzar cualquier token, se requiere asesoramiento legal en la jurisdicción correspondiente.
