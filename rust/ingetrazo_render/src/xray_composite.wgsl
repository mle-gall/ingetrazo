@group(0) @binding(0) var accumulation: texture_2d<f32>;
@group(0) @binding(1) var reveal: texture_2d<f32>;
@vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4f {
 let p = array<vec2f,3>(vec2f(-1.,-1.),vec2f(3.,-1.),vec2f(-1.,3.));
 return vec4f(p[i],0.,1.);
}
@fragment fn fs(@builtin(position) p: vec4f) -> @location(0) vec4f {
 let a = textureLoad(accumulation, vec2i(p.xy), 0);
 let t = textureLoad(reveal, vec2i(p.xy), 0).r;
 return vec4f(a.rgb/max(a.a,0.00001),1.-t);
}
