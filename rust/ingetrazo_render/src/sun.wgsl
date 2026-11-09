// Sun receiver: GL's matte multiplier and a bilinear 3x3 PCF kernel.
struct Sun { inverse_vp: mat4x4f, light_vp: mat4x4f, direction_dark: vec4f, settings: vec4f }
@group(0) @binding(0) var<uniform> sun: Sun;
@group(0) @binding(1) var depth: texture_depth_2d;
@group(0) @binding(2) var shadow: texture_depth_2d;
@group(0) @binding(3) var compare: sampler_comparison;
@vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4f {
 let p = array<vec2f,3>(vec2f(-1.,-1.),vec2f(3.,-1.),vec2f(-1.,3.)); return vec4f(p[i],0.,1.);
}
fn world(uv: vec2f, d: f32) -> vec3f { let p = sun.inverse_vp*vec4f(uv.x*2.-1.,1.-uv.y*2.,d,1.); return p.xyz/p.w; }
fn light(world_position: vec3f) -> f32 {
 let lp = sun.light_vp*vec4f(world_position,1.);
 let uvz = vec3f(lp.x/lp.w*0.5+0.5,0.5-lp.y/lp.w*0.5,lp.z/lp.w);
 let dx = dpdx(uvz); let dy = dpdy(uvz); let det = dx.x*dy.y-dx.y*dy.x;
 var grad = vec2f(0.);
 if abs(det)>1e-12 { grad = vec2f(dy.y*dx.z-dx.y*dy.z,dx.x*dy.z-dy.x*dx.z)/det; }
 grad *= min(1.,8./max(length(grad),1e-10));
 let step = 1./vec2f(textureDimensions(shadow));
 let bias = 0.0006+length(grad)*step.x*1.5;
 var lit = 0.;
 for(var y=-1;y<=1;y++) { for(var x=-1;x<=1;x++) {
  let offset = vec2f(f32(x),f32(y))*step;
  lit += textureSampleCompareLevel(shadow,compare,uvz.xy+offset,uvz.z+dot(grad,offset)-bias);
 }}
 return select(lit/9.,1.,any(uvz.xy<=vec2f(0.)) || any(uvz.xy>=vec2f(1.)) || uvz.z>=1.);
}
@fragment fn fs(@builtin(position) p: vec4f) -> @location(0) vec4f {
 let size = vec2f(textureDimensions(depth)); let uv = p.xy/size;
 let d = textureLoad(depth,vec2i(p.xy),0);
 var pos = world(uv,d); let near = world(uv,0.); let far = world(uv,1.);
 var normal = normalize(cross(dpdx(pos),dpdy(pos)));
 // WGPU's framebuffer Y runs downward; orient toward the camera explicitly.
 if dot(normal,near-pos)<0. { normal = -normal; }
 var ground = false;
 if d>=1. {
  let ray = far-near;
  let t = (-0.005-near.z)/ray.z;
  pos = near+ray*t; normal=vec3f(0.,0.,1.); ground = true;
  if sun.settings.x == 0. || t<0. || t>1. { discard; }
 }
 let lit = light(pos);
 var multiplier = mix(sun.direction_dark.w,1.,clamp(dot(normal,sun.direction_dark.xyz)*1.5,0.,1.)*lit);
 if ground { multiplier = 1.-(1.-sun.direction_dark.w)*(1.-lit); }
 // sRGB render targets multiply linear light; encode GL's display multiplier.
 let linear_multiplier = pow(max(multiplier,0.),2.2);
 return vec4f(vec3f(linear_multiplier),1.);
}
