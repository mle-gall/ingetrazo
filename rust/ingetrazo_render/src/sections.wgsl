struct Camera { vp: mat4x4f, size: vec4f, eye: vec4f, pick_rect: vec4f }
@group(0) @binding(0) var<uniform> camera: Camera;
struct Output { @builtin(position) position: vec4f, @location(0) color: vec3f }
@vertex fn vs(@location(0) position: vec3f, @location(1) color: vec3f) -> Output {
    var o: Output;
    o.position = camera.vp * vec4f(position, 1.);
    o.color = color;
    return o;
}
@fragment fn fs(i: Output) -> @location(0) vec4f { let c = i.color; return vec4f(select(c/12.92, pow((c+0.055)/1.055, vec3f(2.4)), c>vec3f(0.04045)), 1.); }
