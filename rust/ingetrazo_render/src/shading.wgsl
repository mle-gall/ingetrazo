// GL uses display-referred colors; explicitly decode for the sRGB surface.
struct Style { front: vec4f, back: vec4f, edge: vec4f, background: vec4f, sky: vec4f, ground: vec4f }
@group(1) @binding(0) var<uniform> style: Style;
fn linear(c: vec3f) -> vec3f { return select(c/12.92,pow((c+0.055)/1.055,vec3f(2.4)),c>vec3f(0.04045)); }
struct Instance { world: mat4x4f, info: vec4u }
struct Camera { vp: mat4x4f, size: vec4f }
@group(0) @binding(0) var<uniform> camera: Camera;
@group(0) @binding(1) var<storage, read> inst: array<Instance>;
@group(0) @binding(2) var<storage, read> survivors: array<u32>;
struct Out { @builtin(position) position: vec4f, @location(0) color: vec3f, @location(1) @interpolate(flat) id: u32, @location(2) shade: f32, @location(3) @interpolate(flat) decorated: u32 }
@vertex fn vs(@location(0) pos: vec3f, @location(1) normal: vec3f, @location(2) color: vec4f, @builtin(instance_index) index: u32) -> Out {
 let id = survivors[index]; let i = inst[id];
 let a=i.world[0].xyz; let b=i.world[1].xyz; let c=i.world[2].xyz;
 let n = normalize(mat3x3f(cross(b,c),cross(c,a),cross(a,b))*normal);
 var o: Out; o.position = camera.vp*i.world*vec4f(pos,1);
 o.shade = 0.62+0.38*abs(dot(n,normalize(vec3f(0.35,0.25,1.))));
 let tint = unpack4x8unorm(i.info.y);
 var base = select(color.rgb, tint.rgb, color.a < 0.5);
 o.color = base * o.shade;
 if camera.size.z == 2 || camera.size.z == 3 { o.color = style.front.rgb; }
 if (i.info.w >> 24u) != 0u { o.color = unpack4x8unorm(i.info.w).rgb; }
 if (i.info.z & 2u) != 0u { o.color = mix(o.color, vec3f(0.95,0.45,0.16), 0.65); }
 if (i.info.z & 4u) != 0u { o.color = mix(o.color, vec3f(0.30,0.55,0.95), 0.5); }
 o.decorated = (i.info.z & 6u) | (i.info.w >> 24u);
 o.id = id+1u; return o;
}
struct Pixel { @location(0) color: vec4f, @location(1) id: u32 }
fn face_pixel(i: Out, front: bool) -> Pixel {
 var c = i.color;
 if !front && camera.size.z != 2 && i.decorated == 0u { c = style.back.rgb * select(i.shade,1.,camera.size.z == 3); }
 var p: Pixel; p.color=vec4f(linear(c),select(1.,0.4,camera.size.z == 1)); p.id=i.id; return p;
}

fn edge_pixel(i: Out) -> Pixel { var p: Pixel; p.color=vec4f(linear(style.edge.rgb),1); p.id=i.id; return p; }

@fragment fn color_fs(i: Out, @builtin(front_facing) front: bool) -> @location(0) vec4f {
 return face_pixel(i,front).color;
}
@fragment fn color_edge_fs(i: Out) -> @location(0) vec4f { return edge_pixel(i).color; }

@fragment fn fs(i: Out, @builtin(front_facing) front: bool) -> Pixel { return face_pixel(i,front); }
@fragment fn edge_fs(i: Out) -> Pixel { return edge_pixel(i); }
