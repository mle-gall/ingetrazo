//! Depth-based horizon AO. No geometry or picking state is owned by this pass.
use pyo3::{exceptions::PyValueError, prelude::*, types::PyDict};
pub struct AmbientOcclusion {
    pub enabled: bool,
    settings: [f32; 4],
    proj: glam::Mat4,
    uniform: wgpu::Buffer,
    layout: wgpu::BindGroupLayout,
    pipelines: Vec<wgpu::RenderPipeline>,
    targets: Option<(u32, u32, u32, wgpu::Texture, wgpu::Texture, wgpu::Texture)>,
    format: wgpu::TextureFormat,
}
fn target(d: &wgpu::Device, w: u32, h: u32, format: wgpu::TextureFormat) -> wgpu::Texture {
    d.create_texture(&wgpu::TextureDescriptor {
        label: Some("AO target"),
        size: wgpu::Extent3d {
            width: w,
            height: h,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage: wgpu::TextureUsages::TEXTURE_BINDING
            | wgpu::TextureUsages::RENDER_ATTACHMENT
            | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    })
}
impl AmbientOcclusion {
    pub fn new(d: &wgpu::Device, format: wgpu::TextureFormat) -> Self {
        let uniform = d.create_buffer(&wgpu::BufferDescriptor {
            label: Some("AO parameters"),
            size: 144,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let entries = (0..4)
            .map(|i| wgpu::BindGroupLayoutEntry {
                binding: i,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: if i == 0 {
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    }
                } else {
                    wgpu::BindingType::Texture {
                        sample_type: if i == 1 {
                            wgpu::TextureSampleType::Depth
                        } else {
                            wgpu::TextureSampleType::Float { filterable: false }
                        },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    }
                },
                count: None,
            })
            .collect::<Vec<_>>();
        let layout = d.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("AO inputs"),
            entries: &entries,
        });
        let pl = d.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[&layout],
            push_constant_ranges: &[],
        });
        let shader = d.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("horizon AO"),
            source: wgpu::ShaderSource::Wgsl(include_str!("ao.wgsl").into()),
        });
        let pipelines = ["horizon", "blur1", "blur2", "apply", "apply"]
            .iter()
            .enumerate()
            .map(|(i, entry)| {
                d.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                    label: Some(entry),
                    layout: Some(&pl),
                    vertex: wgpu::VertexState {
                        module: &shader,
                        entry_point: Some("vs"),
                        compilation_options: Default::default(),
                        buffers: &[],
                    },
                    fragment: Some(wgpu::FragmentState {
                        module: &shader,
                        entry_point: Some(entry),
                        compilation_options: Default::default(),
                        targets: &[Some(wgpu::ColorTargetState {
                            format: if i < 3 {
                                wgpu::TextureFormat::Rgba16Float
                            } else {
                                format
                            },
                            blend: if i < 3 {
                                None
                            } else {
                                Some(wgpu::BlendState {
                                    color: wgpu::BlendComponent {
                                        src_factor: wgpu::BlendFactor::Zero,
                                        dst_factor: wgpu::BlendFactor::Src,
                                        operation: wgpu::BlendOperation::Add,
                                    },
                                    alpha: wgpu::BlendComponent {
                                        src_factor: wgpu::BlendFactor::Zero,
                                        dst_factor: wgpu::BlendFactor::One,
                                        operation: wgpu::BlendOperation::Add,
                                    },
                                })
                            },
                            write_mask: wgpu::ColorWrites::ALL,
                        })],
                    }),
                    primitive: Default::default(),
                    depth_stencil: None,
                    multisample: wgpu::MultisampleState {
                        count: if i == 4 { 4 } else { 1 },
                        ..Default::default()
                    },
                    multiview: None,
                    cache: None,
                })
            })
            .collect();
        Self {
            enabled: false,
            settings: [0.5, 1., 16., 2.],
            proj: glam::Mat4::IDENTITY,
            uniform,
            layout,
            pipelines,
            targets: None,
            format,
        }
    }
    pub fn update(&mut self, value: &Bound<'_, PyAny>) -> PyResult<()> {
        if let Ok(d) = value.cast::<PyDict>() {
            let mut settings = self.settings;
            for (i, key) in ["ao_distance", "ao_intensity", "ao_samples", "ao_resolution"]
                .iter()
                .enumerate()
            {
                if let Some(v) = d.get_item(key)? {
                    settings[i] = v.extract()?;
                }
            }
            if settings.iter().any(|v| !v.is_finite())
                || settings[0] <= 0.
                || !(0. ..=2.).contains(&settings[1])
                || !(4. ..=64.).contains(&settings[2])
                || ![1., 2.].contains(&settings[3])
            {
                return Err(PyValueError::new_err("invalid AO parameters"));
            }
            let enabled = d
                .get_item("ambient_occlusion")?
                .map(|v| v.extract())
                .transpose()?
                .unwrap_or(self.enabled);
            self.settings = settings;
            self.enabled = enabled;
        }
        Ok(())
    }
    pub fn camera(&mut self, proj: glam::Mat4) {
        self.proj = proj;
    }
    pub fn active(&self, mode: u32) -> bool {
        self.enabled && mode != 1 && mode != 4
    }
    pub fn draw(
        &mut self,
        d: &wgpu::Device,
        q: &wgpu::Queue,
        e: &mut wgpu::CommandEncoder,
        scene: &wgpu::Texture,
        depth: &wgpu::TextureView,
        output: &wgpu::TextureView,
        msaa: bool,
    ) {
        let (w, h, scale) = (scene.width(), scene.height(), self.settings[3] as u32);
        if self.targets.as_ref().map(|t| (t.0, t.1, t.2)) != Some((w, h, scale)) {
            self.targets = Some((
                w,
                h,
                scale,
                target(
                    d,
                    w.div_ceil(scale),
                    h.div_ceil(scale),
                    wgpu::TextureFormat::Rgba16Float,
                ),
                target(
                    d,
                    w.div_ceil(scale),
                    h.div_ceil(scale),
                    wgpu::TextureFormat::Rgba16Float,
                ),
                target(d, w, h, self.format),
            ));
        }
        let t = self.targets.as_ref().unwrap();
        e.copy_texture_to_texture(scene.as_image_copy(), t.5.as_image_copy(), scene.size());
        let mut data = self.proj.to_cols_array().to_vec();
        data.extend(self.proj.inverse().to_cols_array());
        data.extend(self.settings);
        q.write_buffer(&self.uniform, 0, bytemuck::cast_slice(&data));
        let a = t.3.create_view(&Default::default());
        let b = t.4.create_view(&Default::default());
        let color = t.5.create_view(&Default::default());
        for (i, src, dst) in [
            (0, &b, &a),
            (1, &a, &b),
            (2, &b, &a),
            (if msaa { 4 } else { 3 }, &a, output),
        ] {
            let group = d.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("AO inputs"),
                layout: &self.layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: self.uniform.as_entire_binding(),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::TextureView(depth),
                    },
                    wgpu::BindGroupEntry {
                        binding: 2,
                        resource: wgpu::BindingResource::TextureView(src),
                    },
                    wgpu::BindGroupEntry {
                        binding: 3,
                        resource: wgpu::BindingResource::TextureView(&color),
                    },
                ],
            });
            let mut pass = e.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("AO"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: dst,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: if i < 3 {
                            wgpu::LoadOp::Clear(wgpu::Color::WHITE)
                        } else {
                            wgpu::LoadOp::Load
                        },
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            pass.set_pipeline(&self.pipelines[i]);
            pass.set_bind_group(0, &group, &[]);
            pass.draw(0..3, 0..1);
        }
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn metal_validates_ao() {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::METAL,
            ..Default::default()
        });
        let Some(adapter) = pollster::block_on(instance.request_adapter(&Default::default()))
        else {
            return;
        };
        let (d, _) = pollster::block_on(adapter.request_device(&Default::default(), None)).unwrap();
        let _ao = super::AmbientOcclusion::new(&d, wgpu::TextureFormat::Bgra8UnormSrgb);
    }
    #[test]
    fn synthetic_depth_plane_and_corner() {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::METAL,
            ..Default::default()
        });
        let Some(adapter) = pollster::block_on(instance.request_adapter(&Default::default()))
        else {
            return;
        };
        let (d, q) = pollster::block_on(adapter.request_device(&Default::default(), None)).unwrap();
        let mut ao = super::AmbientOcclusion::new(&d, wgpu::TextureFormat::Rgba8Unorm);
        ao.settings = [0.5, 1., 32., 1.];
        ao.camera(glam::Mat4::orthographic_rh(-1., 1., -1., 1., 0.1, 4.));
        let scene = crate::texture(&d, 64, 64, wgpu::TextureFormat::Rgba8Unorm);
        let depth = crate::texture(&d, 64, 64, wgpu::TextureFormat::Depth32Float);
        let cv = scene.create_view(&Default::default());
        let dv = depth.create_view(&Default::default());
        let mut results = Vec::new();
        for corner in [false, true] {
            let fragment = if corner {
                "return (2.0-abs(p.x/32.0-1.0)-0.1)/3.9;"
            } else {
                "return 1.9/3.9;"
            };
            let code=format!("@vertex fn vs(@builtin(vertex_index) i:u32)->@builtin(position) vec4<f32>{{return vec4<f32>(f32((i<<1u)&2u)*2.-1.,f32(i&2u)*2.-1.,0.,1.);}} @fragment fn fs(@builtin(position) p:vec4<f32>)->@builtin(frag_depth) f32{{{fragment}}}");
            let shader = d.create_shader_module(wgpu::ShaderModuleDescriptor {
                label: None,
                source: wgpu::ShaderSource::Wgsl(code.into()),
            });
            let pipeline = d.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: None,
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
                    targets: &[],
                }),
                primitive: Default::default(),
                depth_stencil: Some(wgpu::DepthStencilState {
                    format: wgpu::TextureFormat::Depth32Float,
                    depth_write_enabled: true,
                    depth_compare: wgpu::CompareFunction::Always,
                    stencil: Default::default(),
                    bias: Default::default(),
                }),
                multisample: Default::default(),
                multiview: None,
                cache: None,
            });
            let mut e = d.create_command_encoder(&Default::default());
            {
                let _pass = e.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: None,
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &cv,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(wgpu::Color::WHITE),
                            store: wgpu::StoreOp::Store,
                        },
                    })],
                    depth_stencil_attachment: None,
                    timestamp_writes: None,
                    occlusion_query_set: None,
                });
            }
            {
                let mut pass = e.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: None,
                    color_attachments: &[],
                    depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                        view: &dv,
                        depth_ops: Some(wgpu::Operations {
                            load: wgpu::LoadOp::Clear(1.),
                            store: wgpu::StoreOp::Store,
                        }),
                        stencil_ops: None,
                    }),
                    timestamp_writes: None,
                    occlusion_query_set: None,
                });
                pass.set_pipeline(&pipeline);
                pass.draw(0..3, 0..1);
            }
            ao.draw(&d, &q, &mut e, &scene, &dv, &cv, false);
            let read = d.create_buffer(&wgpu::BufferDescriptor {
                label: None,
                size: 64 * 256,
                usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                mapped_at_creation: false,
            });
            e.copy_texture_to_buffer(
                scene.as_image_copy(),
                wgpu::TexelCopyBufferInfo {
                    buffer: &read,
                    layout: wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some(256),
                        rows_per_image: None,
                    },
                },
                scene.size(),
            );
            q.submit(Some(e.finish()));
            let (tx, rx) = std::sync::mpsc::channel();
            read.slice(..)
                .map_async(wgpu::MapMode::Read, move |r| tx.send(r).unwrap());
            d.poll(wgpu::Maintain::Wait);
            rx.recv().unwrap().unwrap();
            let bytes = read.slice(..).get_mapped_range();
            results.push(bytes[32 * 256 + 32 * 4]);
        }
        assert!(results[0] >= 254, "flat plane self-occluded: {:?}", results);
        assert!(
            results[1] < results[0] - 10 && results[1] > 76,
            "corner must darken softly: {:?}",
            results
        );
    }
}
