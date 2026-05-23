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
├── miner/             # Cliente minero (Python)
├── orchestrator/      # Nodo orquestador (Python)
├── contracts/         # Smart contracts (Solidity)
├── tests/             # Tests automatizados
└── scripts/           # Utilidades varias
```

## Roadmap

- [x] Sesión 1: Arquitectura técnica + setup inicial
- [ ] Sesión 2: Prototipo del minero funcional
- [ ] Sesión 3: Orquestador + comunicación P2P
- [ ] Sesión 4: Smart contracts en testnet
- [ ] Sesión 5: Integración end-to-end
- [ ] Sesión 6+: Whitepaper, web, comunidad

## Licencia

MIT — ver [LICENSE](LICENSE)

## Disclaimer

Este es un proyecto experimental de investigación y desarrollo. No constituye consejo financiero. Las criptomonedas son volátiles y de alto riesgo. Antes de lanzar cualquier token, se requiere asesoramiento legal en la jurisdicción correspondiente.
