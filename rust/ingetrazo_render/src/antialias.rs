//! Faces and edges render once to MSAA attachments; color resolves at pass end.
//! Single-sample IDs are independent; AO uses a fullscreen depth resolve.
pub struct Antialias {
    pipelines: Vec<wgpu::RenderPipeline>,
    texture_groups: Vec<wgpu::BindGroup>,
    groups: Vec<(wgpu::BindGroup, wgpu::BindGroup)>,
    background: crate::background::Background,
    color: wgpu::Texture,
    depth: wgpu::Texture,
    format: wgpu::TextureFormat,
    depth_resolve: crate::depth_resolve::DepthResolve,
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
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
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
        let face_attrs = wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x3,2=>Unorm8x4];
        let pipelines = (0..8)
            .map(|k| {
                let edge = (2..6).contains(&k);
                let xray = k % 2 == 1;
                d.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                    label: Some("4x MSAA geometry"),
                    layout: None,
                    vertex: wgpu::VertexState {
                        module: &shader,
                        entry_point: Some(if edge { "edge_vs" } else { "vs" }),
                        compilation_options: wgpu::PipelineCompilationOptions { constants: &[("PROFILES".to_string(), if (4..6).contains(&k) { 0. } else { 1. })].into_iter().collect(), ..Default::default() },
                        buffers: &{ let layouts = if edge { vec![] } else { vec![wgpu::VertexBufferLayout {
                            array_stride: 28,
                            step_mode: wgpu::VertexStepMode::Vertex,
                            attributes: &face_attrs,
                        }] }; layouts },
                    },
                    fragment: Some(wgpu::FragmentState {
                        module: &shader,
                        entry_point: Some(if edge { "color_edge_fs" } else { "color_fs" }),
                        compilation_options: wgpu::PipelineCompilationOptions { constants: &[("TEXTURED".to_string(), if k >= 6 { 0. } else { 1. })].into_iter().collect(), ..Default::default() },
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
            texture_groups: Vec::new(),
            groups: Vec::new(),
            background: crate::background::Background::new(d, format, style, 4),
            color: target(d, w, h, format),
            depth: target(d, w, h, wgpu::TextureFormat::Depth32Float),
            format,
            depth_resolve: crate::depth_resolve::DepthResolve::new(d),
        }
    }
    pub fn bind_textures(&mut self, d: &wgpu::Device, textures: &crate::textures::Textures) {
        self.texture_groups = [0,1,6,7].iter().map(|&k| textures.bind(d,&self.pipelines[k])).collect();
    }
    pub fn bind_scene(
        &mut self,
        d: &wgpu::Device,
        camera: &wgpu::Buffer,
        inst: &wgpu::Buffer,
        survivors: &wgpu::Buffer,
        style: &wgpu::Buffer,
        edges: &wgpu::Buffer,
        viewpoints: &wgpu::Buffer,
    ) {
        self.groups = self
            .pipelines
            .iter()
            .enumerate().map(|(k,p)| {
                let buffers = [camera, inst, survivors, edges, viewpoints];
                (
                    crate::bind(d, &p.get_bind_group_layout(0), &buffers[..if (2..6).contains(&k) { 5 } else { 3 }]),
                    crate::bind(d, &p.get_bind_group_layout(1), &[style]),
                )
            })
            .collect();
    }
    pub fn resize(&mut self, d: &wgpu::Device, w: u32, h: u32) {
        self.color = target(d, w, h, self.format);
        self.depth = target(d, w, h, wgpu::TextureFormat::Depth32Float);
    }
    pub fn resolve_depth(&self, d: &wgpu::Device, e: &mut wgpu::CommandEncoder, target: &wgpu::TextureView) {
        self.depth_resolve.draw(d, e, &self.depth.create_view(&Default::default()), target);
    }
    pub fn color_view(&self) -> wgpu::TextureView { self.color.create_view(&Default::default()) }
    pub fn draw(
        &self,
        e: &mut wgpu::CommandEncoder,
        resolve: &wgpu::TextureView,
        scene: &crate::Scene,
        mode: u32,
        edges: bool,
        profiles: bool,
        multi: bool,
        queries: Option<&wgpu::QuerySet>,
        edge_only: Option<bool>,
    ) {
        let color = self.color.create_view(&Default::default());
        let depth = self.depth.create_view(&Default::default());
        if edge_only != Some(true) { self.background.draw(e, &color, None); }
        let mut pass = e.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("4x MSAA color resolve"),
            color_attachments: &[Some(color_attachment(&color, resolve, edge_only == Some(false)))],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                view: &depth,
                depth_ops: Some(wgpu::Operations {
                    load: if edge_only == Some(true) { wgpu::LoadOp::Load } else { wgpu::LoadOp::Clear(1.) },
                    store: if edge_only == Some(false) { wgpu::StoreOp::Store } else { wgpu::StoreOp::Discard },
                }),
                stencil_ops: None,
            }),
            timestamp_writes: crate::timing::writes(queries, if edge_only == Some(true) { "antialias_edges" } else { "antialias" }),
            occlusion_query_set: None,
        });
        pass.set_vertex_buffer(0, scene.vertex.slice(..));
        pass.set_index_buffer(scene.index.slice(..), wgpu::IndexFormat::Uint32);
        for &edge in geometry_stages(edge_only) {
            if (!edge && mode == 4) || (edge && !edges && mode != 4) {
                continue;
            }
            let k = if edge && !profiles { 4 + usize::from(mode == 1) } else { usize::from(edge) * 2 + usize::from(mode == 1) };
            pass.set_pipeline(&self.pipelines[k]);
            if !edge { pass.set_bind_group(2, &self.texture_groups[k], &[]); }
            pass.set_bind_group(0, &self.groups[k].0, &[]);
            pass.set_bind_group(1, &self.groups[k].1, &[]);
            let first = if edge { scene.p } else { 0 };
            if edge {
                for j in first..first + scene.p { pass.draw_indirect(&scene.commands, j as u64 * 20); }
            } else {
                for &(first, count, plain) in &scene.face_ranges {
                    let face = if plain { 6 + usize::from(mode == 1) } else { k };
                    pass.set_pipeline(&self.pipelines[face]);
                    pass.set_bind_group(0, &self.groups[face].0, &[]);
                    pass.set_bind_group(1, &self.groups[face].1, &[]);
                    pass.set_bind_group(2, &self.texture_groups[if plain { face-4 } else { face }], &[]);
                    if multi { pass.multi_draw_indexed_indirect(&scene.commands, first as u64 * 20, count); }
                    else { for j in first..first+count { pass.draw_indexed_indirect(&scene.commands, j as u64 * 20); } }
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
        let (device, _queue) = pollster::block_on(adapter.request_device(&Default::default(), None)).unwrap();
        let style = crate::style::Style::new(&device);
        let _xray = crate::xray::Xray::new(&device, wgpu::TextureFormat::Bgra8UnormSrgb, 64, 64);
        let passes = super::Antialias::new(&device, wgpu::TextureFormat::Bgra8UnormSrgb,
            &style.buffer, 64, 64);
        assert_eq!(passes.color.sample_count(), 4);
        assert_eq!(passes.depth.sample_count(), 4);
        let resolve = crate::texture(&device, 64, 64, wgpu::TextureFormat::Bgra8UnormSrgb);
        assert_eq!(resolve.sample_count(), 1);
        let color = passes.color_view();
        let target = resolve.create_view(&Default::default());
        for preserve in [false, true] {
            let attachment = super::color_attachment(&color, &target, preserve);
            assert!(attachment.resolve_target.is_some());
            assert_eq!(attachment.ops.store, if preserve { wgpu::StoreOp::Store } else { wgpu::StoreOp::Discard });
        }
        let depth = crate::texture(&device, 64, 64, wgpu::TextureFormat::Depth32Float);
        let mut encoder = device.create_command_encoder(&Default::default());
        passes.resolve_depth(&device, &mut encoder, &depth.create_view(&Default::default()));
        let _ = encoder.finish();
    }
}

fn geometry_stages(edge_only: Option<bool>) -> &'static [bool] {
    match edge_only { Some(false) => &[false], Some(true) => &[true], None => &[false, true] }
}
#[cfg(test)]
mod resolve_tests {
    #[test]
    fn geometry_is_submitted_once_with_or_without_ao_boundary() {
        assert_eq!(super::geometry_stages(None), &[false,true]);
        let ao: Vec<_> = [Some(false),Some(true)].into_iter()
            .flat_map(super::geometry_stages).copied().collect();
        assert_eq!(ao, super::geometry_stages(None));
    }
}

fn color_attachment<'a>(color: &'a wgpu::TextureView, resolve: &'a wgpu::TextureView, preserve: bool) -> wgpu::RenderPassColorAttachment<'a> {
    wgpu::RenderPassColorAttachment { view: color, resolve_target: Some(resolve),
        ops: wgpu::Operations { load: wgpu::LoadOp::Load,
            store: if preserve { wgpu::StoreOp::Store } else { wgpu::StoreOp::Discard } } }
}
