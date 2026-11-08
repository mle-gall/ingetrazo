@group(0) @binding(0) var pixels: texture_2d<f32>;
struct Varying {
    @builtin(position) position: vec4<f32>,
};
@vertex fn vs(@builtin(vertex_index) i: u32) -> Varying {
    var xy = array<vec2<f32>, 3>(vec2(-1., -1.), vec2(3., -1.), vec2(-1., 3.));
    var out: Varying;
    out.position = vec4(xy[i], 0., 1.);
    return out;
}
@fragment fn fs(v: Varying) -> @location(0) vec4<f32> {
    return textureLoad(pixels, vec2<i32>(v.position.xy), 0);
}
