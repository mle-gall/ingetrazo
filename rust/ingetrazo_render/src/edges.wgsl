// Classify in projected space so perspective, orthographic and mirrored placements
// use the same face-side test without a camera-dependent CPU topology upload.
fn facing(pos: vec3f, other: vec3f, n: vec3f, transform: mat4x4f) -> f32 {
 let p = transform * vec4f(pos,1.);
 let q = transform * vec4f(other,1.);
 let r = transform * vec4f(pos + cross(n, other-pos),1.);
 // Homogeneous signed area avoids divisions at the near plane.
 return determinant(mat3x3f(p.xyw,q.xyw,r.xyw));
}
// Each endpoint carries its opposite endpoint, so expansion remains constant
// in physical pixels under perspective and nonuniform instance transforms.
@vertex fn edge_vs(@location(0) pos: vec3f, @location(1) other: vec3f,
                   @location(2) corner: vec4f, @location(3) n0: vec3f, @location(4) n1: vec3f, @builtin(instance_index) index: u32) -> Out {
 let id = survivors[index];
 let world = inst[id].world;
 var a = camera.vp * world * vec4f(pos, 1.);
 var b = camera.vp * world * vec4f(other, 1.);
 // Clip at the near plane before dividing by w; crossing edges must not
 // expand across the screen or flip their normal behind the camera.
 if a.z < 0. && b.z >= 0. { a = mix(a,b,-a.z/(b.z-a.z)); }
 if b.z < 0. && a.z >= 0. { b = mix(b,a,-b.z/(a.z-b.z)); }
 let direction = (b.xy/max(b.w,1e-6)-a.xy/max(a.w,1e-6))*camera.size.xy;
 let normal = vec2f(-direction.y,direction.x)/max(length(direction),1e-6);
 let transform = camera.vp * world;
 let boundary = length(n0) > 0. && length(n1) == 0.;
 let profile = boundary || ((facing(pos,other,n0,transform)>0.) != (facing(pos,other,n1,transform)>0.));
 let width = select(style.edge.w,max(style.edge.w,style.profiles.y),profile && style.profiles.x > 0.);
 let side = (corner.r*2.-1.)*(1.-2.*corner.g);
 a = vec4f(a.xy + normal*side*width/camera.size.xy*a.w,a.zw);
 if corner.b > 0.5 && !(profile && style.profiles.x > 0.) { a = vec4f(0.,0.,2.,1.); }
 var o: Out;
 o.distance = corner.g * length(direction) * 0.5;
 o.position = a; o.id = id+1u; o.color = style.edge.rgb;
 o.shade = 1.; o.decorated = (inst[id].info.z & 6u) | select(0u,16u,corner.b > 0.5 && profile && style.profiles.x > 0.);
 return o;
}
