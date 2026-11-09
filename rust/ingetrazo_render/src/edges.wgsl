// Classify in projected space so perspective, orthographic and mirrored placements
// use the same face-side test without a camera-dependent CPU topology upload.
fn facing(p: vec4f, q: vec4f, r: vec4f) -> f32 {
 // Homogeneous signed area avoids divisions at the near plane.
 return determinant(mat3x3f(p.xyw,q.xyw,r.xyw));
}
// Each endpoint carries its opposite endpoint, so expansion remains constant
// in physical pixels under perspective and nonuniform instance transforms.
// Scalar arrays keep this storage record tightly packed at 40 bytes.
struct Edge { a: array<f32,3>, b: array<f32,3>, normals: array<u32,4> }
@group(0) @binding(3) var<storage, read> edges: array<Edge>;
@vertex fn edge_vs(@builtin(vertex_index) vertex: u32, @builtin(instance_index) index: u32) -> Out {
 let first = vertex / 6u;
 let edge = edges[first];
 let id = survivors[index];
 let k = vertex % 6u;
 let end = k == 2u || k == 4u || k == 5u;
 let side_bit = k == 1u || k == 2u || k == 4u;
 let a0 = vec3f(edge.a[0],edge.a[1],edge.a[2]);
 let b0 = vec3f(edge.b[0],edge.b[1],edge.b[2]);
 let pos = select(a0,b0,end);
 let other = select(b0,a0,end);
 let n0 = vec3f(unpack2x16snorm(edge.normals[0]),unpack2x16snorm(edge.normals[1]).x);
 let tail = unpack2x16snorm(edge.normals[3]);
 let n1 = vec3f(unpack2x16snorm(edge.normals[2]),tail.x);
 let corner = vec4f(select(0.,1.,side_bit),select(0.,1.,end),tail.y,0.);
 let world = inst[id].world;
 let transform = camera.vp * world;
 var a = transform * vec4f(pos, 1.);
 var b = transform * vec4f(other, 1.);
 var profile = false;
 // Hard edges need classification only when it can change their width.
 if style.profiles.x > 0. && (corner.b > 0.5 || style.profiles.y > style.edge.w) {
  let boundary = dot(n0,n0) > 0. && dot(n1,n1) == 0.;
  let r0 = transform * vec4f(pos + cross(n0,other-pos),1.);
  let r1 = transform * vec4f(pos + cross(n1,other-pos),1.);
  profile = boundary || ((facing(a,b,r0)>0.) != (facing(a,b,r1)>0.));
 }
 if corner.b > 0.5 && !profile {
  var hidden: Out;
  hidden.position = vec4f(0.,0.,2.,1.);
  return hidden;
 }
 // Clip at the near plane before dividing by w; crossing edges must not
 // expand across the screen or flip their normal behind the camera.
 if a.z < 0. && b.z >= 0. { a = mix(a,b,-a.z/(b.z-a.z)); }
 if b.z < 0. && a.z >= 0. { b = mix(b,a,-b.z/(a.z-b.z)); }
 let direction = (b.xy/max(b.w,1e-6)-a.xy/max(a.w,1e-6))*camera.size.xy;
 let normal = vec2f(-direction.y,direction.x)/max(length(direction),1e-6);
 let width = select(style.edge.w,max(style.edge.w,style.profiles.y),profile && style.profiles.x > 0.);
 let side = (corner.r*2.-1.)*(1.-2.*corner.g);
 a = vec4f(a.xy + normal*side*width/camera.size.xy*a.w,a.zw);
 var o: Out;
 o.distance = corner.g * length(direction) * 0.5;
 o.position = a; o.id = id+1u; o.color = style.edge.rgb;
 o.shade = 1.; o.decorated = (inst[id].info.z & 6u) | select(0u,16u,corner.b > 0.5 && profile && style.profiles.x > 0.);
 return o;
}
