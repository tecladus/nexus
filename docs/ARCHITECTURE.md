# NEXUS — Arquitectura Técnica

**Versión**: 0.1.0 (draft)
**Estado**: Diseño en evolución
**Última actualización**: Mayo 2026

---

## Tabla de contenidos

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Problema y motivación](#2-problema-y-motivación)
3. [Roles en la red](#3-roles-en-la-red)
4. [Tipos de trabajo soportados](#4-tipos-de-trabajo-soportados)
5. [Capa de verificación (el corazón)](#5-capa-de-verificación-el-corazón)
6. [Capa de consenso (blockchain)](#6-capa-de-consenso-blockchain)
7. [Capa de red P2P](#7-capa-de-red-p2p)
8. [Asignación de tareas](#8-asignación-de-tareas)
9. [Modelo económico (tokenomics)](#9-modelo-económico-tokenomics)
10. [Privacidad](#10-privacidad)
11. [Seguridad y vectores de ataque](#11-seguridad-y-vectores-de-ataque)
12. [Gobernanza](#12-gobernanza)
13. [Roadmap técnico](#13-roadmap-técnico)
14. [Decisiones abiertas](#14-decisiones-abiertas)

---

## 1. Resumen ejecutivo

NEXUS es una red descentralizada de cómputo donde:

- **Clientes** publican tareas computacionales y pagan en NXS
- **Mineros** ejecutan las tareas con su hardware y reciben NXS
- **Validadores** verifican que el trabajo se hizo correctamente
- **Orquestadores** coordinan la asignación y agregación
- Una **blockchain de Proof of Stake** registra estados, pagos y reputación

El valor del token NXS proviene de **demanda real de cómputo**, no de especulación. Su sostenibilidad depende de que el revenue por servicios reales supere a la emisión inflacionaria en un horizonte de 5-7 años.

---

## 2. Problema y motivación

### El problema técnico

Hoy el cómputo de IA está hipercentralizado en 4-5 hyperscalers (AWS, GCP, Azure, CoreWeave, Lambda). Esto genera:

- Precios artificialmente altos por falta de competencia
- Riesgo de censura (un hyperscaler puede negarte servicio)
- Subutilización masiva: millones de GPUs en hogares y oficinas usadas <20% del tiempo
- Barrera de entrada para investigadores y startups sin millones

### El problema económico de los proyectos cripto previos

Proyectos como Render, Akash, Bittensor abordaron pedazos, pero ninguno logró integrar:

1. **Verificación criptográfica robusta** (la mayoría dependen de reputación o stake puro)
2. **Tokenomics sostenibles** (muchos viven de la emisión inflacionaria)
3. **UX competitiva** con cloud tradicional
4. **Diversidad de cargas de trabajo** (no solo un tipo específico)

NEXUS intenta una síntesis que ataque las cuatro al mismo tiempo.

---

## 3. Roles en la red

### 3.1 Clientes (Requesters)

Cualquier entidad (persona, empresa, DAO) que necesita cómputo. Publican una **Task** especificando:

- `model_hash`: hash del modelo a ejecutar (Llama, Mistral, Stable Diffusion, etc.)
- `input_data`: payload de entrada (encriptado opcionalmente)
- `compute_requirements`: VRAM mínima, FLOPS estimados, deadline
- `payment`: cantidad de NXS bloqueada en escrow
- `verification_level`: "fast" (probabilístico), "redundant" (N=3), "tee" (enclave), "zk" (cuando esté maduro)

### 3.2 Mineros (Workers)

Operadores de hardware que ejecutan tareas. Para participar:

1. Hacen **stake mínimo** de `S_min` NXS (inicialmente, equivalente a ~$500 USD)
2. Publican su **capabilities profile** firmado:
   ```json
   {
     "gpu_model": "RTX 3060",
     "vram_gb": 12,
     "fp16_tflops": 25.6,
     "preloaded_models": ["llama-3.1-8b", "stable-diffusion-xl"],
     "bandwidth_mbps": 100,
     "uptime_score": 0.97
   }
   ```
3. Reciben tareas vía el orquestador, ejecutan, entregan resultado + hash compromiso

### 3.3 Validadores (Verifiers)

Subconjunto rotativo de mineros con stake elevado (`S_validator > 10 * S_min`). Responsabilidades:

- Re-ejecutar muestra aleatoria de tareas (~5-10%) para verificación profunda
- Resolver disputas cuando hay desacuerdo entre mineros redundantes
- Producir bloques en la cadena de consenso (PoS)

### 3.4 Orquestadores (Schedulers)

Nodos especializados que:

- Reciben tareas del cliente
- Las parten en sub-tareas si aplica
- Eligen mineros usando VRF (Verifiable Random Function)
- Agregan resultados parciales
- Publican el resultado final al cliente

Cobran fee de servicio (~2-5% del valor de la tarea). Son los más exigentes en infraestructura (alta disponibilidad, ancho de banda).

---

## 4. Tipos de trabajo soportados

### Fase 1 (launch): Inferencia de modelos open-source

**Por qué primero**: tarea más simple, modelos públicamente disponibles, verificación tratable.

Modelos soportados al inicio:
- LLMs: Llama 3.1 (8B, 70B), Mistral, Qwen 2.5, DeepSeek
- Imagen: Stable Diffusion XL, FLUX
- Audio: Whisper, MusicGen

### Fase 2 (mes 6+): Fine-tuning

LoRA y QLoRA sobre modelos base. Cliente provee dataset (encriptado opcional), recibe los pesos del adaptador.

### Fase 3 (mes 12+): Renderizado 3D

Integración con Blender, motores de game engines. Cada frame es una tarea independiente.

### Fase 4 (mes 18+): Cargas científicas

Plegamiento de proteínas (AlphaFold-derived), simulaciones Monte Carlo, computational chemistry.

### Fuera de scope (al menos por ahora)

- Entrenamiento de modelos foundation desde cero (requiere sincronización constante)
- Cargas con latencia <50ms (chatbots conversacionales en tiempo real)
- Procesamiento de video real-time

---

## 5. Capa de verificación (el corazón)

Este es el problema más difícil. La estrategia es **multi-modal**: distintos niveles de verificación para distintas necesidades.

### 5.1 Verificación probabilística con commit-reveal

**Para tareas chicas y de bajo riesgo** (inferencia simple, render frame).

**Protocolo**:

1. Minero recibe la tarea `T` con seed `s`
2. Minero ejecuta y obtiene resultado `R`
3. Minero publica `commit = H(R || nonce)` on-chain (donde `H` es SHA-256)
4. Tras timeout, minero revela `R` y `nonce`
5. **Con probabilidad p (ej. 0.08)**, un validador re-ejecuta `T` y compara
6. Si coincide → pago liberado
7. Si no coincide → slashing del 100% del stake del minero, reasignación

**Por qué funciona**:

Si el minero quiere hacer trampa (devolver basura), su valor esperado es:
- `EV(trampa) = (1-p) * pago - p * stake`
- Con `p=0.08` y `stake = 100 * pago` → `EV = 0.92 * pago - 8 * pago = -7.08 * pago`

Mentir tiene EV fuertemente negativo. La trampa solo es rentable si `stake < (1-p)/p * pago`, lo cual el protocolo previene exigiendo stake mínimo proporcional.

### 5.2 Redundancia N-de-M

**Para tareas medianas o críticas**.

Misma tarea va a **N mineros independientes** (elegidos por VRF para que no se coordinen). Resultados se comparan:

- Si todos coinciden → consensus, todos cobran (cada uno cobra `pago/N + bonus`)
- Si hay desacuerdo → se invoca al validador de desempate
- El minero que mintió pierde stake completo; el resto cobra normal + parte del slashing

**Para outputs determinísticos** (mismo seed → mismo resultado): coincidencia exacta byte-a-byte.

**Para outputs probabilísticos** (LLMs con temperatura > 0): se compara distribución de tokens vía métricas de similaridad semántica con threshold configurable.

### 5.3 Trusted Execution Environments (TEE)

**Para tareas con datos confidenciales o resultados de alto valor**.

Mineros con GPUs que soportan confidential computing (NVIDIA H100, próximas Blackwell) ejecutan en enclave. El hardware firma criptográficamente que el código ejecutado coincide con el solicitado.

**Trade-off**: requiere hardware específico (centralizante), pero ofrece garantía hardware-backed sin re-ejecución.

### 5.4 Zero-Knowledge Proofs (ZK)

**Estado**: experimental, no en launch inicial.

A medida que ZK-ML (zkSNARKs para inferencia) madure (proyectos como EZKL, Modulus, RISC Zero), NEXUS lo integrará como opción premium. Hoy genera pruebas 100-1000x más caras que el cómputo; se proyecta llegar a 10-50x en 2-3 años, lo que lo haría viable.

### 5.5 Tabla resumen

| Verificación | Costo overhead | Garantía | Latencia | Uso recomendado |
|---|---|---|---|---|
| Probabilística | ~10% | Económica | Baja | Inferencia simple |
| Redundancia N=3 | 200% | Económica fuerte | Media | Tareas medianas |
| TEE | ~5% | Hardware-backed | Baja | Datos sensibles |
| ZK (futuro) | 10-50x compute | Criptográfica | Alta | Máximo valor |

---

## 6. Capa de consenso (blockchain)

### 6.1 Decisión: cadena propia vs. L2

**Opción evaluada**: L2 sobre Ethereum (rollup).
**Opción elegida**: cadena propia con bridge a Ethereum para liquidez.

**Razones**:
- Necesitamos primitivas específicas (VRF integrado, oráculo de verificación de cómputo)
- Costos predecibles para el caso de uso
- Independencia frente a congestión de L1
- Bridge bidireccional garantiza interoperabilidad

### 6.2 Algoritmo de consenso: Proof of Stake delegado

**No confundir**: NEXUS usa PoS para consenso del **ledger**, y Proof of Useful Work para la **asignación de recompensas**. Son capas separadas.

Especificaciones:
- **Bloque cada 5 segundos**
- **Finalidad probabilística tras 12 bloques (~60 segundos)**
- **Validadores activos**: top 100 por stake delegado
- **Slashing por double-signing**: 100% stake
- **Slashing por inactividad**: 0.1% por epoch (24h)

### 6.3 Estructura de bloque

```
Block {
  header: {
    height: u64,
    parent_hash: [u8; 32],
    state_root: [u8; 32],
    timestamp: u64,
    validator: PublicKey,
    signature: Signature,
  },
  transactions: Vec<Transaction>,
  task_results: Vec<TaskResult>,  // específico de NEXUS
}
```

### 6.4 Transacciones soportadas

- `Transfer(to, amount)`: transferencia de NXS
- `Stake(amount, role)`: bloquear NXS como stake
- `Unstake(amount)`: liberar stake (con período de unbonding de 14 días)
- `PublishTask(spec, payment)`: cliente publica nueva tarea
- `CommitResult(task_id, hash)`: minero publica commit
- `RevealResult(task_id, result, nonce)`: minero revela resultado
- `Verify(task_id, valid)`: validador atestigua verificación
- `Slash(miner, reason)`: ejecuta slashing
- `Vote(proposal_id, choice)`: gobernanza

---

## 7. Capa de red P2P

### 7.1 Stack

- **libp2p** (mismo que IPFS, Ethereum, Polkadot) — modular y maduro
- **Transport**: QUIC primario, TCP fallback
- **Encryption**: Noise protocol
- **DHT**: Kademlia para discovery de peers

### 7.2 Tópicos pub/sub

- `/nexus/tasks/published`: nuevas tareas disponibles
- `/nexus/tasks/assignments`: asignaciones a mineros específicos
- `/nexus/results/commits`: commits de resultados
- `/nexus/results/reveals`: reveals de resultados
- `/nexus/verification/challenges`: validadores pidiendo re-ejecución
- `/nexus/consensus/blocks`: propagación de bloques

### 7.3 Transferencia de datos pesados

Modelos (50-200 GB) y outputs grandes **no van por gossip**. Estrategia:

- Modelos: almacenamiento descentralizado tipo Filecoin/Arweave, con cache local en mineros
- Datos de tarea: transferencia directa minero ↔ cliente via libp2p stream
- Resultados grandes: igual

Solo los **hashes y metadata** van on-chain.

---

## 8. Asignación de tareas

### 8.1 Matching: capabilities vs. requirements

Cuando llega una tarea:

1. Orquestador filtra mineros con `capabilities ⊇ requirements`
2. Aplica filtros adicionales: uptime > umbral, reputación > umbral, no slashed recientemente
3. Genera un random verificable (VRF) usando: `seed = H(task_id || block_hash)`
4. Selecciona los top N por proximidad al VRF output (probabilidad proporcional al stake y reputación)

### 8.2 VRF: por qué importa

Un random verificable previene:
- Que un orquestador favorezca a mineros amigos (sería detectable)
- Que mineros predigan qué tareas les tocarán (y pre-computen trampas)
- Coordinación entre mineros para colusión

Implementación: VRF basado en Ed25519 (rápido y estándar).

### 8.3 Precio: mecanismo de subasta inversa

El cliente publica `max_price`. Mineros que aceptan publican su `accept` con su precio (≤ max_price). El orquestador toma el primero válido por VRF.

En la práctica, los precios convergen al **costo marginal de electricidad + margen** del minero promedio. Esto es saludable: el mercado fija precios eficientes.

---

## 9. Modelo económico (tokenomics)

### 9.1 Suministro total y emisión

- **Supply máximo**: 1,000,000,000 NXS (mil millones)
- **Distribución inicial**:
  - 0% premine para fundadores/insiders (los fundadores reciben emisión vesteada)
  - 60% emisión a mineros y validadores a lo largo de 20 años
  - 20% reserva ecosistema (grants, integraciones, bug bounties) gobernada por DAO
  - 10% equipo fundador, vesting de 5 años, cliff de 1 año, con cláusulas de slashing si abandonan
  - 10% venta pública inicial (para financiar desarrollo) con vesting de 2 años para inversores

### 9.2 Curva de emisión

```
Año 1:  15% supply emitido (150M NXS) — alta para bootstrap
Año 2:  10% supply
Año 3:   7%
Año 4:   5%
Año 5:   4%
...
Año 20: ~1% (tail emission permanente para seguridad)
```

Función matemática: `emission(t) = E_0 * exp(-λt) + E_tail`
- `E_0 = 150M`, `λ = 0.35`, `E_tail = 5M/año`

### 9.3 Flujos de valor

**Entrada (NXS sale de circulación)**:
- Stakes bloqueados (no quemados pero ilíquidos)
- Quema del 1-2% de cada pago al miner
- Slashing por trampa

**Salida (NXS entra a circulación)**:
- Emisión de bloque distribuida entre mineros y validadores activos
- Unstaking tras período de unbonding

### 9.4 Distribución de pagos por tarea

Cuando un cliente paga `P` NXS por una tarea:
- **85%** → minero que ejecutó
- **5%** → validadores que verificaron
- **5%** → orquestador
- **3%** → tesoro de la DAO
- **2%** → **quemado** (presión deflacionaria)

### 9.5 La métrica clave a vigilar

**Ratio de sostenibilidad** = `revenue_pagos_clientes / emision_inflacionaria`

- Año 1: ~0.05 (5% — la red vive de subsidio)
- Año 3 objetivo: > 0.30
- Año 5 objetivo: > 1.00 (la red se sostiene sola)
- Año 10 objetivo: > 5.00 (red maduramente rentable)

Si esta métrica no progresa, el modelo está fallando y requiere intervención (vía gobernanza).

---

## 10. Privacidad

Niveles ofrecidos al cliente (paga más por más privacidad):

### 10.1 Nivel 0 — Estándar (gratis)

- Datos encriptados en tránsito (TLS sobre libp2p)
- Minero ve los datos en RAM durante ejecución
- **Apto para**: contenido público, prompts no sensibles

### 10.2 Nivel 1 — Federated (premium leve)

- Solo aplicable a fine-tuning
- Datos nunca salen del cliente
- Solo viajan gradientes encriptados
- **Apto para**: entrenar sobre datos propietarios sin exponerlos

### 10.3 Nivel 2 — TEE (premium medio)

- Tarea solo se asigna a mineros con hardware TEE atestiguado
- Datos encriptados incluso durante ejecución (memoria enclave)
- Minero no puede acceder ni con root
- **Apto para**: datos médicos, financieros, legales

### 10.4 Nivel 3 — FHE (futuro)

- Fully Homomorphic Encryption
- Cómputo sobre datos encriptados sin desencriptar
- Hoy 1000x más caro; viable cuando madure (5+ años)
- **Apto para**: máxima confidencialidad

---

## 11. Seguridad y vectores de ataque

### 11.1 Ataque: Sybil de mineros

**Vector**: atacante crea miles de identidades de mineros falsas para manipular asignación o consenso.

**Defensa**:
- Stake mínimo costoso (~$500 USD por identidad)
- Reputación que se gana lentamente (meses)
- Validation random no proporcional puramente al stake

### 11.2 Ataque: colusión entre mineros redundantes

**Vector**: en verificación N=3, los 3 mineros se ponen de acuerdo en devolver basura idéntica.

**Defensa**:
- Selección por VRF impredecible
- Probabilidad de que 3 mineros random se coordinen es ~0 en red grande
- Validación profunda periódica adicional incluso si los 3 coinciden

### 11.3 Ataque: cliente no paga

**Vector**: cliente recibe el resultado y reverta el pago.

**Defensa**:
- Pago en escrow on-chain ANTES de asignar la tarea
- Cliente no puede retirar hasta que se complete la tarea o expire el deadline

### 11.4 Ataque: cliente declara incorrectamente que el resultado es malo

**Vector**: cliente recibe resultado válido pero reclama que es inválido para no pagar.

**Defensa**:
- Cliente no decide la validez. La decide el validador del protocolo.
- Si cliente disputa, paga un fee adicional para forzar re-verificación
- Si la re-verificación confirma que el resultado era válido, cliente pierde el fee

### 11.5 Ataque: 51% en consensus

**Vector**: atacante acumula >50% del stake total y controla la cadena.

**Defensa**:
- Distribución amplia incentivada por emisión
- Slashing severo por double-signing
- Social slashing (fork manual) como último recurso ante ataque masivo

### 11.6 Ataque: pool centralization

**Vector**: 2-3 pools concentran la mayoría del hashrate de mineros.

**Defensa**:
- A diferencia de Bitcoin, no hay "pools" como tales; cada minero es identidad propia con stake
- Pero pueden formarse "operadores" que controlan muchos mineros (similar a Lido en Ethereum)
- Defensa parcial: caps de stake delegado a un mismo operador, aplicado on-chain

### 11.7 Ataque: malware en el cliente minero

**Vector**: alguien publica una versión modificada del cliente minero que roba claves o stake.

**Defensa**:
- Builds reproducibles, hashes publicados, firmados por la fundación
- Auditorías regulares
- Encouragement a usar la versión oficial; nada de "miner pro v2" descargado de cualquier lado

---

## 12. Gobernanza

### 12.1 Filosofía

Gobernanza descentralizada pero **práctica**. La descentralización pura suele resultar en parálisis o captura. NEXUS adopta un modelo híbrido:

### 12.2 Estructura

- **NXS Holders**: votan en propuestas mayores (cambio de protocolo, treasury allocations grandes)
- **Validators**: votan en parámetros operacionales (slashing thresholds, fees, etc.)
- **Foundation Council**: 5-7 personas elegidas, ejecutan decisiones técnicas urgentes (security patches), pueden ser destituidas por NXS holders
- **Disputed protocol forks**: requieren mayoría calificada (>66%) de stake

### 12.3 Quorum y mayorías

- Cambios menores: 33% participación, 50% favor
- Cambios mayores: 50% participación, 60% favor
- Cambios constitucionales: 66% participación, 75% favor

---

## 13. Roadmap técnico

### Q1-Q2 2026: Diseño y prototipos

- ✅ Arquitectura técnica (este documento)
- ⬜ Prototipo del minero (Python, single-node)
- ⬜ Prototipo del orquestador
- ⬜ Smart contracts del escrow (Solidity, testnet)
- ⬜ Whitepaper público v1.0

### Q3-Q4 2026: Devnet

- ⬜ Devnet pública con 10-50 mineros invited
- ⬜ Cliente Rust performante reemplazando el Python
- ⬜ Auditoría de seguridad inicial
- ⬜ Bug bounty público

### Q1-Q2 2027: Testnet

- ⬜ Testnet abierta con incentivos en token de prueba
- ⬜ Integración con primer modelo LLM completo (Llama 3.1 70B)
- ⬜ Stress tests con cargas reales
- ⬜ Segunda auditoría de seguridad

### Q3 2027+: Mainnet

- ⬜ Mainnet launch
- ⬜ Bridge a Ethereum
- ⬜ Integraciones con wallets principales
- ⬜ Frontends para clientes y mineros

---

## 14. Decisiones abiertas

Estas son las preguntas técnicas que aún requieren definición:

1. **¿VRF basado en BLS o Ed25519?** BLS permite aggregation (más eficiente), Ed25519 es más simple. Tentativo: Ed25519 para v1.
2. **¿Cómo manejamos modelos privados?** Si un cliente quiere usar su modelo propietario, ¿cómo previene que el minero lo robe? Posibles: solo TEE, splitting del modelo, model watermarking.
3. **¿Qué métricas exactas para comparación de outputs probabilísticos (LLMs)?** Cosine similarity de embeddings parece prometedor pero no se ha validado a escala.
4. **¿Mecanismo de governance del oráculo de precios?** Para el escrow, necesitamos saber el precio USD-NXS para calcular stakes mínimos. Chainlink-style oracle o consensus interno.
5. **¿Soporte multi-cadena para escrow?** ¿Aceptar USDC, ETH directamente sin convertir? Trade-off entre UX y complejidad.

---

## Anexo A: Glosario

- **NXS**: token nativo de la red NEXUS
- **Stake**: NXS bloqueados como garantía
- **Slashing**: confiscación de stake por mal comportamiento
- **Commit-reveal**: protocolo donde primero se publica el hash, luego el valor
- **VRF**: Verifiable Random Function — random verificable por cualquiera
- **TEE**: Trusted Execution Environment — enclave de hardware seguro
- **ZK proof**: zero-knowledge proof — prueba criptográfica sin revelar el dato
- **PoS**: Proof of Stake
- **DAO**: Decentralized Autonomous Organization
