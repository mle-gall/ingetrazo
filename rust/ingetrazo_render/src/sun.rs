//! Cached, camera-independent sun depth map; optional opaque/ground receiver.
use pyo3::{exceptions::PyValueError, prelude::*, types::PyDict};
pub struct Sun {
    pub enabled: bool,
    dirty: bool,
    direction: [f32; 3],
    matrix: [f32; 16],
    darkness: f32,
    ground: bool,
    map: wgpu::Texture,
    caster: wgpu::RenderPipeline,
    receivers: Vec<wgpu::RenderPipeline>,
    uniform: wgpu::Buffer,
    sampler: wgpu::Sampler,
}
impl Sun {
    pub fn new(d: &wgpu::Device, format: wgpu::TextureFormat) -> Self {
        let shader = d.create_shader_module(wgpu::ShaderModuleDescriptor { label: Some("sun caster"),
            source: wgpu::ShaderSource::Wgsl(concat!(include_str!("shading.wgsl"), "\n@fragment fn shadow_fs(i: Out, @builtin(front_facing) front: bool) { let alpha = face_pixel(i,front).color.a; if (inst[i.id-1u].info.z & 129u) != 0u || alpha < 0.7 { discard; } }").into()) });
        let caster = d.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("sun depth map"),
            layout: None,
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[wgpu::VertexBufferLayout {
                    array_stride: 28,
                    step_mode: wgpu::VertexStepMode::Vertex,
                    attributes: &wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x3,2=>Unorm8x4],
                }],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("shadow_fs"),
                compilation_options: Default::default(),
                targets: &[],
            }),
            primitive: Default::default(),
            depth_stencil: Some(wgpu::DepthStencilState {
                format: wgpu::TextureFormat::Depth32Float,
                depth_write_enabled: true,
                depth_compare: wgpu::CompareFunction::Less,
                stencil: Default::default(),
                bias: wgpu::DepthBiasState {
                    constant: 2,
                    slope_scale: 2.,
                    clamp: 0.,
                },
            }),
            multisample: Default::default(),
            multiview: None,
            cache: None,
        });
        let shader = d.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("sun receiver"),
            source: wgpu::ShaderSource::Wgsl(include_str!("sun.wgsl").into()),
        });
        let layout = d.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: None,
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Depth,
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Depth,
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 3,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Comparison),
                    count: None,
                },
            ],
        });
        let pl = d.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[&layout],
            push_constant_ranges: &[],
        });
        let receivers = [1, 4]
            .into_iter()
            .map(|count| {
                d.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                    label: Some("sun and ground shadows"),
                    layout: Some(&pl),
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
                            blend: Some(wgpu::BlendState {
                                color: wgpu::BlendComponent {
                                    src_factor: wgpu::BlendFactor::Zero,
                                    dst_factor: wgpu::BlendFactor::Src,
                                    operation: wgpu::BlendOperation::Add,
                                },
                                alpha: wgpu::BlendComponent::REPLACE,
                            }),
                            write_mask: wgpu::ColorWrites::COLOR,
                        })],
                    }),
                    primitive: Default::default(),
                    depth_stencil: None,
                    multisample: wgpu::MultisampleState {
                        count,
                        ..Default::default()
                    },
                    multiview: None,
                    cache: None,
                })
            })
            .collect();
        Self {
            enabled: false,
            dirty: true,
            direction: [0., 0., 1.],
            matrix: glam::Mat4::IDENTITY.to_cols_array(),
            darkness: 0.55,
            ground: true,
            map: crate::texture(d, 2048, 2048, wgpu::TextureFormat::Depth32Float),
            caster,
            receivers,
            uniform: crate::buffer(
                d,
                &[0; 160],
                wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            ),
            sampler: d.create_sampler(&wgpu::SamplerDescriptor {
                compare: Some(wgpu::CompareFunction::LessEqual),
                mag_filter: wgpu::FilterMode::Linear,
                min_filter: wgpu::FilterMode::Linear,
                ..Default::default()
            }),
        }
    }
    pub fn invalidate(&mut self) {
        self.dirty = true;
    }
    pub fn update(&mut self, value: &Bound<'_, PyAny>) -> PyResult<()> {
        let Ok(d) = value.cast::<PyDict>() else {
            self.enabled = false;
            return Ok(());
        };
        let enabled = d
            .get_item("shadows")?
            .map(|v| v.extract::<bool>())
            .transpose()?
            .unwrap_or(false);
        let direction = d
            .get_item("sun_direction")?
            .map(|v| v.extract::<[f32; 3]>())
            .transpose()?
            .unwrap_or([0., 0., 1.]);
        let matrix = d
            .get_item("shadow_matrix")?
            .map(|v| v.extract::<[f32; 16]>())
            .transpose()?
            .unwrap_or(glam::Mat4::IDENTITY.to_cols_array());
        let darkness = d
            .get_item("shadow_darkness")?
            .map(|v| v.extract::<f32>())
            .transpose()?
            .unwrap_or(0.55);
        let ground = d
            .get_item("ground_shadows")?
            .map(|v| v.extract::<bool>())
            .transpose()?
            .unwrap_or(true);
        if !darkness.is_finite()
            || !(0. ..=1.).contains(&darkness)
            || direction
                .iter()
                .chain(matrix.iter())
                .any(|v| !v.is_finite())
            || glam::Vec3::from(direction).length_squared() < 1e-12
        {
            return Err(PyValueError::new_err("invalid sun payload"));
        }
        let direction = glam::Vec3::from(direction).normalize().to_array();
        self.dirty |=
            self.matrix != matrix || self.direction != direction || self.enabled != enabled;
        self.enabled = enabled;
        self.matrix = matrix;
        self.direction = direction;
        self.darkness = darkness;
        self.ground = ground;
        Ok(())
    }
    pub fn prepare(
        &mut self,
        d: &wgpu::Device,
        q: &wgpu::Queue,
        e: &mut wgpu::CommandEncoder,
        s: &crate::Scene,
        textures: &crate::textures::Textures,
        style: &wgpu::Buffer,
    ) {
        if !self.enabled || !self.dirty {
            return;
        }
        let conversion = glam::Mat4::from_cols(
            glam::Vec4::X,
            glam::Vec4::Y,
            glam::Vec4::new(0., 0., 0.5, 0.),
            glam::Vec4::new(0., 0., 0.5, 1.),
        );
        let mut camera = (conversion * glam::Mat4::from_cols_array(&self.matrix))
            .to_cols_array()
            .to_vec();
        camera.extend([2048., 2048., 0., 0.]);
        let camera = crate::buffer(
            d,
            bytemuck::cast_slice(&camera),
            wgpu::BufferUsages::UNIFORM,
        );
        let mut rows = vec![Vec::new(); s.p as usize];
        for (i, row) in s.rows.chunks_exact(80).enumerate() {
            rows[u32::from_le_bytes(row[64..68].try_into().unwrap()) as usize].push(i as u32);
        }
        let mut survivors = Vec::new();
        let mut commands = Vec::new();
        for (id, rows) in rows.iter().enumerate() {
            let mut c: crate::Command =
                bytemuck::pod_read_unaligned(&s.template_data[id * 20..id * 20 + 20]);
            c.start = survivors.len() as u32;
            c.instances = rows.len() as u32;
            survivors.extend(rows);
            commands.push(c);
        }
        if survivors.is_empty() {
            survivors.push(0u32);
        }
        let survivors = crate::buffer(
            d,
            bytemuck::cast_slice(&survivors),
            wgpu::BufferUsages::STORAGE,
        );
        let group = crate::bind(
            d,
            &self.caster.get_bind_group_layout(0),
            &[&camera, &s.inst, &survivors],
        );
        let look = crate::bind(d, &self.caster.get_bind_group_layout(1), &[style]);
        let materials = textures.bind(d, &self.caster);
        let map = self.map.create_view(&Default::default());
        let mut p = e.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("sun map"),
            color_attachments: &[],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                view: &map,
                depth_ops: Some(wgpu::Operations {
                    load: wgpu::LoadOp::Clear(1.),
                    store: wgpu::StoreOp::Store,
                }),
                stencil_ops: None,
            }),
            timestamp_writes: None,
            occlusion_query_set: None,
        });
        p.set_pipeline(&self.caster);
        p.set_bind_group(0, &group, &[]);
        p.set_bind_group(1, &look, &[]);
        p.set_bind_group(2, &materials, &[]);
        p.set_vertex_buffer(0, s.vertex.slice(..));
        p.set_index_buffer(s.index.slice(..), wgpu::IndexFormat::Uint32);
        for c in commands {
            if c.instances > 0 && c.count > 0 {
                p.draw_indexed(
                    c.first..c.first + c.count,
                    c.base,
                    c.start..c.start + c.instances,
                );
            }
        }
        self.dirty = false;
        let _ = q;
    }
    pub fn draw(
        &self,
        d: &wgpu::Device,
        q: &wgpu::Queue,
        e: &mut wgpu::CommandEncoder,
        color: &wgpu::TextureView,
        depth: &wgpu::TextureView,
        msaa: bool,
        camera: &[f32],
    ) {
        if !self.enabled {
            return;
        }
        let inverse = glam::Mat4::from_cols_array(camera[..16].try_into().unwrap()).inverse();
        let conversion = glam::Mat4::from_cols(
            glam::Vec4::X,
            glam::Vec4::Y,
            glam::Vec4::new(0., 0., 0.5, 0.),
            glam::Vec4::new(0., 0., 0.5, 1.),
        );
        let mut data = inverse.to_cols_array().to_vec();
        data.extend((conversion * glam::Mat4::from_cols_array(&self.matrix)).to_cols_array());
        data.extend(self.direction);
        data.push(self.darkness);
        data.extend([if self.ground { 1. } else { 0. }, 0., 0., 0.]);
        q.write_buffer(&self.uniform, 0, bytemuck::cast_slice(&data));
        let map = self.map.create_view(&Default::default());
        let pipeline = &self.receivers[usize::from(msaa)];
        let group = d.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &pipeline.get_bind_group_layout(0),
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
                    resource: wgpu::BindingResource::TextureView(&map),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                },
            ],
        });
        let mut p = e.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("sun receiver"),
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
        p.set_pipeline(pipeline);
        p.set_bind_group(0, &group, &[]);
        p.draw(0..3, 0..1);
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn sun_validates_on_metal_both_samples() {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::METAL,
            ..Default::default()
        });
        let Some(a) = pollster::block_on(instance.request_adapter(&Default::default())) else {
            return;
        };
        let (d, _) = pollster::block_on(a.request_device(&Default::default(), None)).unwrap();
        let sun = super::Sun::new(&d, wgpu::TextureFormat::Bgra8UnormSrgb);
        assert!(!sun.enabled);
        assert_eq!(sun.receivers.len(), 2);
    }
}
