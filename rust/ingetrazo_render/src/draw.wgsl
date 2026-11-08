struct Instance { world: mat4x4f, info: vec4u }
struct Camera { vp: mat4x4f, size: vec4f }
@group(0) @binding(0) var<uniform> camera: Camera;
@group(0) @binding(1) var<storage, read> inst: array<Instance>;
@group(0) @binding(2) var<storage, read> survivors: array<u32>;
struct Out { @builtin(position) position: vec4f, @location(0) color: vec3f, @location(1) @interpolate(flat) id: u32 }
@vertex fn vs(@location(0) pos: vec3f, @location(1) normal: vec3f, @location(2) color: vec4f, @builtin(instance_index) index: u32) -> Out {
 let id = survivors[index]; let i = inst[id];
 let n = normalize((i.world * vec4f(normal,0)).xyz);
 var o: Out; o.position = camera.vp*i.world*vec4f(pos,1);
 o.color = select(color.rgb, color.rgb * unpack4x8unorm(i.info.y).rgb, color.a < 0.5) * (0.62+0.38*abs(dot(n,normalize(vec3f(0.3,-0.5,0.8)))));
 o.id = id+1u; return o;
}
struct Pixel { @location(0) color: vec4f, @location(1) id: u32 }
@fragment fn fs(i: Out) -> Pixel { var p: Pixel; p.color=vec4f(i.color,1); p.id=i.id; return p; }
