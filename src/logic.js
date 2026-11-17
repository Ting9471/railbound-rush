export const LANES = [-3.4, 0, 3.4];
export const PLAYER_Z = 4;
export const GROUND_Y = 0;

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
