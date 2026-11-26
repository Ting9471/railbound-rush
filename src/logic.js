export const LANES = [-3.4, 0, 3.4];
export const PLAYER_Z = 4;
export const GROUND_Y = 0;

export function runCameraLayout(aspect, fov = 58) {
  // Fit every lane, then anchor the runner's feet at 98% of the screen height.
  const halfFov = Math.tan(fov * Math.PI / 360);
  const distance = Math.max(10, 5.2 / (Math.max(0.1, aspect) * halfFov));
  const height = 0.56 * distance;
  const pitch = Math.atan2(height - GROUND_Y, distance) - Math.atan(0.96 * halfFov);
  return { height, z: PLAYER_Z + distance, targetY: height - 2 * distance * Math.tan(pitch), targetZ: PLAYER_Z - distance };
}

export const CHARACTERS = [
  { id: "classic", name: "经典", file: "runner.glb", animation: "nodes", scale: 0.82 },
  { id: "ch09", name: "蒂姆", file: "ch09.glb", animation: "clips", scale: 1.12 },
  { id: "cat", name: "猫猫跑者", file: "cat_guy_thing.glb", animation: "clips", scale: 1.12 }
];

export async function loadModelData(url, { signal, onProgress, timeoutMs = 45000 } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort(signal.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(() => controller.abort(new Error("模型下载超时，请重试或切换其他跑者")), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`模型下载失败（HTTP ${response.status}）`);
    if (!response.body) return await response.arrayBuffer();
    const reader = response.body.getReader(), chunks = [];
    let loaded = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);loaded += value.byteLength;
        onProgress?.(loaded);
      }
    } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(loaded);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset);offset += chunk.byteLength; }
    return bytes.buffer;
  } catch (error) {
    if (controller.signal.aborted) throw controller.signal.reason;
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export async function withTimeout(promise, timeoutMs, message) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), timeoutMs);
    })]);
  } finally { clearTimeout(timer); }
}

export function resolveCharacter(query, saved) {
  const known = id => CHARACTERS.some(character => character.id === id);
  return known(query) ? query : known(saved) ? saved : "cat";
}

export function cycleCharacter(id, direction) {
  const index = Math.max(0, CHARACTERS.findIndex(character => character.id === id));
  return CHARACTERS[((index + direction) % CHARACTERS.length + CHARACTERS.length) % CHARACTERS.length].id;
}

export function runnerAnimationState(player, phase) {
  if (phase !== "running" || player.dead) return "Idle";
  if (!player.support) return "Jump";
  return player.sliding ? "Slide" : "Run";
}

export function jumpAnimationPhase(player, landingY = GROUND_Y) {
  if (player.vy > 0) return Math.max(0, Math.min(0.5, 0.5 * (1 - player.vy / 11.2)));
  const height = Math.max(0, player.y - landingY);
  const impactSpeed = Math.sqrt(player.vy * player.vy + 2 * 19.5 * height);
  return impactSpeed > 0 ? 0.5 + 0.5 * Math.min(1, -player.vy / impactSpeed) : 1;
}

export function clampLane(index) {
  return Math.max(0, Math.min(2, index));
}

export function springStep(position, velocity, target, dt, frequency = 12) {
  const damping = 2 * frequency;
  const acceleration = frequency * frequency * (target - position) - damping * velocity;
  velocity += acceleration * dt;
  position += velocity * dt;
  if (Math.abs(target - position) < 0.001 && Math.abs(velocity) < 0.01) return { position: target, velocity: 0 };
  return { position, velocity };
}

export function overlaps(a, b) {
  return a.minX <= b.maxX && a.maxX >= b.minX && a.minY <= b.maxY && a.maxY >= b.minY && a.minZ <= b.maxZ && a.maxZ >= b.minZ;
}

export function playerBounds(player) {
  const height = player.sliding ? 0.82 : 1.82;
  return {
    minX: player.x - 0.38, maxX: player.x + 0.38,
    minY: player.y, maxY: player.y + height,
    minZ: PLAYER_Z - 0.34, maxZ: PLAYER_Z + 0.34
  };
}

export function obstacleBounds(entity) {
  const x = LANES[entity.lane];
  if (entity.kind === "low") return { minX: x - 1.25, maxX: x + 1.25, minY: entity.baseY, maxY: entity.baseY + 0.9, minZ: entity.z - 0.35, maxZ: entity.z + 0.35 };
  if (entity.kind === "high") return { minX: x - 1.3, maxX: x + 1.3, minY: entity.baseY + 0.95, maxY: entity.baseY + 5, minZ: entity.z - 0.38, maxZ: entity.z + 0.38 };
  return null;
}

export function trainBodyBounds(train) {
  const x = LANES[train.lane];
  return { minX: x - 1.34, maxX: x + 1.34, minY: 0, maxY: train.roofY, minZ: train.z - train.length / 2, maxZ: train.z + train.length / 2 };
}

export function canLandOnRoof(player, previousY, train) {
  const body = trainBodyBounds(train);
  const xOverlap = player.x + 0.38 >= body.minX && player.x - 0.38 <= body.maxX;
  const zOverlap = PLAYER_Z + 0.34 >= body.minZ && PLAYER_Z - 0.34 <= body.maxZ;
  return player.vy <= 0 && previousY >= train.roofY && player.y <= train.roofY && xOverlap && zOverlap;
}

export function coinCollected(player, coin) {
  const dx = player.x - LANES[coin.lane];
  const dy = player.y + (player.sliding ? 0.45 : 0.95) - coin.y;
  const dz = PLAYER_Z - coin.z;
  return dx * dx + dy * dy + dz * dz < 0.78 * 0.78;
}

export function wrapChunkZ(z, delta, chunkLength, chunkCount, threshold) {
  let next = z + delta;
  const span = chunkLength * chunkCount;
  while (next > threshold) next -= span;
  return next;
}

export function mulberry32(seed) {
  return function random() {
    let t = seed += 0x6D2B79F5;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

export const PATTERNS = [
  { id: "low-hop", length: 30, placements: [{ kind: "low", lane: 1, at: 18 }, { kind: "coinLine", lane: 0, at: 12, count: 5 }] },
  { id: "high-slide", length: 30, placements: [{ kind: "high", lane: 1, at: 18 }, { kind: "coinLine", lane: 1, at: 12, count: 5 }] },
  { id: "open-lane", length: 34, placements: [{ kind: "train", lane: 0, at: 22, length: 13 }, { kind: "train", lane: 2, at: 23, length: 13 }, { kind: "coinLine", lane: 1, at: 12, count: 7 }] },
  { id: "roof-run", length: 48, placements: [{ kind: "train", lane: 1, at: 28, length: 25 }, { kind: "coinArc", lane: 1, at: 12, count: 12 }] },
  { id: "choice", length: 34, placements: [{ kind: "low", lane: 0, at: 19 }, { kind: "high", lane: 2, at: 20 }, { kind: "coinLine", lane: 1, at: 12, count: 6 }] }
];
