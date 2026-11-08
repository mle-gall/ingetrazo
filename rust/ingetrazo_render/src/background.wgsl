struct Style { front: vec4f, back: vec4f, edge: vec4f, background: vec4f, sky: vec4f, ground: vec4f }
@group(0) @binding(0) var<uniform> style: Style;
struct Out { @builtin(position) position: vec4f, @location(0) y: f32 }
@vertex fn vs(@builtin(vertex_index) i: u32) -> Out {
 let xy = array<vec2f,3>(vec2f(-1,-1),vec2f(3,-1),vec2f(-1,3));
 var o: Out; o.position = vec4f(xy[i],0,1); o.y = xy[i].y; return o;
}
fn linear(c: vec3f) -> vec3f { return select(c/12.92,pow((c+0.055)/1.055,vec3f(2.4)),c>vec3f(0.04045)); }
@fragment fn fs(i: Out) -> @location(0) vec4f {
 var c = style.background.rgb;
 if style.background.a > 0.5 {
  let hy = style.sky.a;
  let sh = mix(style.sky.rgb,vec3f(1),0.55);
  let gh = mix(style.ground.rgb,vec3f(1),0.30);
  let split = clamp(hy,-1.,1.);
  let sb = mix(sh,style.sky.rgb,clamp((split-hy)/1.4,0.,1.));
  let st = mix(sh,style.sky.rgb,clamp((1.-hy)/1.4,0.,1.));
  let gb = mix(gh,style.ground.rgb,clamp((hy+1.)/0.9,0.,1.));
  let gt = mix(gh,style.ground.rgb,clamp((hy-split)/0.9,0.,1.));
  c = select(mix(gb,gt,clamp((i.y+1.)/max(split+1.,0.00001),0.,1.)),
             mix(sb,st,clamp((i.y-split)/max(1.-split,0.00001),0.,1.)),i.y>=split);
  if abs(i.y-hy) < fwidth(i.y)*0.5 { c = mix(sh,gh,0.5)*0.88; }
 }
 return vec4f(linear(c),1);
}
