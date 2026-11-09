struct Camera { vp: mat4x4f, size: vec4f }
struct Axes { frame: mat4x4f, spacing: vec4f }
@group(0) @binding(0) var<uniform> camera: Camera;
@group(0) @binding(1) var<uniform> axes: Axes;
struct Out { @builtin(position) position: vec4f, @location(0) color: vec3f }
@vertex fn vs(@builtin(vertex_index) vertex: u32, @builtin(instance_index) axis: u32) -> Out {
 let segment = vertex / 6u;
 let k = vertex % 6u;
 let end = k == 2u || k == 4u || k == 5u;
 let side_bit = k == 1u || k == 2u || k == 4u;
 var t0 = 0.; var t1 = 1e5;
 if segment > 0u {
  t0 = -f32(segment-1u)*axes.spacing.x;
  t1 = t0-0.18*axes.spacing.x;
 }
 let direction = normalize(axes.frame[axis].xyz);
 let origin = axes.frame[3].xyz;
 var a = camera.vp * vec4f(origin + direction*select(t0,t1,end),1.);
 var b = camera.vp * vec4f(origin + direction*select(t1,t0,end),1.);
 if a.z < 0. && b.z >= 0. { a = mix(a,b,-a.z/(b.z-a.z)); }
 if b.z < 0. && a.z >= 0. { b = mix(b,a,-b.z/(a.z-b.z)); }
 let delta = (b.xy/max(b.w,1e-6)-a.xy/max(a.w,1e-6))*camera.size.xy;
 var out: Out;
 if length(delta) == 0. { out.position = vec4f(0.,0.,2.,1.); return out; }
 let normal = vec2f(-delta.y,delta.x)/length(delta);
 let side = select(-1.,1.,side_bit)*select(1.,-1.,end);
 // One physical pixel, like GL_LINES. The factor two from NDC cancels
 // the half-width; no device-scale multiplication belongs here.
 out.position = vec4f(a.xy+normal*side/camera.size.xy*a.w,a.zw);
 out.color = array<vec3f,3>(vec3f(0.86,0.22,0.27),vec3f(0.16,0.62,0.36),vec3f(0.20,0.40,0.78))[axis];
 return out;
}
@fragment fn fs(i: Out) -> @location(0) vec4f {
 let c = i.color;
 return vec4f(select(c/12.92,pow((c+0.055)/1.055,vec3f(2.4)),c>vec3f(0.04045)),1.);
}
