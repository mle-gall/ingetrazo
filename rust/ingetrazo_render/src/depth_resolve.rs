//! AO consumes the nearest covered MSAA sample, without replaying geometry.
pub struct DepthResolve { pipeline: wgpu::RenderPipeline }
impl DepthResolve {
    pub fn new(device: &wgpu::Device) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("MSAA depth resolve"),
            source: wgpu::ShaderSource::Wgsl(r#"
@group(0) @binding(0) var source: texture_depth_multisampled_2d;
@vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4f {
 return vec4f(f32((i<<1u)&2u)*2.-1., f32(i&2u)*2.-1., 0., 1.);
}
@fragment fn fs(@builtin(position) p: vec4f) -> @builtin(frag_depth) f32 {
 let xy = vec2i(p.xy);
 return min(min(textureLoad(source,xy,0),textureLoad(source,xy,1)),
            min(textureLoad(source,xy,2),textureLoad(source,xy,3)));
}"#.into()),
        });
        Self { pipeline: device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("MSAA depth resolve"), layout: None,
            vertex: wgpu::VertexState { module: &shader, entry_point: Some("vs"), compilation_options: Default::default(), buffers: &[] },
            fragment: Some(wgpu::FragmentState { module: &shader, entry_point: Some("fs"), compilation_options: Default::default(), targets: &[] }),
            primitive: Default::default(),
            depth_stencil: Some(wgpu::DepthStencilState { format: wgpu::TextureFormat::Depth32Float, depth_write_enabled: true, depth_compare: wgpu::CompareFunction::Always, stencil: Default::default(), bias: Default::default() }),
            multisample: Default::default(), multiview: None, cache: None,
        }) }
    }
    pub fn draw(&self, device: &wgpu::Device, encoder: &mut wgpu::CommandEncoder, source: &wgpu::TextureView, target: &wgpu::TextureView) {
        let group = device.create_bind_group(&wgpu::BindGroupDescriptor { label: None,
            layout: &self.pipeline.get_bind_group_layout(0), entries: &[wgpu::BindGroupEntry { binding: 0, resource: wgpu::BindingResource::TextureView(source) }] });
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("MSAA depth resolve"), color_attachments: &[],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment { view: target,
                depth_ops: Some(wgpu::Operations { load: wgpu::LoadOp::Clear(1.), store: wgpu::StoreOp::Store }), stencil_ops: None }),
            timestamp_writes: None, occlusion_query_set: None,
        });
        pass.set_pipeline(&self.pipeline); pass.set_bind_group(0, &group, &[]); pass.draw(0..3, 0..1);
    }
}
