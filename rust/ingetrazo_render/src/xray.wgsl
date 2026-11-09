// Weighted blended OIT: accumulated premultiplied color and transmittance.
struct Accum { @location(0) color: vec4f, @location(1) reveal: vec4f }
@fragment fn accumulate(i: Out, @builtin(front_facing) front: bool) -> Accum {
 let face = face_pixel(i, front).color;
 if camera.size.z != 1. && (face.a >= 1. || face.a <= 0.) { discard; }
 var o: Accum;
 o.color = vec4f(face.rgb * face.a, face.a);
 o.reveal = vec4f(face.a);
 return o;
}
