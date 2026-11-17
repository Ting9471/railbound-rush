import { describe, expect, it } from "vitest";
import { clampLane, springStep, overlaps, playerBounds, obstacleBounds, canLandOnRoof, coinCollected, wrapChunkZ, PATTERNS } from "../src/logic.js";

describe("runner movement", () => {
  it("keeps lane indices inside three tracks", () => {
    expect(clampLane(-2)).toBe(0);
    expect(clampLane(1)).toBe(1);
    expect(clampLane(9)).toBe(2);
  });

  it("spring converges to a selected lane", () => {
    let position = 0, velocity = 0;
    for (let i = 0; i < 180; i++) ({ position, velocity } = springStep(position, velocity, 3.4, 1 / 60));
    expect(position).toBeCloseTo(3.4, 3);
  });
});

describe("height-aware collisions", () => {
  const base = { x: 0, y: 0, vy: 0, sliding: false };

  it("jumping clears a low barrier", () => {
    const obstacle = obstacleBounds({ kind: "low", lane: 1, baseY: 0, z: 4 });
    expect(overlaps(playerBounds(base), obstacle)).toBe(true);
    expect(overlaps(playerBounds({ ...base, y: 1.05 }), obstacle)).toBe(false);
  });

  it("sliding clears a high barrier", () => {
    const obstacle = obstacleBounds({ kind: "high", lane: 1, baseY: 0, z: 4 });
    expect(overlaps(playerBounds(base), obstacle)).toBe(true);
    expect(overlaps(playerBounds({ ...base, sliding: true }), obstacle)).toBe(false);
  });

  it("lands only while descending across a roof", () => {
    const train = { lane: 1, z: 4, length: 12, roofY: 2.75 };
    expect(canLandOnRoof({ ...base, y: 2.7, vy: -1 }, 2.9, train)).toBe(true);
    expect(canLandOnRoof({ ...base, y: 2.7, vy: 1 }, 2.6, train)).toBe(false);
  });

  it("requires coins to overlap in three dimensions", () => {
    expect(coinCollected(base, { lane: 1, y: 0.95, z: 4 })).toBe(true);
    expect(coinCollected(base, { lane: 1, y: 3.5, z: 4 })).toBe(false);
  });
});

describe("scrolling scenery", () => {
  it("wraps foreground chunks using the authored 54 meter span", () => {
    expect(wrapChunkZ(26, 3, 54, 4, 27)).toBe(-187);
    expect(wrapChunkZ(-60, 2, 54, 4, 27)).toBe(-58);
  });

  it("wraps the slower distant skyline independently", () => {
    expect(wrapChunkZ(47, 3, 96, 3, 48)).toBe(-238);
    expect(wrapChunkZ(-96, 4, 96, 3, 48)).toBe(-92);
  });
});

describe("chunk grammar", () => {
  it("gives every pattern a traversable option", () => {
    for (const pattern of PATTERNS) {
      const blocked = new Set(pattern.placements.filter(p => p.kind === "train").map(p => p.lane));
      expect(blocked.size).toBeLessThan(3);
      expect(pattern.length).toBeGreaterThanOrEqual(30);
    }
  });
});
