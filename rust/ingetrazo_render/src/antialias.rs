//! Color-only MSAA keeps the original single-sample ID path and picking semantics.
//! Geometry is replayed after IDs, trading GPU work for an isolated integration.
pub struct Antialias {
    pipelines: Vec<wgpu::RenderPipeline>,
    groups: Vec<(wgpu::BindGroup, wgpu::BindGroup)>,
    background: crate::background::Background,
    color: wgpu::Texture,
    depth: wgpu::Texture,
    format: wgpu::TextureFormat,
}
fn target(d: &wgpu::Device, w: u32, h: u32, format: wgpu::TextureFormat) -> wgpu::Texture {
    d.create_texture(&wgpu::TextureDescriptor {
        label: Some("4x MSAA"),
        size: wgpu::Extent3d {
            width: w,
            height: h,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 4,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
        view_formats: &[],
    })
}
impl Antialias {
    pub fn new(
        d: &wgpu::Device,
        format: wgpu::TextureFormat,
        style: &wgpu::Buffer,
        w: u32,
        h: u32,
    ) -> Self {
        let shader = d.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("4x MSAA shading"),
            source: wgpu::ShaderSource::Wgsl(concat!(include_str!("shading.wgsl"), "\n", include_str!("edges.wgsl")).into()),
        });
        let attrs = wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x3,2=>Unorm8x4,3=>Float32x3,4=>Float32x3];
        let pipelines = (0..4)
            .map(|k| {
                let edge = k >= 2;
                let xray = k % 2 == 1;
                d.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                    label: Some("4x MSAA geometry"),
                    layout: None,
                    vertex: wgpu::VertexState {
                        module: &shader,
                        entry_point: Some(if edge { "edge_vs" } else { "vs" }),
                        compilation_options: Default::default(),
                        buffers: &[wgpu::VertexBufferLayout {
                            array_stride: 52,
                            step_mode: wgpu::VertexStepMode::Vertex,
                            attributes: &attrs,
                        }],
                    },
                    fragment: Some(wgpu::FragmentState {
                        module: &shader,
                        entry_point: Some(if edge { "color_edge_fs" } else { "color_fs" }),
                        compilation_options: Default::default(),
                        targets: &[Some(wgpu::ColorTargetState {
                            format,
                            blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                            write_mask: wgpu::ColorWrites::ALL,
                        })],
                    }),
                    primitive: wgpu::PrimitiveState {
                        topology: if edge {
                            wgpu::PrimitiveTopology::TriangleList
                        } else {
                            wgpu::PrimitiveTopology::TriangleList
                        },
                        ..Default::default()
                    },
                    depth_stencil: Some(wgpu::DepthStencilState {
                        format: wgpu::TextureFormat::Depth32Float,
                        depth_write_enabled: !edge && !xray,
                        depth_compare: if edge && xray {
                            wgpu::CompareFunction::Always
                        } else {
                            wgpu::CompareFunction::LessEqual
                        },
                        stencil: Default::default(),
                        bias: if edge {
                            wgpu::DepthBiasState {
                                constant: -2,
                                slope_scale: -1.,
                                clamp: 0.,
                            }
                        } else {
                            Default::default()
                        },
                    }),
                    multisample: wgpu::MultisampleState {
                        count: 4,
                        ..Default::default()
                    },
                    multiview: None,
                    cache: None,
                })
            })
            .collect();
        Self {
            pipelines,
            groups: Vec::new(),
            background: crate::background::Background::new(d, format, style, 4),
            color: target(d, w, h, format),
            depth: target(d, w, h, wgpu::TextureFormat::Depth32Float),
            format,
        }
    }
    pub fn bind_scene(
        &mut self,
        d: &wgpu::Device,
        camera: &wgpu::Buffer,
        inst: &wgpu::Buffer,
        survivors: &wgpu::Buffer,
        style: &wgpu::Buffer,
    ) {
        self.groups = self
            .pipelines
            .iter()
            .map(|p| {
                (
                    crate::bind(d, &p.get_bind_group_layout(0), &[camera, inst, survivors]),
                    crate::bind(d, &p.get_bind_group_layout(1), &[style]),
                )
            })
            .collect();
    }
    pub fn resize(&mut self, d: &wgpu::Device, w: u32, h: u32) {
        self.color = target(d, w, h, self.format);
        self.depth = target(d, w, h, wgpu::TextureFormat::Depth32Float);
    }
    pub fn draw(
        &self,
        e: &mut wgpu::CommandEncoder,
        resolve: &wgpu::TextureView,
        scene: &crate::Scene,
        mode: u32,
        edges: bool,
        multi: bool,
        queries: Option<&wgpu::QuerySet>,
    ) {
        let color = self.color.create_view(&Default::default());
        let depth = self.depth.create_view(&Default::default());
        self.background.draw(e, &color);
        let mut pass = e.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("4x MSAA color resolve"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: &color,
                resolve_target: Some(resolve),
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Load,
                    store: wgpu::StoreOp::Discard,
                },
            })],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                view: &depth,
                depth_ops: Some(wgpu::Operations {
                    load: wgpu::LoadOp::Clear(1.),
                    store: wgpu::StoreOp::Discard,
                }),
                stencil_ops: None,
            }),
            timestamp_writes: queries.map(|q| wgpu::RenderPassTimestampWrites {
                query_set: q,
                beginning_of_pass_write_index: None,
                end_of_pass_write_index: Some(3),
            }),
            occlusion_query_set: None,
        });
        pass.set_vertex_buffer(0, scene.vertex.slice(..));
        pass.set_index_buffer(scene.index.slice(..), wgpu::IndexFormat::Uint32);
        for edge in [false, true] {
            if (!edge && mode == 4) || (edge && !edges && mode != 4) {
                continue;
            }
            let k = usize::from(edge) * 2 + usize::from(mode == 1);
            pass.set_pipeline(&self.pipelines[k]);
            pass.set_bind_group(0, &self.groups[k].0, &[]);
            pass.set_bind_group(1, &self.groups[k].1, &[]);
            let first = if edge { scene.p } else { 0 };
            if multi {
                pass.multi_draw_indexed_indirect(&scene.commands, first as u64 * 20, scene.p);
            } else {
                for j in first..first + scene.p {
                    pass.draw_indexed_indirect(&scene.commands, j as u64 * 20);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn metal_validates_background_and_multisample_pipelines() {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::METAL,
            ..Default::default()
        });
        let Some(adapter) = pollster::block_on(instance.request_adapter(&Default::default())) else {
            return;
        };
        let (device, _) = pollster::block_on(adapter.request_device(&Default::default(), None)).unwrap();
        let style = crate::style::Style::new(&device);
        let _xray = crate::xray::Xray::new(&device, wgpu::TextureFormat::Bgra8UnormSrgb, 64, 64);
        let _passes = super::Antialias::new(&device, wgpu::TextureFormat::Bgra8UnormSrgb,
            &style.buffer, 64, 64);
    }
}
