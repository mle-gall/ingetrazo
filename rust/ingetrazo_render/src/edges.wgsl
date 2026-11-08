// Each endpoint carries its opposite endpoint, so expansion remains constant
// in physical pixels under perspective and nonuniform instance transforms.
@vertex fn edge_vs(@location(0) pos: vec3f, @location(1) other: vec3f,
                   @location(2) corner: vec4f, @builtin(instance_index) index: u32) -> Out {
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
 let side = (corner.r*2.-1.)*(1.-2.*corner.g);
 a = vec4f(a.xy + normal*side*style.edge.w/camera.size.xy*a.w,a.zw);
 var o: Out;
 o.position = a; o.id = id+1u; o.color = style.edge.rgb;
 o.shade = 1.; o.decorated = inst[id].info.z & 6u;
 return o;
}
