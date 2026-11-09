//! Cached closed-ring polygons, using the same topology as the GL viewport.
use wgpu::util::DeviceExt;
pub struct Sections {
    pipelines: Vec<wgpu::RenderPipeline>,
    group: wgpu::BindGroup,
    vertices: Option<wgpu::Buffer>,
    pub count: u32,
    bounds: [glam::Vec3; 2],
}
impl Sections {
    pub fn new(d: &wgpu::Device, format: wgpu::TextureFormat, camera: &wgpu::Buffer) -> Self {
        let shader = d.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("section polygons"),
            source: wgpu::ShaderSource::Wgsl(include_str!("sections.wgsl").into()),
        });
        let bind_layout = d.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: None, entries: &[wgpu::BindGroupLayoutEntry { binding: 0,
                visibility: wgpu::ShaderStages::VERTEX,
                ty: wgpu::BindingType::Buffer { ty: wgpu::BufferBindingType::Uniform, has_dynamic_offset: false, min_binding_size: None }, count: None }],
        });
        let layout = d.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor { label: None,
            bind_group_layouts: &[&bind_layout], push_constant_ranges: &[] });
        let pipelines: Vec<_> = [1, 4].into_iter().map(|count| d.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("section polygons"), layout: Some(&layout),
            vertex: wgpu::VertexState { module: &shader, entry_point: Some("vs"),
                compilation_options: Default::default(), buffers: &[wgpu::VertexBufferLayout {
                    array_stride: 24, step_mode: wgpu::VertexStepMode::Vertex,
                    attributes: &wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x3],
                }] },
            fragment: Some(wgpu::FragmentState { module: &shader, entry_point: Some("fs"),
                compilation_options: Default::default(), targets: &[Some(wgpu::ColorTargetState {
                    format, blend: None, write_mask: wgpu::ColorWrites::ALL,
                })] }),
            primitive: Default::default(), depth_stencil: Some(depth_state()),
            multisample: wgpu::MultisampleState { count, ..Default::default() }, multiview: None, cache: None,
        })).collect();
        let group = d.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None, layout: &pipelines[0].get_bind_group_layout(0),
            entries: &[wgpu::BindGroupEntry { binding: 0, resource: camera.as_entire_binding() }],
        });
        Self { pipelines, group, vertices: None, count: 0, bounds: [glam::Vec3::ZERO; 2] }
    }
    pub fn upload(&mut self, d: &wgpu::Device, data: &[u8]) {
        self.count = (data.len()/24) as u32;
        self.bounds = [glam::Vec3::splat(f32::INFINITY), glam::Vec3::splat(f32::NEG_INFINITY)];
        for vertex in data.chunks_exact(24) {
            let position = glam::Vec3::from_array(bytemuck::pod_read_unaligned::<[f32; 3]>(&vertex[..12]));
            self.bounds[0] = self.bounds[0].min(position);
            self.bounds[1] = self.bounds[1].max(position);
        }
        self.vertices = (!data.is_empty()).then(|| d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("cached section polygons"), contents: data, usage: wgpu::BufferUsages::VERTEX,
        }));
    }
    pub fn draw(&self, e: &mut wgpu::CommandEncoder, color: &wgpu::TextureView,
                depth: &wgpu::TextureView, resolve: Option<&wgpu::TextureView>, queries: Option<&wgpu::QuerySet>, camera: &[f32]) {
        let Some(vertices) = &self.vertices else { return; };
        let mut pass = e.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("section caps and boundaries"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment { view: color, resolve_target: resolve,
                ops: wgpu::Operations { load: wgpu::LoadOp::Load, store: wgpu::StoreOp::Store } })],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment { view: depth,
                depth_ops: Some(wgpu::Operations { load: wgpu::LoadOp::Load, store: wgpu::StoreOp::Store }), stencil_ops: None }),
            timestamp_writes: crate::timing::writes(queries, "section_caps"), occlusion_query_set: None,
        });
        if let Some([x, y, width, height]) = scissor(self.bounds, camera) {
            pass.set_scissor_rect(x, y, width, height);
        }
        pass.set_pipeline(&self.pipelines[usize::from(resolve.is_some())]);
        pass.set_bind_group(0, &self.group, &[]);
        pass.set_vertex_buffer(0, vertices.slice(..));
        pass.draw(0..self.count, 0..1);
    }
}
fn depth_state() -> wgpu::DepthStencilState {
    wgpu::DepthStencilState { format: wgpu::TextureFormat::Depth32Float, depth_write_enabled: true,
        depth_compare: wgpu::CompareFunction::LessEqual, stencil: Default::default(), bias: Default::default() }
}
#[cfg(test)]
mod tests {
    #[test]
    fn polygon_caps_write_depth_without_stencil_or_culling() {
        let state = super::depth_state();
        assert!(state.depth_write_enabled);
        assert_eq!(state.depth_compare, wgpu::CompareFunction::LessEqual);
        assert_eq!(state.stencil, wgpu::StencilState::default());
    }
}

// A projected world AABB conservatively bounds every cached cap and boundary.
// Near-plane crossings retain the full viewport instead of dividing by w <= 0.
fn scissor(bounds: [glam::Vec3; 2], camera: &[f32]) -> Option<[u32; 4]> {
    if camera.len() < 18 { return None; }
    let vp = glam::Mat4::from_cols_array(camera[..16].try_into().unwrap());
    let size = glam::Vec2::new(camera[16], camera[17]);
    let mut lo = size;
    let mut hi = glam::Vec2::ZERO;
    for k in 0..8 {
        let p = glam::Vec3::new(bounds[(k & 1) as usize].x,
            bounds[((k >> 1) & 1) as usize].y, bounds[((k >> 2) & 1) as usize].z);
        let q = vp * p.extend(1.);
        if !q.is_finite() || q.w <= 0. || q.z < 0. { return None; }
        let pixel = (glam::Vec2::new(q.x, -q.y) / q.w + glam::Vec2::ONE) * size * 0.5;
        lo = lo.min(pixel);
        hi = hi.max(pixel);
    }
    let lo = (lo.floor() - glam::Vec2::ONE).clamp(glam::Vec2::ZERO, size);
    let hi = (hi.ceil() + glam::Vec2::ONE).clamp(glam::Vec2::ZERO, size);
    let extent = hi - lo;
    if extent.min_element() <= 0. { return None; }
    Some([lo.x as u32, lo.y as u32, extent.x as u32, extent.y as u32])
}
#[cfg(test)]
mod scissor_tests {
    #[test]
    fn bounds_include_pixel_margin_and_flip_y() {
        let mut camera = glam::Mat4::IDENTITY.to_cols_array().to_vec();
        camera.extend([100., 200.]);
        assert_eq!(super::scissor([glam::Vec3::new(-0.5, 0., 0.2),
            glam::Vec3::new(0.5, 0.5, 0.8)], &camera), Some([24, 49, 52, 52]));
        assert_eq!(super::scissor([glam::Vec3::new(-0.5, 0., -0.2),
            glam::Vec3::new(0.5, 0.5, 0.8)], &camera), None);
    }
}
