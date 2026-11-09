//! Draw the GL style's hazed sky/ground ramp before geometry, without depth or IDs.
pub struct Background {
    pipeline: wgpu::RenderPipeline,
    group: wgpu::BindGroup,
}
impl Background {
    pub fn new(
        d: &wgpu::Device,
        format: wgpu::TextureFormat,
        style: &wgpu::Buffer,
        samples: u32,
    ) -> Self {
        let shader = d.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("style background"),
            source: wgpu::ShaderSource::Wgsl(include_str!("background.wgsl").into()),
        });
        let pipeline = d.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("style background"),
            layout: None,
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: Default::default(),
            depth_stencil: None,
            multisample: wgpu::MultisampleState {
                count: samples,
                ..Default::default()
            },
            multiview: None,
            cache: None,
        });
        let group = crate::bind(d, &pipeline.get_bind_group_layout(0), &[style]);
        Self { pipeline, group }
    }
    pub fn draw(&self, e: &mut wgpu::CommandEncoder, view: &wgpu::TextureView, queries: Option<&wgpu::QuerySet>) {
        let mut pass = e.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("style background"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            timestamp_writes: crate::timing::writes(queries, "background"),
            occlusion_query_set: None,
        });
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, &self.group, &[]);
        pass.draw(0..3, 0..1);
    }
}
