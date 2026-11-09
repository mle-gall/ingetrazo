//! Order independent translucent faces; a separate face depth pass classifies edges.
pub struct Xray {
    pipeline: wgpu::RenderPipeline,
    texture_group: Option<wgpu::BindGroup>,
    composite: wgpu::RenderPipeline,
    groups: Option<(wgpu::BindGroup, wgpu::BindGroup)>,
    targets: [wgpu::Texture; 2],
    composite_group: wgpu::BindGroup,
}
impl Xray {
    fn targets(d: &wgpu::Device, w: u32, h: u32) -> [wgpu::Texture; 2] {
        [
            wgpu::TextureFormat::Rgba16Float,
            wgpu::TextureFormat::R16Float,
        ]
        .map(|format| {
            d.create_texture(&wgpu::TextureDescriptor {
                label: Some("X-ray OIT"),
                size: wgpu::Extent3d {
                    width: w,
                    height: h,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT
                    | wgpu::TextureUsages::TEXTURE_BINDING,
                view_formats: &[],
            })
        })
    }
    fn composite_group(
        d: &wgpu::Device,
        p: &wgpu::RenderPipeline,
        targets: &[wgpu::Texture; 2],
    ) -> wgpu::BindGroup {
        let views = targets
            .each_ref()
            .map(|t| t.create_view(&Default::default()));
        d.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("X-ray composite"),
            layout: &p.get_bind_group_layout(0),
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&views[0]),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&views[1]),
                },
            ],
        })
    }
    pub fn new(d: &wgpu::Device, format: wgpu::TextureFormat, w: u32, h: u32) -> Self {
        let shader = d.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("X-ray OIT"),
            source: wgpu::ShaderSource::Wgsl(
                concat!(
                    include_str!("shading.wgsl"),
                    "\n",
                    include_str!("xray.wgsl")
                )
                .into(),
            ),
        });
        let additive = wgpu::BlendComponent {
            src_factor: wgpu::BlendFactor::One,
            dst_factor: wgpu::BlendFactor::One,
            operation: wgpu::BlendOperation::Add,
        };
        let reveal = wgpu::BlendComponent {
            src_factor: wgpu::BlendFactor::Zero,
            dst_factor: wgpu::BlendFactor::OneMinusSrc,
            operation: wgpu::BlendOperation::Add,
        };
        let attrs = wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x3,2=>Unorm8x4];
        let pipeline = d.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("X-ray accumulation"),
            layout: None,
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[wgpu::VertexBufferLayout {
                    array_stride: 52,
                    step_mode: wgpu::VertexStepMode::Vertex,
                    attributes: &attrs,
                }, crate::textures::layout()],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("accumulate"),
                compilation_options: Default::default(),
                targets: &[
                    Some(wgpu::ColorTargetState {
                        format: wgpu::TextureFormat::Rgba16Float,
                        blend: Some(wgpu::BlendState {
                            color: additive,
                            alpha: additive,
                        }),
                        write_mask: wgpu::ColorWrites::ALL,
                    }),
                    Some(wgpu::ColorTargetState {
                        format: wgpu::TextureFormat::R16Float,
                        blend: Some(wgpu::BlendState {
                            color: reveal,
                            alpha: reveal,
                        }),
                        write_mask: wgpu::ColorWrites::ALL,
                    }),
                ],
            }),
            primitive: Default::default(),
            depth_stencil: None,
            multisample: Default::default(),
            multiview: None,
            cache: None,
        });
        let shader = d.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("X-ray composite"),
            source: wgpu::ShaderSource::Wgsl(include_str!("xray_composite.wgsl").into()),
        });
        let composite = d.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("X-ray composite"),
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
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: Default::default(),
            depth_stencil: None,
            multisample: Default::default(),
            multiview: None,
            cache: None,
        });
        let targets = Self::targets(d, w, h);
        let composite_group = Self::composite_group(d, &composite, &targets);
        Self {
            texture_group: None,            pipeline,
            composite,
            targets,
            composite_group,
            groups: None,
        }
    }
    pub fn resize(&mut self, d: &wgpu::Device, w: u32, h: u32) {
        self.targets = Self::targets(d, w, h);
        self.composite_group = Self::composite_group(d, &self.composite, &self.targets);
    }
    pub fn bind_textures(&mut self, d: &wgpu::Device, textures: &crate::textures::Textures) {
        self.texture_group = Some(textures.bind(d, &self.pipeline));
    }
    pub fn bind_scene(
        &mut self,
        d: &wgpu::Device,
        camera: &wgpu::Buffer,
        inst: &wgpu::Buffer,
        survivors: &wgpu::Buffer,
        style: &wgpu::Buffer,
    ) {
        self.groups = Some((
            crate::bind(
                d,
                &self.pipeline.get_bind_group_layout(0),
                &[camera, inst, survivors],
            ),
            crate::bind(d, &self.pipeline.get_bind_group_layout(1), &[style]),
        ));
    }
    pub fn draw(
        &self,
        e: &mut wgpu::CommandEncoder,
        color: &wgpu::TextureView,
        s: &crate::Scene,
        multi: bool,
    ) {
        let views = self
            .targets
            .each_ref()
            .map(|t| t.create_view(&Default::default()));
        let attachments = [0, 1].map(|i| {
            Some(wgpu::RenderPassColorAttachment {
                view: &views[i],
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(if i == 0 {
                        wgpu::Color::TRANSPARENT
                    } else {
                        wgpu::Color::WHITE
                    }),
                    store: wgpu::StoreOp::Store,
                },
            })
        });
        {
            let mut p = e.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("X-ray accumulation"),
                color_attachments: &attachments,
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            let groups = self.groups.as_ref().unwrap();
            p.set_pipeline(&self.pipeline);
            p.set_bind_group(0, &groups.0, &[]);
            p.set_bind_group(1, &groups.1, &[]);
            p.set_bind_group(2, self.texture_group.as_ref().unwrap(), &[]);
            p.set_vertex_buffer(0, s.vertex.slice(..));
            p.set_index_buffer(s.index.slice(..), wgpu::IndexFormat::Uint32);
            if multi {
                p.multi_draw_indexed_indirect(&s.commands, 0, s.p);
            } else {
                for i in 0..s.p {
                    p.draw_indexed_indirect(&s.commands, i as u64 * 20);
                }
            }
        }
        let mut p = e.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("X-ray composite"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: color,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Load,
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            timestamp_writes: None,
            occlusion_query_set: None,
        });
        p.set_pipeline(&self.composite);
        p.set_bind_group(0, &self.composite_group, &[]);
        p.draw(0..3, 0..1);
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn transmittance_and_average_are_order_independent() {
        fn blend(faces: &[[f32; 3]]) -> ([f32; 3], f32) {
            let mut sum = [0.; 3];
            let mut alpha = 0.;
            let mut reveal = 1.;
            for face in faces {
                for k in 0..3 {
                    sum[k] += face[k] * 0.6;
                }
                alpha += 0.6;
                reveal *= 0.4;
            }
            (sum.map(|v| v / alpha), 1. - reveal)
        }
        let a = blend(&[[1., 0., 0.], [0., 0., 1.]]);
        assert_eq!(a, blend(&[[0., 0., 1.], [1., 0., 0.]]));
        assert!((a.1 - 0.84).abs() < 1e-6);
        assert_eq!(a.0, [0.5, 0., 0.5]);
    }
}
