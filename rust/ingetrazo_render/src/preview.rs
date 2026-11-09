//! Tool-owned triangles/edges and loose-face marks; empty by default.
use wgpu::util::DeviceExt;
pub struct Preview {
    pipelines: Vec<wgpu::RenderPipeline>,
    group: wgpu::BindGroup,
    triangles: Option<wgpu::Buffer>,
    edges: Option<wgpu::Buffer>,
    counts: [u32; 2],
}
impl Preview {
    pub fn new(
        d: &wgpu::Device,
        format: wgpu::TextureFormat,
        camera: &wgpu::Buffer,
        style: &wgpu::Buffer,
        kind: u32,
    ) -> Self {
        let marks = kind == 1;
        let ghost = kind == 2;
        let shader = d.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("tool previews"),
            source: wgpu::ShaderSource::Wgsl(include_str!("preview.wgsl").into()),
        });
        let bindings = d.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: None,
            entries: &[0, 1].map(|binding| wgpu::BindGroupLayoutEntry {
                binding,
                visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }),
        });
        let layout = d.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[&bindings],
            push_constant_ranges: &[],
        });
        let pipelines = [1,4].into_iter().flat_map(|samples| [false,true].map(|edge| {
            let constants = [("MARK".to_string(), if marks {1.} else {0.}), ("EDGE".to_string(), if edge {1.} else {0.}), ("GHOST".to_string(), if ghost {1.} else {0.})].into_iter().collect();
            d.create_render_pipeline(&wgpu::RenderPipelineDescriptor { label: Some("depth-tested tool preview"), layout: Some(&layout),
                vertex: wgpu::VertexState { module: &shader, entry_point: Some("vs"), compilation_options: wgpu::PipelineCompilationOptions { constants: &constants, ..Default::default() },
                    buffers: &[wgpu::VertexBufferLayout { array_stride: 28, step_mode: wgpu::VertexStepMode::Vertex,
                        attributes: &wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x3,2=>Unorm8x4] }] },
                fragment: Some(wgpu::FragmentState { module: &shader, entry_point: Some("fs"), compilation_options: wgpu::PipelineCompilationOptions { constants: &constants, ..Default::default() },
                    targets: &[Some(wgpu::ColorTargetState { format, blend: Some(wgpu::BlendState::ALPHA_BLENDING), write_mask: wgpu::ColorWrites::ALL })] }),
                primitive: wgpu::PrimitiveState { topology: if edge { wgpu::PrimitiveTopology::LineList } else { wgpu::PrimitiveTopology::TriangleList }, ..Default::default() },
                depth_stencil: Some(wgpu::DepthStencilState { format: wgpu::TextureFormat::Depth32Float, depth_write_enabled: !marks && !ghost && !edge,
                    depth_compare: wgpu::CompareFunction::LessEqual, stencil: Default::default(),
                    bias: wgpu::DepthBiasState { constant: if marks || edge {-2} else {0}, slope_scale: if marks || edge {-1.} else {0.}, clamp: 0. } }),
                multisample: wgpu::MultisampleState { count: samples, ..Default::default() }, multiview: None, cache: None })
        })).collect();
        let group = crate::bind(d, &bindings, &[camera, style]);
        Self {
            pipelines,
            group,
            triangles: None,
            edges: None,
            counts: [0; 2],
        }
    }
    pub fn upload(
        &mut self,
        d: &wgpu::Device,
        triangles: &[u8],
        edges: &[u8],
    ) -> Result<(), &'static str> {
        if triangles.len() % 84 != 0 || edges.len() % 56 != 0 {
            return Err("preview requires 28-byte triangle vertices and edge pairs");
        }
        for vertex in triangles.chunks_exact(28).chain(edges.chunks_exact(28)) {
            if vertex[..24]
                .chunks_exact(4)
                .any(|v| !f32::from_le_bytes(v.try_into().unwrap()).is_finite())
            {
                return Err("nonfinite preview vertex");
            }
        }
        let upload = |data: &[u8]| {
            (!data.is_empty()).then(|| {
                d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                    label: Some("transient mesh"),
                    contents: data,
                    usage: wgpu::BufferUsages::VERTEX,
                })
            })
        };
        self.triangles = upload(triangles);
        self.edges = upload(edges);
        self.counts = [(triangles.len() / 28) as u32, (edges.len() / 28) as u32];
        Ok(())
    }
    pub fn active(&self) -> bool {
        self.counts != [0; 2]
    }
    pub fn draw(
        &self,
        e: &mut wgpu::CommandEncoder,
        color: &wgpu::TextureView,
        depth: &wgpu::TextureView,
        resolve: Option<&wgpu::TextureView>,
    ) {
        if self.counts == [0; 2] {
            return;
        }
        let mut p = e.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("tool preview"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: color,
                resolve_target: resolve,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Load,
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                view: depth,
                depth_ops: Some(wgpu::Operations {
                    load: wgpu::LoadOp::Load,
                    store: wgpu::StoreOp::Store,
                }),
                stencil_ops: None,
            }),
            timestamp_writes: None,
            occlusion_query_set: None,
        });
        p.set_bind_group(0, &self.group, &[]);
        for (k, buffer) in [&self.triangles, &self.edges].into_iter().enumerate() {
            if let Some(buffer) = buffer {
                p.set_pipeline(&self.pipelines[usize::from(resolve.is_some()) * 2 + k]);
                p.set_vertex_buffer(0, buffer.slice(..));
                p.draw(0..self.counts[k], 0..1);
            }
        }
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn preview_and_marks_validate_on_metal_both_samples() {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::METAL,
            ..Default::default()
        });
        let Some(adapter) = pollster::block_on(instance.request_adapter(&Default::default()))
        else {
            return;
        };
        let (d, _) = pollster::block_on(adapter.request_device(&Default::default(), None)).unwrap();
        let camera = crate::buffer(&d, &[0; 112], wgpu::BufferUsages::UNIFORM);
        let style = crate::style::Style::new(&d);
        for kind in [0, 1, 2] {
            let mut preview = super::Preview::new(
                &d,
                wgpu::TextureFormat::Bgra8UnormSrgb,
                &camera,
                &style.buffer,
                kind,
            );
            assert!(preview.upload(&d, &[0; 83], &[]).is_err());
            preview.upload(&d, &[0; 84], &[0; 56]).unwrap();
            assert_eq!(preview.counts, [3, 2]);
            assert_eq!(preview.pipelines.len(), 4);
            preview.upload(&d, &[], &[]).unwrap();
            assert_eq!(preview.counts, [0, 0]);
        }
    }
}
