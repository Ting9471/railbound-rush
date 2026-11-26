import { afterEach, describe, expect, it, vi } from "vitest";
import { PerspectiveCamera, Vector3 } from "three";
import { readFileSync } from "node:fs";
import { clampLane, springStep, overlaps, playerBounds, obstacleBounds, canLandOnRoof, coinCollected, wrapChunkZ, PATTERNS, runnerAnimationState, jumpAnimationPhase, CHARACTERS, resolveCharacter, runCameraLayout, LANES, PLAYER_Z, cycleCharacter, loadModelData, withTimeout } from "../src/logic.js";

describe("model download reliability", () => {
  afterEach(() => { vi.unstubAllGlobals();vi.useRealTimers(); });

  it("assembles streamed model bytes and reports real download progress", async () => {
    const onProgress = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array([1, 2]));
        controller.enqueue(new Uint8Array([3, 4, 5]));
        controller.close();
      }
    }))));
    expect([...new Uint8Array(await loadModelData("https://example.com/models/cat.glb", { onProgress }))]).toEqual([1, 2, 3, 4, 5]);
    expect(onProgress.mock.calls.map(([loaded]) => loaded)).toEqual([2, 5]);
  });

  it("rejects missing models instead of attempting to parse an HTML error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("missing", { status: 404 })));
    await expect(loadModelData("https://example.com/missing.glb")).rejects.toThrow("HTTP 404");
  });

  it("aborts stalled downloads at the deadline", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((url, { signal }) => new Promise((resolve, reject) => {
      signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    })));
    const result = expect(loadModelData("https://example.com/stalled.glb", { timeoutMs: 1000 })).rejects.toThrow("模型下载超时");
    await vi.advanceTimersByTimeAsync(1000);
    await result;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("cancels the previous runner download when switching", async () => {
    const controller = new AbortController();
    let downloadSignal;
    vi.stubGlobal("fetch", vi.fn((url, { signal }) => {
      downloadSignal = signal;
      return new Promise((resolve, reject) => signal.addEventListener("abort", () => reject(signal.reason), { once: true }));
    }));
    const result = expect(loadModelData("https://example.com/cat.glb", { signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    await result;
    expect(downloadSignal.aborted).toBe(true);
  });

  it("preserves network errors so callers can offer a retry", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(loadModelData("https://example.com/cat.glb")).rejects.toThrow("Failed to fetch");
  });

  it("bounds model parsing and clears the deadline after success", async () => {
    vi.useFakeTimers();
    await expect(withTimeout(Promise.resolve("model"), 1000, "解析超时")).resolves.toBe("model");
    expect(vi.getTimerCount()).toBe(0);
    const result = expect(withTimeout(new Promise(() => {}), 1000, "解析超时")).rejects.toThrow("解析超时");
    await vi.advanceTimersByTimeAsync(1000);
    await result;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not depend on external font downloads to load the game", () => {
    const css = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
    expect(css).not.toMatch(/@import\s+url\(['"]https?:/);
  });
});

describe("character selection", () => {
  it("offers exactly the original, Ch09 and cat without the rejected director version", () => {
    expect(CHARACTERS.map(character => character.id)).toEqual(["classic", "ch09", "cat"]);
    expect(new Set(CHARACTERS.map(character => character.file)).size).toBe(3);
  });
  it("uses the player-facing names and slightly enlarges Tim and the cat", () => {
    expect(CHARACTERS.map(character => character.name)).toEqual(["经典", "蒂姆", "猫猫跑者"]);
    expect(CHARACTERS.find(character => character.id === "classic").scale).toBe(0.82);
    for (const id of ["ch09", "cat"]) expect(CHARACTERS.find(character => character.id === id).scale).toBe(1.12);
  });
  it("cycles through all runners in both directions and wraps at the ends", () => {
    expect(cycleCharacter("classic", 1)).toBe("ch09");
    expect(cycleCharacter("ch09", 1)).toBe("cat");
    expect(cycleCharacter("cat", 1)).toBe("classic");
    expect(cycleCharacter("classic", -1)).toBe("cat");
    expect(cycleCharacter("cat", -1)).toBe("ch09");
    expect(cycleCharacter("ch09", -1)).toBe("classic");
  });
  it("defaults to the new cat and restores a saved choice", () => {
    expect(resolveCharacter(null, null)).toBe("cat");
    expect(resolveCharacter(null, "ch09")).toBe("ch09");
    expect(resolveCharacter(null, "classic")).toBe("classic");
  });
  it("honors valid shared links before a saved choice", () => {
    expect(resolveCharacter("cat", "classic")).toBe("cat");
    expect(resolveCharacter("classic", "cat")).toBe("classic");
  });
  it("ignores invalid query or storage values", () => {
    expect(resolveCharacter("director", "ch09")).toBe("ch09");
    expect(resolveCharacter("unknown", "unknown")).toBe("cat");
  });
});

describe("imported character animation", () => {
  const player = { support: "ground", sliding: false, dead: false };
  it("uses idle for menus and completed runs", () => {
    for (const phase of ["menu", "over"]) expect(runnerAnimationState(player, phase)).toBe("Idle");
    expect(runnerAnimationState({ ...player, dead: true }, "running")).toBe("Idle");
  });
  it("runs on the ground or a train roof", () => {
    expect(runnerAnimationState(player, "running")).toBe("Run");
    expect(runnerAnimationState({ ...player, support: { roofY: 2.78 } }, "running")).toBe("Run");
  });
  it("uses jump before slide when unsupported", () => {
    expect(runnerAnimationState({ ...player, support: null, sliding: true }, "running")).toBe("Jump");
    expect(runnerAnimationState({ ...player, sliding: true }, "running")).toBe("Slide");
  });
});

describe("Ch09 Fast Run asset", () => {
  it("includes the downloaded Run cycle and keeps the other gameplay clips", () => {
    const data = readFileSync(new URL("../public/models/ch09.glb", import.meta.url));
    expect(data.toString("ascii", 0, 4)).toBe("glTF");
    const jsonLength = data.readUInt32LE(12);
    const document = JSON.parse(data.toString("utf8", 20, 20 + jsonLength));
    const binary = data.subarray(28 + jsonLength);
    const scalarValues = index => {
      const accessor = document.accessors[index], view = document.bufferViews[accessor.bufferView];
      expect(accessor.componentType).toBe(5126);
      const offset = (view.byteOffset || 0) + (accessor.byteOffset || 0);
      return Array.from({ length: accessor.count }, (_, i) => binary.readFloatLE(offset + i * (view.byteStride || 4)));
    };
    const clips = new Map(document.animations.map(clip => [clip.name, clip]));
    expect([...clips.keys()].sort()).toEqual(["Idle", "Jump", "Run", "Slide"]);
    for (const [name, duration] of [["Idle", 2], ["Jump", 0.9], ["Slide", 0.8], ["Run", 16 / 30]]) {
      const clip = clips.get(name);
      const times = clip.samplers.flatMap(sampler => scalarValues(sampler.input));
      expect(Math.max(...times) - Math.min(...times)).toBeCloseTo(duration, 5);
    }
    const run = clips.get("Run");
    const root = run.channels.find(channel => channel.target.path === "translation"
      && document.nodes[channel.target.node].name.endsWith("Hips"));
    expect(root).toBeDefined();
    const accessor = document.accessors[run.samplers[root.sampler].output];
    const view = document.bufferViews[accessor.bufferView];
    const offset = (view.byteOffset || 0) + (accessor.byteOffset || 0);
    for (const axis of [0, 2]) {
      const values = Array.from({ length: accessor.count }, (_, i) =>
        binary.readFloatLE(offset + i * (view.byteStride || 12) + axis * 4));
      expect(Math.max(...values) - Math.min(...values)).toBeLessThan(0.001);
    }
    expect(document.skins[0].joints).toHaveLength(65);
    expect(document.nodes.filter(node => node.mesh !== undefined).map(node => node.name)).toEqual(["Ch09"]);
  });
});

describe("jump animation synchronization", () => {
  it("maps takeoff and apex onto the first half", () => {
    expect(jumpAnimationPhase({ y: 0, vy: 11.2 })).toBe(0);
    expect(jumpAnimationPhase({ y: 3.2, vy: 0 })).toBe(0.5);
  });
  it("starts a roof fall in the descending half", () => {
    expect(jumpAnimationPhase({ y: 2.78, vy: 0 })).toBe(0.5);
    expect(jumpAnimationPhase({ y: 1.5, vy: -7 })).toBeGreaterThan(0.5);
  });
  it("finishes at the landing surface, including a train roof", () => {
    expect(jumpAnimationPhase({ y: 2.78, vy: -4 }, 2.78)).toBe(1);
    expect(jumpAnimationPhase({ y: 0, vy: -11.2 })).toBe(1);
    expect(jumpAnimationPhase({ y: 0, vy: 0 })).toBe(1);
  });
  it("clamps the rising phase when velocities exceed launch speed", () => {
    expect(jumpAnimationPhase({ y: 0, vy: 20 })).toBe(0);
  });
});

describe("runner camera framing", () => {
  it("anchors the runner near the bottom with the slide head in the bottom tenth", () => {
    for (const aspect of [1440 / 900, 390 / 844, 320 / 740, 844 / 390]) {
      for (const fov of [58, 61.6]) {
        const layout = runCameraLayout(aspect, fov);
        const camera = new PerspectiveCamera(fov, aspect, 0.1, 220);
        camera.position.set(0, layout.height, layout.z);
        camera.lookAt(0, layout.targetY, layout.targetZ);
        camera.updateMatrixWorld();
        const feet = new Vector3(0, 0, PLAYER_Z).project(camera);
        expect((1 - feet.y) / 2).toBeCloseTo(0.98, 5);
        const head = new Vector3(0, 0.82, PLAYER_Z).project(camera);
        expect((1 - head.y) / 2).toBeGreaterThan(0.9);
        expect((1 - head.y) / 2).toBeLessThan(0.98);
      }
    }
  });
  for (const [width, height] of [[1440, 900], [390, 844], [320, 740], [844, 390]]) {
    it(`keeps all lanes and low poses visible at ${width}x${height}`, () => {
      for (const fov of [58, 61.6]) {
        const aspect = width / height, layout = runCameraLayout(aspect, fov);
        for (const cameraX of [-0.816, 0, 0.816]) {
          const camera = new PerspectiveCamera(fov, aspect, 0.1, 220);
          camera.position.set(cameraX, layout.height, layout.z);
          camera.lookAt(cameraX * 0.25, layout.targetY, layout.targetZ);
          camera.updateMatrixWorld();
          for (const lane of LANES) for (const offset of [-0.7, 0.7]) {
            for (const y of [0, 0.82, 2.05, 8.1]) {
              const point = new Vector3(lane + offset, y, PLAYER_Z).project(camera);
              expect(Math.abs(point.x)).toBeLessThan(1);
              expect(Math.abs(point.y)).toBeLessThan(1);
              if (y === 0) {
                const groundY = (1 - point.y) / 2;
                expect(groundY).toBeGreaterThan(0.96);
                expect(groundY).toBeLessThan(0.995);
              }
            }
          }
        }
      }
    });
  }
});

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
