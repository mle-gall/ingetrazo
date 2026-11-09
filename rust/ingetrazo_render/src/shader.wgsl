struct Prototype { lo: vec4f, hi: vec4f }
struct Instance { world: mat4x4f, info: vec4u }
struct Camera { vp: mat4x4f, size: vec4f, eye: vec4f }
struct Command { count: u32, instances: atomic<u32>, first: u32, base: i32, start: u32 }
@group(0) @binding(0) var<uniform> camera: Camera;
@group(0) @binding(1) var<storage, read> inst: array<Instance>;
@group(0) @binding(2) var<storage, read> proto: array<Prototype>;
@group(0) @binding(3) var<storage, read_write> commands: array<Command>;
@group(0) @binding(4) var<storage, read_write> survivors: array<u32>;
struct EdgePlacement { eye: vec4f, transform: mat4x4f }
@group(0) @binding(5) var<storage, read_write> viewpoints: array<EdgePlacement>;
@group(0) @binding(6) var<storage, read_write> counters: array<atomic<u32>>;
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
  outside += vec3u(vec3<bool>(q.x < -q.w, q.y < -q.w, q.z < 0));
  outside2 += vec3u(vec3<bool>(q.x > q.w, q.y > q.w, q.z > q.w));
  if q.w <= 0 { crosses = true; } else {
   low = min(low, q.xy/q.w); high = max(high, q.xy/q.w);
  }
 }
 if any(outside == vec3u(8)) || any(outside2 == vec3u(8)) { atomicAdd(&counters[1], 1u); return; }
 if !crosses && all((high-low)*camera.size.xy*0.5 < vec2f(1)) { atomicAdd(&counters[2], 1u); return; }
 atomicAdd(&counters[0], 1u);
 atomicAdd(&counters[3], commands[i.info.x].count / 3u);
 viewpoints[id].transform = m;
 let a = i.world[0].xyz; let b = i.world[1].xyz; let c = i.world[2].xyz;
 let determinant = dot(a,cross(b,c));
 let r = camera.eye.xyz - i.world[3].xyz * camera.eye.w;
 viewpoints[id].eye = vec4f(0.,0.,0.,2.);
 if abs(determinant) > 1e-20 {
  viewpoints[id].eye = vec4f(vec3f(dot(cross(b,c),r),dot(cross(c,a),r),dot(cross(a,b),r))/determinant,camera.eye.w);
 }
 let edge_command = i.info.x + arrayLength(&proto);
 atomicAdd(&commands[edge_command].instances, 1u);
 let slot = atomicAdd(&commands[i.info.x].instances, 1u);
 survivors[commands[i.info.x].start+slot] = id;
}
