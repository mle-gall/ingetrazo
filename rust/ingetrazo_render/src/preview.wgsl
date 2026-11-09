// World-space transient meshes: 28-byte vertex ABI, no resident ownership.
struct Camera { vp: mat4x4f, size: vec4f }
struct Style { front: vec4f, back: vec4f, edge: vec4f, background: vec4f, sky: vec4f, ground: vec4f, profiles: vec4f, section_plane: vec4f, fade: vec4f, raster: vec4f }
@group(0) @binding(0) var<uniform> camera: Camera;
@group(0) @binding(1) var<uniform> style: Style;
override MARK: bool = false;
override GHOST: bool = false;
override EDGE: bool = false;
struct Out { @builtin(position) position: vec4f, @location(0) color: vec4f, @location(1) section: f32 }
@vertex fn vs(@location(0) pos: vec3f, @location(1) normal: vec3f, @location(2) color: vec4f) -> Out {
 var o: Out; o.position = camera.vp*vec4f(pos,1.);
 let shade = select(0.62+0.38*abs(dot(normalize(normal),normalize(vec3f(0.35,0.25,1.)))),1.,EDGE || MARK);
 o.color = vec4f(select(color.rgb,style.front.rgb,color.a == 0.)*shade,select(color.a,1.,color.a == 0.));
 o.section = dot(vec4f(pos,1.),style.section_plane); return o;
}
@fragment fn fs(i: Out) -> @location(0) vec4f {
 if i.section < 0. { discard; }
 if GHOST {
  if EDGE { if ((i.position.x+i.position.y)%6.)>=3. { discard; } }
  else { if all((i.position.xy%vec2f(4.))>=vec2f(1.)) { discard; } }
 }
 if MARK && !all((i.position.xy % vec2f(6.)) < vec2f(2.)) { discard; }
 let c = i.color.rgb;
 return vec4f(select(c/12.92,pow((c+0.055)/1.055,vec3f(2.4)),c>vec3f(0.04045)),i.color.a);
}
