struct Prototype { lo: vec4f, hi: vec4f }
struct Instance { world: mat4x4f, info: vec4u }
struct Camera { vp: mat4x4f, size: vec4f }
struct Command { count: u32, instances: atomic<u32>, first: u32, base: i32, start: u32 }
@group(0) @binding(0) var<uniform> camera: Camera;
@group(0) @binding(1) var<storage, read> inst: array<Instance>;
@group(0) @binding(2) var<storage, read> proto: array<Prototype>;
@group(0) @binding(3) var<storage, read_write> commands: array<Command>;
@group(0) @binding(4) var<storage, read_write> survivors: array<u32>;
@compute @workgroup_size(64)
fn cull(@builtin(global_invocation_id) gid: vec3u) {
 let id = gid.x;
 if id >= arrayLength(&inst) { return; }
 let i = inst[id];
 if (i.info.z & 1u) != 0u { return; }
 let p = proto[i.info.x];
 let m = camera.vp * i.world;
 var outside = vec3u(0); var outside2 = vec3u(0);
 var low = vec2f(1e30); var high = vec2f(-1e30); var crosses = false;
 for (var k = 0u; k < 8u; k++) {
  let v = select(p.lo.xyz, p.hi.xyz, vec3<bool>((k&1u)!=0u,(k&2u)!=0u,(k&4u)!=0u));
  let q = m * vec4f(v, 1);
  outside += vec3u(q.x < -q.w, q.y < -q.w, q.z < 0);
  outside2 += vec3u(q.x > q.w, q.y > q.w, q.z > q.w);
  if q.w <= 0 { crosses = true; } else {
   low = min(low, q.xy/q.w); high = max(high, q.xy/q.w);
  }
 }
 if any(outside == vec3u(8)) || any(outside2 == vec3u(8)) { return; }
 if !crosses && all((high-low)*camera.size.xy*0.5 < vec2f(1)) { return; }
 let slot = atomicAdd(&commands[i.info.x].instances, 1u);
 survivors[commands[i.info.x].start+slot] = id;
}
