// Horizon AO, ported from resources/shaders/ao*.frag (GPL-3.0-or-later).
struct Params { proj: mat4x4<f32>, inv: mat4x4<f32>, settings: vec4<f32> }
@group(0) @binding(0) var<uniform> u: Params;
@group(0) @binding(1) var depth: texture_depth_2d;
@group(0) @binding(2) var source: texture_2d<f32>;
@group(0) @binding(3) var color: texture_2d<f32>;
@vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4<f32> {
    return vec4<f32>(f32((i << 1u) & 2u)*2.-1., f32(i & 2u)*2.-1., 0., 1.);
}
fn coord(uv: vec2<f32>, size: vec2<u32>) -> vec2<i32> {
    return clamp(vec2<i32>(floor(uv*vec2<f32>(size))), vec2<i32>(0), vec2<i32>(size)-1);
}
fn dep(uv: vec2<f32>) -> f32 { return textureLoad(depth, coord(uv, textureDimensions(depth)), 0); }
fn pos(uv: vec2<f32>, d: f32) -> vec3<f32> {
    let p = u.inv * vec4<f32>(uv.x*2.-1., 1.-uv.y*2., d, 1.); return p.xyz/p.w;
}
fn at(uv: vec2<f32>) -> vec3<f32> { return pos(uv, dep(uv)); }
fn value(uv: vec2<f32>) -> f32 { return textureLoad(source, coord(uv, textureDimensions(source)), 0).r; }
fn aligned(uv: vec2<f32>) -> vec2<f32> {
    return (vec2<f32>(coord(uv, textureDimensions(depth)))+0.5)/vec2<f32>(textureDimensions(depth));
}
fn size_ao() -> vec2<f32> { return ceil(vec2<f32>(textureDimensions(depth))/u.settings.w); }
@fragment fn horizon(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = aligned(frag.xy/size_ao()); let d = dep(uv);
    if d >= 1. { return vec4<f32>(1.); }
    let texel = 1./vec2<f32>(textureDimensions(depth)); let p = pos(uv,d);
    let r = at(uv+vec2<f32>(texel.x,0.))-p; let l = p-at(uv-vec2<f32>(texel.x,0.));
    let t = at(uv+vec2<f32>(0.,texel.y))-p; let b = p-at(uv-vec2<f32>(0.,texel.y));
    var n = normalize(cross(select(l,r,abs(r.z)<abs(l.z)),select(b,t,abs(t.z)<abs(b.z))));
    let eye = select(vec3<f32>(0.,0.,1.),normalize(-p),u.proj[2][3]< -0.5);
    if dot(n,eye)<0. { n = -n; }
    let radius=u.settings.x;
    let bias=max(radius*0.025,abs(pos(uv,min(d+4./16777216.,1.)).z-p.z));
    let pb=p+n*bias*2.;
    let tile=array<f32,16>(0.,8.,2.,10.,12.,4.,14.,6.,3.,11.,1.,9.,15.,7.,13.,5.);
    let c=vec2<u32>(frag.xy)&vec2<u32>(3u); let jitter=(tile[c.y*4u+c.x]+0.5)/16.;
    let steps=max(i32(u.settings.z)/4,2);
    let w=select(1.,-p.z,u.proj[2][3]< -0.5);
    let radius_uv=radius*0.5*vec2<f32>(u.proj[0][0],u.proj[1][1])/w;
    if radius_uv.x<texel.x { return vec4<f32>(1.); }
    var vis=0.; var sky=0.;
    for(var di=0;di<2;di++) {
        let phi=(f32(di)+jitter)*3.14159265/2.; let dir=vec2<f32>(cos(phi),sin(phi));
        let d3=vec3<f32>(dir,0.); let ortho=d3-dot(d3,eye)*eye; let axis=cross(d3,eye);
        let pn=n-axis*dot(n,axis); let plen=length(pn); if plen<0.0001 { continue; }
        let cn=clamp(dot(pn,eye)/plen,-1.,1.); let an=sign(dot(ortho,pn))*acos(cn);
        let initial=vec2<f32>(cos(an-1.5707963),cos(an+1.5707963)); var hc=initial;
        for(var s=0;s<steps;s++) {
            let f=(f32(s)+fract(jitter*7.+0.5))/f32(steps);
            let off=dir*max(radius_uv*f*f,texel*1.5)*vec2<f32>(1.,-1.);
            for(var side=0;side<2;side++) {
                let suv=uv+select(-off,off,side==1);
                if any(suv<vec2<f32>(0.)) || any(suv>vec2<f32>(1.)) || dep(suv)>=1. { continue; }
                let delta=at(suv)-pb; let dist=length(delta); if dist<0.000001 { continue; }
                let shc=dot(delta/dist,eye); let fall=1.-smoothstep(radius*0.5,radius*1.5,dist);
                hc[side]=max(hc[side],mix(initial[side],shc,fall));
            }
        }
        let h0=an+max(-acos(clamp(hc.x,-1.,1.))-an,-1.5707963);
        let h1=an+min(acos(clamp(hc.y,-1.,1.))-an,1.5707963);
        let sn=sin(an);
        vis+=plen*0.25*(-cos(2.*h0-an)-cos(2.*h1-an)+2.*cn+2.*(h0+h1)*sn);
        sky+=plen*(cn+an*sn);
    }
    vis=select(1.,clamp(vis/max(sky,0.0001),0.,1.),sky>0.0001);
    return vec4<f32>(vec3<f32>(mix(1.,vis,smoothstep(0.08,0.3,dot(n,eye)))),1.);
}
fn slope(z: f32, m: f32, p: f32) -> f32 { return select(z-m,p-z,abs(p-z)<abs(z-m)); }
fn blur(frag: vec4<f32>, spread: f32) -> vec4<f32> {
    let texel=1./size_ao(); let uv=aligned(frag.xy*texel); let z=at(uv).z;
    if dep(uv)>=1. { return vec4<f32>(1.); }
    let gx=slope(z,at(uv-vec2<f32>(texel.x,0.)).z,at(uv+vec2<f32>(texel.x,0.)).z);
    let gy=slope(z,at(uv-vec2<f32>(0.,texel.y)).z,at(uv+vec2<f32>(0.,texel.y)).z);
    let tol=max(u.settings.x*0.2,abs(z)*0.004); var sum=0.; var total=0.;
    for(var y=-2;y<2;y++) { for(var x=-2;x<2;x++) {
        let o=vec2<f32>(f32(x),f32(y))+0.5; let sample=uv+o*texel*spread;
        if dep(sample)<1. && abs(at(sample).z-z-dot(vec2<f32>(gx,gy),o)*spread)<tol {
            sum+=value(sample); total+=1.;
        }
    }}
    return vec4<f32>(vec3<f32>(select(value(uv),sum/max(total,1.),total>0.)),1.);
}
@fragment fn blur1(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> { return blur(p,1.); }
@fragment fn blur2(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> { return blur(p,2.); }
@fragment fn apply(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    let uv=frag.xy/vec2<f32>(textureDimensions(depth)); if dep(uv)>=1. { return vec4<f32>(1.); }
    let z=at(uv).z; let f=uv*size_ao()-0.5; let base=floor(f); let t=fract(f);
    let tol=max(u.settings.x*0.1,abs(z)*0.003); var sum=0.; var total=0.; var best=1e30; var nearest=1.;
    for(var j=0;j<2;j++) { for(var i=0;i<2;i++) {
        let sample=(base+vec2<f32>(f32(i),f32(j))+0.5)/size_ao();
        let dz=select(abs(at(aligned(sample)).z-z),1e30,dep(aligned(sample))>=1.);
        let a=value(sample); let bil=select(1.-t.x,t.x,i==1)*select(1.-t.y,t.y,j==1);
        let weight=bil*max(0.,1.-dz/tol)+0.00001*bil;
        if dz<tol { sum+=a*weight; total+=weight; } if dz<best { best=dz; nearest=a; }
    }}
    let v=clamp(select(nearest,sum/max(total,0.000001),total>0.000001),0.,1.);
    // Decode/encode follows the render target's linear colour convention.
    let a=clamp(textureLoad(color,coord(uv,textureDimensions(color)),0).rgb,vec3<f32>(0.),vec3<f32>(1.))*0.5;
    let lit=max(vec3<f32>(v),((v*(2.0404*a-0.3324)+(-4.7951*a+0.6417))*v+(2.7552*a+0.6903))*v);
    return vec4<f32>(max(vec3<f32>(0.3),1.-(1.-lit)*clamp(u.settings.y,0.,2.)),1.);
}
