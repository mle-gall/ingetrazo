//! A resident Metal scene: compute compaction precedes native indirect draws.
mod timing;
mod overlay;
mod sections;
mod textures;
// R-look: isolated style and background passes.
mod style;
mod background;
mod antialias;
mod depth_resolve;
mod edges;
mod faces;
mod xray;
mod ao;
use numpy::PyReadonlyArray1;
use pyo3::{exceptions::PyValueError, prelude::*};
use raw_window_handle::{
    AppKitDisplayHandle, AppKitWindowHandle, RawDisplayHandle, RawWindowHandle,
};
use std::{ptr::NonNull, time::Instant};
use wgpu::util::DeviceExt;

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Command {
    count: u32,
    instances: u32,
    first: u32,
    base: i32,
    start: u32,
}
struct TimingSlot {
    read: wgpu::Buffer,
    active: Vec<&'static str>,
    pending: Option<std::sync::mpsc::Receiver<Result<(), wgpu::BufferAsyncError>>>,
}
struct Scene {
    material_shifts: Vec<i64>,
    material_data: Vec<u8>,
    face_ranges: Vec<(u32, u32, bool)>,
    inst: wgpu::Buffer,
    flags: Vec<u32>,
    rows: Vec<u8>,
    protos: wgpu::Buffer,
    prototype_data: Vec<u8>,
    survivors: wgpu::Buffer,
    template_data: Vec<u8>,
    capacity: usize,
    edge_data: Vec<u8>,
    edge_records: wgpu::Buffer,
    viewpoints: wgpu::Buffer,
    counters: wgpu::Buffer,
    vertex_data: Vec<u8>,
    index_data: Vec<u8>,
    vertex: wgpu::Buffer,
    index: wgpu::Buffer,
    commands: wgpu::Buffer,
    template: wgpu::Buffer,
    hard_template: wgpu::Buffer,
    compute: wgpu::BindGroup,
    draw: wgpu::BindGroup,
    edge_draw: wgpu::BindGroup,
    xray_draw: wgpu::BindGroup,
    xray_edge_draw: wgpu::BindGroup,
    profile_draw: wgpu::BindGroup,
    n: u32,
    p: u32,
}
#[pyclass(unsendable)]
struct Renderer {
    textures: textures::Textures,
    textures_enabled: bool,
    texture_groups: Vec<wgpu::BindGroup>,
    ao: ao::AmbientOcclusion,
    antialias: bool,
    ids_dirty: bool,
    camera_data: Vec<f32>,
    stable_frames: u32,
    pick_pending: bool,
    aa: antialias::Antialias,
    transparency: xray::Xray,
    look: style::Style,
    background: background::Background,
    look_groups: Vec<wgpu::BindGroup>,
    capture_next: bool,
    captured: Option<Vec<u8>>,
    overlay: overlay::Overlay,
    sections: sections::Sections,
    surface: wgpu::Surface<'static>,
    device: wgpu::Device,
    queue: wgpu::Queue,
    config: wgpu::SurfaceConfiguration,
    depth: wgpu::Texture,
    offscreen: wgpu::Texture,
    ids: wgpu::Texture,
    camera: wgpu::Buffer,
    compute: wgpu::ComputePipeline,
    compute_pick: wgpu::ComputePipeline,
    draw: wgpu::RenderPipeline,
    draw_plain: wgpu::RenderPipeline,
    draw_noids: wgpu::RenderPipeline,
    plain_noids: wgpu::RenderPipeline,
    edge: wgpu::RenderPipeline,
    hard_edge: wgpu::RenderPipeline,
    xray: wgpu::RenderPipeline,
    xray_edge: wgpu::RenderPipeline,
    profile_top: wgpu::RenderPipeline,
    scene: Option<Scene>,
    multi: bool,
    style: u32,
    edges: bool,
    queries: Option<wgpu::QuerySet>,
    resolve: wgpu::Buffer,
    timings: Vec<TimingSlot>,
    last_gpu: Option<f64>,
    last_counters: std::collections::BTreeMap<String, u64>,
    last_pick_gpu: Option<f64>,
    pass_gpu: std::collections::BTreeMap<String, f64>,
    detailed_timestamps: bool,
    last_cpu: f64,
    last_acquire: f64,
    frame_stages: [f64; 5],
    read: wgpu::Buffer,
    gpu_memory: u64,
    #[pyo3(get)]
    adapter: String,
}
fn row_runs(ids: Vec<usize>) -> Vec<(usize, usize)> {
    // The CPU mirror includes flags and overrides for untouched rows. Uploading
    // the enclosing range batches scattered selections into one queue write.
    match (ids.iter().min(), ids.iter().max()) {
        (Some(&first), Some(&last)) => vec![(first, last + 1)],
        _ => Vec::new(),
    }
}

fn grown_capacity(current: usize, needed: usize) -> usize {
    current.max(needed.max(1).next_power_of_two())
}

fn merge_instance_flags(old: u32, incoming: u32) -> u32 {
    (old & 6) | (incoming & 1)
}

fn texture(d: &wgpu::Device, w: u32, h: u32, format: wgpu::TextureFormat) -> wgpu::Texture {
    d.create_texture(&wgpu::TextureDescriptor {
        label: None,
        size: wgpu::Extent3d {
            width: w,
            height: h,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC | wgpu::TextureUsages::TEXTURE_BINDING,
        view_formats: &[],
    })
}
fn multisampled(d: &wgpu::Device, w: u32, h: u32, format: wgpu::TextureFormat) -> wgpu::Texture {
    d.create_texture(&wgpu::TextureDescriptor {
        label: Some("4x color resolve"),
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
fn buffer(d: &wgpu::Device, bytes: &[u8], usage: wgpu::BufferUsages) -> wgpu::Buffer {
    d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: None,
        contents: bytes,
        usage,
    })
}
fn capacity_buffer(d: &wgpu::Device, bytes: &[u8], capacity: usize, usage: wgpu::BufferUsages) -> wgpu::Buffer {
    let mut padded = vec![0; capacity];
    padded[..bytes.len()].copy_from_slice(bytes);
    buffer(d, &padded, usage)
}

fn bind_prototypes(d: &wgpu::Device, layout: &wgpu::BindGroupLayout,
    buffers: &[&wgpu::Buffer], count: u32) -> wgpu::BindGroup {
    // arrayLength(proto) defines the edge-command offset in the shader.
    // Bind the logical range even when its allocation has spare capacity.
    let entries: Vec<_> = buffers.iter().enumerate().map(|(i, b)| wgpu::BindGroupEntry {
        binding: i as u32,
        resource: if i == 2 {
            wgpu::BindingResource::Buffer(wgpu::BufferBinding {
                buffer: b, offset: 0, size: std::num::NonZeroU64::new(count as u64 * 32),
            })
        } else { b.as_entire_binding() },
    }).collect();
    d.create_bind_group(&wgpu::BindGroupDescriptor { label: None, layout, entries: &entries })
}

fn bind(
    d: &wgpu::Device,
    layout: &wgpu::BindGroupLayout,
    buffers: &[&wgpu::Buffer],
) -> wgpu::BindGroup {
    let entries: Vec<_> = buffers
        .iter()
        .enumerate()
        .map(|(i, b)| wgpu::BindGroupEntry {
            binding: i as u32,
            resource: b.as_entire_binding(),
        })
        .collect();
    d.create_bind_group(&wgpu::BindGroupDescriptor {
        label: None,
        layout,
        entries: &entries,
    })
}
#[pymethods]
impl Renderer {
    #[new]
    fn new(ns_view_ptr: usize, width: u32, height: u32, scale: f64) -> PyResult<Self> {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::METAL,
            ..Default::default()
        });
        let ptr = NonNull::new(ns_view_ptr as *mut std::ffi::c_void)
            .ok_or_else(|| PyValueError::new_err("null NSView"))?;
        // Qt owns the NSView. Python retains this Renderer only while its widget lives.
        // wgpu's Metal backend installs/reuses a CAMetalLayer on this AppKit view.
        let surface = unsafe {
            instance.create_surface_unsafe(wgpu::SurfaceTargetUnsafe::RawHandle {
                raw_display_handle: RawDisplayHandle::AppKit(AppKitDisplayHandle::new()),
                raw_window_handle: RawWindowHandle::AppKit(AppKitWindowHandle::new(ptr)),
            })
        }
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
        let a = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            compatible_surface: Some(&surface),
            ..Default::default()
        }))
        .ok_or_else(|| PyValueError::new_err("no Metal adapter"))?;
        let optional = wgpu::Features::MULTI_DRAW_INDIRECT | wgpu::Features::TIMESTAMP_QUERY;
        let features = (a.features() & optional) | wgpu::Features::INDIRECT_FIRST_INSTANCE;
        let (device, queue) = pollster::block_on(a.request_device(
            &wgpu::DeviceDescriptor {
                label: None,
                required_features: features,
                required_limits: a.limits(),
                memory_hints: Default::default(),
            },
            None,
        ))
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
        let caps = surface.get_capabilities(&a);
        let format = caps
            .formats
            .iter()
            .copied()
            .find(|f| f.is_srgb())
            .ok_or_else(|| PyValueError::new_err("no sRGB surface"))?;
        let w = ((width as f64 * scale) as u32).max(1);
        let h = ((height as f64 * scale) as u32).max(1);
        let config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            format,
            width: w,
            height: h,
            present_mode: wgpu::PresentMode::AutoNoVsync,
            desired_maximum_frame_latency: 2,
            alpha_mode: caps.alpha_modes[0],
            view_formats: vec![],
        };
        surface.configure(&device, &config);
        let camera = buffer(
            &device,
            &[0; 112],
            wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        );
        let cs = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("cull"),
            source: wgpu::ShaderSource::Wgsl(include_str!("shader.wgsl").into()),
        });
        let compute = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: None,
            layout: None,
            module: &cs,
            entry_point: Some("cull"),
            compilation_options: Default::default(),
            cache: None,
        });
        let pick_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("cursor culling"), bind_group_layouts: &[&compute.get_bind_group_layout(0)], push_constant_ranges: &[],
        });
        let compute_pick = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("cursor placement culling"), layout: Some(&pick_layout), module: &cs, entry_point: Some("cull"),
            compilation_options: wgpu::PipelineCompilationOptions { constants: &[("PICK".to_string(), 1.)].into_iter().collect(), ..Default::default() }, cache: None,
        });
        let vs = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("draw"),
            source: wgpu::ShaderSource::Wgsl(concat!(include_str!("shading.wgsl"), "\n", include_str!("edges.wgsl")).into()),
        });
        let face_attrs = wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x3,2=>Unorm8x4];
        let pipeline = |topology, fragment, compare, write, bias, samples| {
            device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: None,
                layout: None,
                vertex: wgpu::VertexState {
                    module: &vs,
                    entry_point: Some(if fragment == "edge_fs" || fragment == "hidden_edge_fs" || fragment == "profile_fs" { "edge_vs" } else { "vs" }),
                    compilation_options: Default::default(),
                    buffers: &{ let layouts = if fragment == "edge_fs" || fragment == "hidden_edge_fs" || fragment == "profile_fs" { vec![] } else { vec![wgpu::VertexBufferLayout {
                        array_stride: 28,
                        step_mode: wgpu::VertexStepMode::Vertex,
                        attributes: &face_attrs,
                    }] }; layouts },
                },
                fragment: Some(wgpu::FragmentState {
                    module: &vs,
                    entry_point: Some(fragment),
                    compilation_options: Default::default(),
                    targets: &[
                        Some(wgpu::ColorTargetState {
                            format,
                            blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                            write_mask: if fragment == "depth_fs" { wgpu::ColorWrites::empty() } else { wgpu::ColorWrites::ALL },
                        }),
                        (samples == 1).then_some(wgpu::ColorTargetState {
                            format: wgpu::TextureFormat::R32Uint,
                            blend: None,
                            write_mask: wgpu::ColorWrites::ALL,
                        }),
                    ],
                }),
                primitive: wgpu::PrimitiveState {
                    topology,
                    ..Default::default()
                },
                depth_stencil: Some(wgpu::DepthStencilState {
                    format: wgpu::TextureFormat::Depth32Float,
                    depth_write_enabled: write,
                    depth_compare: compare,
                    stencil: Default::default(),
                    bias,
                }),
                multisample: wgpu::MultisampleState {
                    count: samples,
                    ..Default::default()
                },
                multiview: None,
                cache: None,
            })
        };
        let draw = pipeline(
            wgpu::PrimitiveTopology::TriangleList,
            "fs",
            wgpu::CompareFunction::Less,
            true,
            Default::default(),
            1,
        );
        // Keep the same explicit layouts so resident draw groups can be reused.
        let plain_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("untextured faces"),
            bind_group_layouts: &[&draw.get_bind_group_layout(0), &draw.get_bind_group_layout(1), &draw.get_bind_group_layout(2)],
            push_constant_ranges: &[],
        });
        let face_variant = |plain: bool, ids: bool| device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("untextured faces without alpha discard"), layout: Some(&plain_layout),
            vertex: wgpu::VertexState { module: &vs, entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[wgpu::VertexBufferLayout { array_stride: 28, step_mode: wgpu::VertexStepMode::Vertex, attributes: &face_attrs }] },
            fragment: Some(wgpu::FragmentState { module: &vs, entry_point: Some("fs"),
                compilation_options: wgpu::PipelineCompilationOptions { constants: &[("TEXTURED".to_string(), if plain { 0. } else { 1. })].into_iter().collect(), ..Default::default() },
                targets: &[Some(wgpu::ColorTargetState { format, blend: Some(wgpu::BlendState::ALPHA_BLENDING), write_mask: wgpu::ColorWrites::ALL }),
                    ids.then_some(wgpu::ColorTargetState { format: wgpu::TextureFormat::R32Uint, blend: None, write_mask: wgpu::ColorWrites::ALL })] }),
            primitive: Default::default(),
            depth_stencil: Some(wgpu::DepthStencilState { format: wgpu::TextureFormat::Depth32Float,
                depth_write_enabled: true, depth_compare: wgpu::CompareFunction::Less, stencil: Default::default(), bias: Default::default() }),
            multisample: Default::default(), multiview: None, cache: None,
        });
        let draw_plain = face_variant(true, true);
        let draw_noids = face_variant(false, false);
        let plain_noids = face_variant(true, false);
        let xray = pipeline(
            wgpu::PrimitiveTopology::TriangleList,
            "depth_fs",
            wgpu::CompareFunction::Less,
            true,
            Default::default(),
            1,
        );
        let bias = wgpu::DepthBiasState {
            constant: -2,
            slope_scale: -1.,
            clamp: 0.,
        };
        let edge = pipeline(
            wgpu::PrimitiveTopology::TriangleList,
            "edge_fs",
            wgpu::CompareFunction::LessEqual,
            false,
            bias,
            1,
        );
        let xray_edge = pipeline(
            wgpu::PrimitiveTopology::TriangleList,
            "hidden_edge_fs",
            wgpu::CompareFunction::Greater,
            false,
            bias,
            1,
        );
        let profile_top = pipeline(wgpu::PrimitiveTopology::TriangleList, "profile_fs",
            wgpu::CompareFunction::Always, false, bias, 1);
        let queries = features.contains(wgpu::Features::TIMESTAMP_QUERY).then(|| {
            device.create_query_set(&wgpu::QuerySetDescriptor {
                label: None,
                ty: wgpu::QueryType::Timestamp,
                count: timing::COUNT,
            })
        });
        let resolve = buffer(
            &device,
            &[0; timing::BYTES],
            wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
        );
        let read = buffer(
            &device,
            &[0; 256],
            wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        );
        let look = style::Style::new(&device);
        let background = background::Background::new(&device, format, &look.buffer, 1);
        let look_groups = [&draw, &xray, &edge, &xray_edge, &profile_top].iter().map(|p|
            bind(&device, &p.get_bind_group_layout(1), &[&look.buffer])).collect();
        let textures = textures::Textures::new(&device, &queue, 1, 1, 1, &[vec![255;4]]);
        let texture_groups = [&draw, &xray].iter().map(|p| textures.bind(&device,p)).collect();
        let hard_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("hard edges"), bind_group_layouts: &[&edge.get_bind_group_layout(0), &edge.get_bind_group_layout(1)], push_constant_ranges: &[],
        });
        let hard_edge = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("hard edges without profile classification"), layout: Some(&hard_layout),
            vertex: wgpu::VertexState { module: &vs, entry_point: Some("edge_vs"),
                compilation_options: wgpu::PipelineCompilationOptions { constants: &[("PROFILES".to_string(), 0.)].into_iter().collect(), ..Default::default() }, buffers: &[] },
            fragment: Some(wgpu::FragmentState { module: &vs, entry_point: Some("edge_fs"), compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState { format, blend: Some(wgpu::BlendState::ALPHA_BLENDING), write_mask: wgpu::ColorWrites::ALL }), Some(wgpu::ColorTargetState { format: wgpu::TextureFormat::R32Uint, blend: None, write_mask: wgpu::ColorWrites::ALL })] }),
            primitive: Default::default(),
            depth_stencil: Some(wgpu::DepthStencilState { format: wgpu::TextureFormat::Depth32Float, depth_write_enabled: false, depth_compare: wgpu::CompareFunction::LessEqual, stencil: Default::default(), bias }),
            multisample: Default::default(), multiview: None, cache: None,
        });
        let mut aa = antialias::Antialias::new(&device, format, &look.buffer, w, h);
        aa.bind_textures(&device, &textures);
        let mut transparency = xray::Xray::new(&device, format, w, h);
        transparency.bind_textures(&device, &textures);
        Ok(Self {
            textures, texture_groups, textures_enabled: true,
            ao: ao::AmbientOcclusion::new(&device, format),
            antialias: true,
            ids_dirty: true,
            camera_data: Vec::new(),
            stable_frames: 0,
            pick_pending: false,
            aa,
            look, background, look_groups,
            transparency,
            capture_next: false,
            captured: None,
            overlay: overlay::Overlay::new(&device, format),
            sections: sections::Sections::new(&device, format, &camera),
            depth: texture(&device, w, h, wgpu::TextureFormat::Depth32Float),
            offscreen: texture(&device, w, h, format),
            ids: texture(&device, w, h, wgpu::TextureFormat::R32Uint),
            timings: (0..4)
                .map(|_| TimingSlot {
                    read: buffer(
                        &device,
                        &[0; timing::BYTES + 32],
                        wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
                    ),
                    pending: None,
                    active: Vec::new(),
                })
                .collect(),
            last_gpu: None,
            last_pick_gpu: None,
            pass_gpu: Default::default(),
            last_counters: Default::default(),
            detailed_timestamps: features.contains(wgpu::Features::TIMESTAMP_QUERY),
            last_cpu: 0.,
            last_acquire: 0.,
            frame_stages: [0.; 5],
            surface,
            device,
            queue,
            config,
            camera,
            compute,
            compute_pick,
            draw,
            draw_plain,
            draw_noids,
            plain_noids,
            edge,
            hard_edge,
            xray,
            xray_edge,
            profile_top,
            scene: None,
            style: 0,
            edges: true,
            multi: features.contains(wgpu::Features::MULTI_DRAW_INDIRECT),
            queries,
            resolve,
            read,
            gpu_memory: 0,
            adapter: format!(
                "{:?}; multi_draw={}",
                a.get_info(),
                features.contains(wgpu::Features::MULTI_DRAW_INDIRECT)
            ),
        })
    }
    /// Packed little-endian arrays; reject malformed uploads before reaching wgpu.
    fn set_scene(
        &mut self,
        prototypes: (
            PyReadonlyArray1<'_, u8>,
            PyReadonlyArray1<'_, u8>,
            PyReadonlyArray1<'_, u8>,
            PyReadonlyArray1<'_, u8>,
        ),
        instances: PyReadonlyArray1<'_, u8>,
    ) -> PyResult<()> {
        let (v, ix, p, cmd) = (&prototypes.0, &prototypes.1, &prototypes.2, &prototypes.3);
        let (v, ix, p, cmd) = (
            v.as_slice()?,
            ix.as_slice()?,
            p.as_slice()?,
            cmd.as_slice()?,
        );
        let instances = instances.as_slice()?;
        if v.len() % 28 != 0
            || ix.len() % 4 != 0
            || p.is_empty()
            || p.len() % 32 != 0
            || cmd.len() != p.len() / 32 * 40
            || instances.is_empty()
            || instances.len() % 80 != 0
        {
            return Err(PyValueError::new_err("invalid scene array layout"));
        }
        let n = instances.len() / 80;
        let count = p.len() / 32;
        let capacity = grown_capacity(0, n);
        let prototype_capacity = grown_capacity(0, count);
        let limit = self.device.limits().max_storage_buffer_binding_size as usize;
        if capacity * 80 > limit || prototype_capacity * 40 > limit {
            return Err(PyValueError::new_err("scene capacity exceeds storage binding limit"));
        }
        let mut counts = vec![0u32; count];
        for row in instances.chunks_exact(80) {
            let id = u32::from_le_bytes(row[64..68].try_into().unwrap()) as usize;
            if id >= count {
                return Err(PyValueError::new_err("prototype id out of range"));
            }
            counts[id] += 1;
        }
        let mut start = 0;
        for (j, (row, capacity)) in cmd.chunks_exact(20).zip(counts.iter().cycle()).enumerate() {
            if j == count {
                start = 0;
            }
            let c: Command = bytemuck::pod_read_unaligned(row);
            if c.instances != 0
                || c.start != start
                || (c.first as u64 + c.count as u64) * 4 > ix.len() as u64
            {
                return Err(PyValueError::new_err("invalid command range"));
            }
            for index in ix[c.first as usize * 4..(c.first + c.count) as usize * 4].chunks_exact(4)
            {
                let j = u32::from_le_bytes(index.try_into().unwrap()) as i64 + c.base as i64;
                if j < 0 || j >= v.len() as i64 / 28 {
                    return Err(PyValueError::new_err("vertex index out of range"));
                }
            }
            start += capacity;
        }
        for bytes in [p, instances] {
            if bytes.len() as u64 > self.device.limits().max_storage_buffer_binding_size as u64 {
                return Err(PyValueError::new_err("scene exceeds storage binding limit"));
            }
        }
        // Preserve the scene ABI; pack unique edges separately from face vertices.
        let (expanded_v, expanded_ix, mut expanded_cmd) = edges::expand(v, ix, cmd, count)
            .map_err(PyValueError::new_err)?;
        let (face_v, face_ix, material_shifts) = faces::compact(v, &expanded_ix, &mut expanded_cmd, count);
        let (v, ix, cmd) = (face_v.as_slice(), face_ix.as_slice(), expanded_cmd.as_slice());
        if expanded_v.len() as u64 > self.device.limits().max_storage_buffer_binding_size as u64 {
            return Err(PyValueError::new_err("edge records exceed storage binding limit"));
        }
        let edge_records = buffer(&self.device, &expanded_v, wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST);
        let vertex = buffer(&self.device, v, wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST);
        let index = buffer(&self.device, ix, wgpu::BufferUsages::INDEX | wgpu::BufferUsages::COPY_DST);
        let protos = capacity_buffer(&self.device, p, prototype_capacity * 32, wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST);
        let mut padded = vec![0; capacity * 80];
        for row in padded.chunks_exact_mut(80) {
            row[72] = 1;
        }
        padded[..instances.len()].copy_from_slice(instances);

        let inst = buffer(
            &self.device,
            &padded,
            wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
        );
        let commands = capacity_buffer(
            &self.device,
            cmd,
            prototype_capacity * 40,
            wgpu::BufferUsages::STORAGE
                | wgpu::BufferUsages::INDIRECT
                | wgpu::BufferUsages::COPY_DST,
        );
        let template = capacity_buffer(&self.device, cmd, prototype_capacity * 40, wgpu::BufferUsages::COPY_SRC | wgpu::BufferUsages::COPY_DST);
        let mut hard_cmd = cmd.to_vec();
        for row in hard_cmd.chunks_exact_mut(20).skip(count) {
            let hard_count = row[16..20].to_vec();
            row[..4].copy_from_slice(&hard_count);
        }
        let hard_template = capacity_buffer(&self.device, &hard_cmd, prototype_capacity * 40, wgpu::BufferUsages::COPY_SRC | wgpu::BufferUsages::COPY_DST);
        let survivors = buffer(&self.device, &vec![0; capacity * 4], wgpu::BufferUsages::STORAGE);
        let viewpoints = buffer(&self.device, &vec![0; capacity * 80], wgpu::BufferUsages::STORAGE);
        let counters = buffer(&self.device, &[0; 32], wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC | wgpu::BufferUsages::COPY_DST);
        let compute = bind_prototypes(
            &self.device,
            &self.compute.get_bind_group_layout(0),
            &[&self.camera, &inst, &protos, &commands, &survivors, &viewpoints, &counters],
            count as u32,
        );
        let draw = bind(
            &self.device,
            &self.draw.get_bind_group_layout(0),
            &[&self.camera, &inst, &survivors],
        );
        let edge_draw = bind(
            &self.device,
            &self.edge.get_bind_group_layout(0),
            &[&self.camera, &inst, &survivors, &edge_records, &viewpoints],
        );
        let xray_draw = bind(
            &self.device,
            &self.xray.get_bind_group_layout(0),
            &[&self.camera, &inst, &survivors],
        );
        let xray_edge_draw = bind(
            &self.device,
            &self.xray_edge.get_bind_group_layout(0),
            &[&self.camera, &inst, &survivors, &edge_records, &viewpoints],
        );
        let profile_draw = bind(&self.device, &self.profile_top.get_bind_group_layout(0), &[&self.camera, &inst, &survivors, &edge_records, &viewpoints]);
        self.transparency.bind_scene(&self.device, &self.camera, &inst, &survivors, &self.look.buffer);
        self.aa.bind_scene(&self.device, &self.camera, &inst, &survivors, &self.look.buffer, &edge_records, &viewpoints);
        self.gpu_memory =
            (v.len() + expanded_v.len() + ix.len() + p.len() + cmd.len() * 3 + instances.len() + n * 20 + 112 + 416)
                as u64 + self.textures.bytes + self.textures.materials.size();
        self.ids_dirty = true;
        self.scene = Some(Scene {
            edge_data: expanded_v,
            edge_records,
            viewpoints,
            counters,
            face_ranges: vec![(0, count as u32, true)],
            material_data: vec![0; count*16],
            material_shifts,
            inst,
            rows: instances.to_vec(),
            protos,
            prototype_data: p.to_vec(),
            survivors,
            template_data: cmd.to_vec(),
            capacity,
            vertex_data: v.to_vec(),
            index_data: ix.to_vec(),
            flags: instances
                .chunks_exact(80)
                .map(|r| u32::from_le_bytes(r[72..76].try_into().unwrap()))
                .collect(),
            vertex,
            index,
            commands,
            template,
            hard_template,
            compute,
            draw,
            edge_draw,
            xray_draw,
            xray_edge_draw,
            profile_draw,
            n: n as u32,
            p: count as u32,
        });
        self.device.poll(wgpu::Maintain::Wait);
        Ok(())
    }
    /// Append compact replacement ranges while preserving placement identities.
    fn replace_prototype(&mut self, id: usize, vertices: PyReadonlyArray1<'_, u8>,
        indices: PyReadonlyArray1<'_, u8>, bounds: PyReadonlyArray1<'_, u8>, faces: u32) -> PyResult<()> {
        let (v, ix, bounds) = (vertices.as_slice()?, indices.as_slice()?, bounds.as_slice()?);
        let s = self.scene.as_mut().ok_or_else(|| PyValueError::new_err("set_scene first"))?;
        if id > s.p as usize || v.len()%28 != 0 || ix.len()%4 != 0 || bounds.len()!=32 || faces as usize > ix.len()/4 {
            return Err(PyValueError::new_err("invalid prototype"));
        }
        if ix.chunks_exact(4).any(|i| u32::from_le_bytes(i.try_into().unwrap()) as usize >= v.len()/28) {
            return Err(PyValueError::new_err("vertex index out of range"));
        }
        let source = [Command { count: faces, instances: 0, first: 0, base: 0, start: 0 },
            Command { count: ix.len() as u32/4-faces, instances: 0, first: faces, base: 0, start: 0 }];
        let (edge, expanded_ix, mut commands) = edges::expand(v, ix, bytemuck::cast_slice(&source), 1).map_err(PyValueError::new_err)?;
        let (face, indices, shifts) = faces::compact(v, &expanded_ix, &mut commands, 1);
        let edge_base = s.edge_data.len()/48;
        let vertex_base = s.vertex_data.len()/28;
        let index_base = s.index_data.len()/4;
        if (s.edge_data.len()+edge.len()).next_power_of_two() > self.device.limits().max_storage_buffer_binding_size as usize {
            return Err(PyValueError::new_err("edge capacity exceeds storage binding limit"));
        }
        if id == s.p as usize {
            let old_p = s.p as usize;
            s.p += 1;
            s.prototype_data.extend_from_slice(bounds);
            s.material_shifts.push(0);
            for row in s.material_data[..old_p*16].chunks_exact_mut(16) {
                let offset = u32::from_le_bytes(row[4..8].try_into().unwrap());
                if offset != 0 { row[4..8].copy_from_slice(&(offset+1).to_le_bytes()); }
            }
            s.material_data.splice(old_p*16..old_p*16, [0;16]);
            s.template_data.splice(old_p*20..old_p*20, [0;20]);
            s.template_data.extend_from_slice(&[0;20]);
        }
        s.face_ranges = face_ranges(&s.material_data, s.p);
        s.material_shifts[id] = vertex_base as i64 + shifts[0];
        s.prototype_data[id*32..(id+1)*32].copy_from_slice(bounds);
        s.vertex_data.extend_from_slice(&face);
        s.index_data.extend_from_slice(&indices);
        s.edge_data.extend_from_slice(&edge);
        for (target, data, usage, offset, addition) in [
            (&mut s.vertex, &s.vertex_data, wgpu::BufferUsages::VERTEX, vertex_base*28, face.as_slice()),
            (&mut s.index, &s.index_data, wgpu::BufferUsages::INDEX, index_base*4, indices.as_slice()),
            (&mut s.edge_records, &s.edge_data, wgpu::BufferUsages::STORAGE, edge_base*48, edge.as_slice())] {
            if data.len() as u64 > target.size() {
                *target = capacity_buffer(&self.device, data, grown_capacity(target.size() as usize, data.len()), usage | wgpu::BufferUsages::COPY_DST);
            } else if !addition.is_empty() { self.queue.write_buffer(target, offset as u64, addition); }
        }
        let mut face_cmd: Command = bytemuck::pod_read_unaligned(&commands[..20]);
        face_cmd.base += vertex_base as i32;
        face_cmd.first += index_base as u32;
        let mut edge_cmd: [u32;5] = bytemuck::pod_read_unaligned(&commands[20..]);
        edge_cmd[2] += edge_base as u32*6;
        s.template_data[id*20..(id+1)*20].copy_from_slice(bytemuck::bytes_of(&face_cmd));
        s.template_data[(id+s.p as usize)*20..(id+s.p as usize+1)*20].copy_from_slice(bytemuck::bytes_of(&edge_cmd));
        let mut counts = vec![0u32; s.p as usize];
        for row in s.rows.chunks_exact(80) { counts[u32::from_le_bytes(row[64..68].try_into().unwrap()) as usize] += 1; }
        let mut start = 0u32;
        for (i, count) in counts.into_iter().enumerate() {
            s.template_data[i*20+16..i*20+20].copy_from_slice(&start.to_le_bytes());
            let offset = (i+s.p as usize)*20+12;
            s.template_data[offset..offset+4].copy_from_slice(&start.to_le_bytes());
            start += count;
        }
        let mut hard = s.template_data.clone();
        for row in hard.chunks_exact_mut(20).skip(s.p as usize) { let count = row[16..20].to_vec(); row[..4].copy_from_slice(&count); }
        for (target, data, usage) in [
            (&mut s.protos, &s.prototype_data, wgpu::BufferUsages::STORAGE),
            (&mut s.template, &s.template_data, wgpu::BufferUsages::COPY_SRC),
            (&mut s.hard_template, &hard, wgpu::BufferUsages::COPY_SRC),
            (&mut s.commands, &s.template_data, wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::INDIRECT)] {
            if data.len() as u64 > target.size() { *target = capacity_buffer(&self.device, data, grown_capacity(target.size() as usize, data.len()), usage | wgpu::BufferUsages::COPY_DST); }
            else { self.queue.write_buffer(target, 0, data); }
        }
        s.compute = bind_prototypes(&self.device, &self.compute.get_bind_group_layout(0), &[&self.camera, &s.inst, &s.protos, &s.commands, &s.survivors, &s.viewpoints, &s.counters], s.p);
        s.edge_draw = bind(&self.device, &self.edge.get_bind_group_layout(0), &[&self.camera, &s.inst, &s.survivors, &s.edge_records, &s.viewpoints]);
        s.xray_edge_draw = bind(&self.device, &self.xray_edge.get_bind_group_layout(0), &[&self.camera, &s.inst, &s.survivors, &s.edge_records, &s.viewpoints]);
        s.profile_draw = bind(&self.device, &self.profile_top.get_bind_group_layout(0), &[&self.camera, &s.inst, &s.survivors, &s.edge_records, &s.viewpoints]);
        self.aa.bind_scene(&self.device, &self.camera, &s.inst, &s.survivors, &self.look.buffer, &s.edge_records, &s.viewpoints);
        self.ids_dirty = true;
        Ok(())
    }

    /// Update existing resident rows without replacing geometry or pick IDs.
    fn update_instances(&mut self, ids: Vec<usize>, rows: PyReadonlyArray1<'_, u8>) -> PyResult<()> {
        self.ids_dirty = true;
        self.stable_frames = 0;
        let rows = rows.as_slice()?;
        let s = self.scene.as_mut().ok_or_else(|| PyValueError::new_err("set_scene first"))?;
        if rows.len() != ids.len() * 80 {
            return Err(PyValueError::new_err("invalid instance rows"));
        }
        for row in rows.chunks_exact(80) {
            if u32::from_le_bytes(row[64..68].try_into().unwrap()) >= s.p {
                return Err(PyValueError::new_err("prototype id out of range"));
            }
        }
        let max_rows = self.device.limits().max_storage_buffer_binding_size as usize / 80;
        if ids.iter().any(|&id| id >= max_rows) {
            return Err(PyValueError::new_err("instance rows exceed storage binding limit"));
        }
        let n = ids.iter().map(|i| i + 1).max().unwrap_or(0).max(s.n as usize);
        if grown_capacity(s.capacity, n) > max_rows {
            return Err(PyValueError::new_err("instance capacity exceeds storage binding limit"));
        }
        let structure = n != s.n as usize || ids.iter().zip(rows.chunks_exact(80)).any(|(&id, row)|
            row[64..68] != s.rows[id*80+64..id*80+68]);
        let old_n = s.n as usize;
        s.rows.resize(n * 80, 0);
        s.flags.resize(n, 1);
        for row in s.rows[old_n*80..].chunks_exact_mut(80) {
            row[72] = 1;
        }
        if n > s.capacity {
            s.capacity = grown_capacity(s.capacity, n);
            let mut padded = vec![0; s.capacity*80];
            for row in padded.chunks_exact_mut(80) {
                row[72] = 1;
            }
            padded[..s.rows.len()].copy_from_slice(&s.rows);
            s.inst = buffer(&self.device, &padded, wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST);
            s.survivors = buffer(&self.device, &vec![0; s.capacity*4], wgpu::BufferUsages::STORAGE);
            s.viewpoints = buffer(&self.device, &vec![0; s.capacity*80], wgpu::BufferUsages::STORAGE);
            s.compute = bind_prototypes(&self.device, &self.compute.get_bind_group_layout(0),
                &[&self.camera, &s.inst, &s.protos, &s.commands, &s.survivors, &s.viewpoints, &s.counters], s.p);
            s.draw = bind(&self.device, &self.draw.get_bind_group_layout(0), &[&self.camera, &s.inst, &s.survivors]);
            s.edge_draw = bind(&self.device, &self.edge.get_bind_group_layout(0), &[&self.camera, &s.inst, &s.survivors, &s.edge_records, &s.viewpoints]);
            s.xray_draw = bind(&self.device, &self.xray.get_bind_group_layout(0), &[&self.camera, &s.inst, &s.survivors]);
            s.xray_edge_draw = bind(&self.device, &self.xray_edge.get_bind_group_layout(0), &[&self.camera, &s.inst, &s.survivors, &s.edge_records, &s.viewpoints]);
            s.profile_draw = bind(&self.device, &self.profile_top.get_bind_group_layout(0), &[&self.camera, &s.inst, &s.survivors, &s.edge_records, &s.viewpoints]);
            self.aa.bind_scene(&self.device, &self.camera, &s.inst, &s.survivors, &self.look.buffer, &s.edge_records, &s.viewpoints);
            self.transparency.bind_scene(&self.device, &self.camera, &s.inst, &s.survivors, &self.look.buffer);
        }
        s.n = n as u32;
        for (&id, row) in ids.iter().zip(rows.chunks_exact(80)) {
            let mut value = row.to_vec();
            let flags = u32::from_le_bytes(row[72..76].try_into().unwrap());
            s.flags[id] = merge_instance_flags(s.flags[id], flags);
            value[72..76].copy_from_slice(&s.flags[id].to_le_bytes());
            value[76..80].copy_from_slice(&s.rows[id*80+76..id*80+80]);
            s.rows[id*80..(id+1)*80].copy_from_slice(&value);
        }
        for (first, end) in row_runs(ids) {
            self.queue.write_buffer(&s.inst, first as u64 * 80, &s.rows[first*80..end*80]);
        }
        if structure {
            let mut counts = vec![0u32; s.p as usize];
            for row in s.rows.chunks_exact(80) {
                counts[u32::from_le_bytes(row[64..68].try_into().unwrap()) as usize] += 1;
            }
            let mut starts = vec![0u32; counts.len()];
            for i in 1..counts.len() {
                starts[i] = starts[i-1] + counts[i-1];
            }
            for (i, command) in s.template_data.chunks_exact_mut(20).enumerate() {
                let offset = if i < s.p as usize { 16 } else { 12 };
                command[offset..offset+4].copy_from_slice(&starts[i % starts.len()].to_le_bytes());
            }
            self.queue.write_buffer(&s.template, 0, &s.template_data);
            let mut hard = s.template_data.clone();
            for row in hard.chunks_exact_mut(20).skip(s.p as usize) { let count = row[16..20].to_vec(); row[..4].copy_from_slice(&count); }
            self.queue.write_buffer(&s.hard_template, 0, &hard);
        }
        Ok(())
    }

    /// Tombstones retain row identities so stale picks cannot select a neighbour.
    fn remove_instances(&mut self, ids: Vec<usize>) -> PyResult<()> {
        self.ids_dirty = true;
        let s = self.scene.as_mut().ok_or_else(|| PyValueError::new_err("set_scene first"))?;
        if ids.iter().any(|&id| id >= s.n as usize) {
            return Err(PyValueError::new_err("instance id out of range"));
        }
        for id in ids {
            s.flags[id] = 1;
            s.rows[id*80+72..id*80+76].copy_from_slice(&1u32.to_le_bytes());
            self.queue.write_buffer(&s.inst, id as u64 * 80 + 72, &1u32.to_le_bytes());
        }
        Ok(())
    }

    #[pyo3(signature = (selected_ids, hovered_id=None))]
    fn set_highlight(
        &mut self,
        selected_ids: Vec<usize>,
        hovered_id: Option<usize>,
    ) -> PyResult<()> {
        if let Some(s) = &mut self.scene {
            if selected_ids
                .iter()
                .chain(hovered_id.iter())
                .any(|&i| i >= s.flags.len())
            {
                return Err(PyValueError::new_err("instance id out of range"));
            }
            let selected: std::collections::HashSet<_> = selected_ids.into_iter().collect();
            for (i, flag) in s.flags.iter_mut().enumerate() {
                let next = (*flag & 1)
                    | if selected.contains(&i) { 2 } else { 0 }
                    | if hovered_id == Some(i) { 4 } else { 0 };
                if next != *flag {
                    *flag = next;
                    s.rows[i*80+72..i*80+76].copy_from_slice(&next.to_le_bytes());
                    self.queue
                        .write_buffer(&s.inst, i as u64 * 80 + 72, &next.to_le_bytes());
                }
            }
        }
        Ok(())
    }
    fn set_overrides(&mut self, colors: Vec<u32>) -> PyResult<()> {
        self.ids_dirty = true;
        if let Some(s) = &mut self.scene {
            if colors.len() != s.n as usize {
                return Err(PyValueError::new_err("one override per instance required"));
            }
            for (i, color) in colors.iter().enumerate() {
                if s.rows[i*80+76..i*80+80] == color.to_le_bytes() {
                    continue;
                }
                s.rows[i*80+76..i*80+80].copy_from_slice(&color.to_le_bytes());
                self.queue
                    .write_buffer(&s.inst, i as u64 * 80 + 76, &color.to_le_bytes());
            }
        }
        Ok(())
    }
    // R-look: retain string compatibility for existing diagnostic scripts.
    fn set_style(&mut self, style: &Bound<'_, PyAny>) -> PyResult<()> {
        self.ids_dirty = true;
        let (mode, edges) = self.look.update(style, &self.queue)?;
        self.ao.update(style)?;
        self.style = mode;
        let name = if let Ok(d) = style.cast::<pyo3::types::PyDict>() {
            d.get_item("face_mode")?.map(|v| v.extract::<String>()).transpose()?.unwrap_or_default()
        } else { style.extract::<String>()? };
        self.textures_enabled = name != "shaded";
        if let Some(enabled) = edges { self.edges = enabled; }
        Ok(())
    }
    fn set_antialias(&mut self, enabled: bool) { self.antialias = enabled; }
    fn read_pixels(&mut self) -> PyResult<Vec<u8>> {
        self.capture_next = true;
        self.render(true)?;
        Ok(self.captured.take().unwrap_or_default())
    }
    /// Render with resident geometry and textures into isolated sheet targets.
    /// Surface configuration and interactive attachments are never replaced.
    #[pyo3(signature = (width, height, view, projection, style, instances=None))]
    fn render_image(&mut self, width: u32, height: u32, view: Vec<f32>,
                    projection: Vec<f32>, style: &Bound<'_, PyAny>, instances: Option<PyReadonlyArray1<'_, u8>>) -> PyResult<Vec<u8>> {
        if width == 0 || height == 0 || width > self.device.limits().max_texture_dimension_2d
            || height > self.device.limits().max_texture_dimension_2d {
            return Err(PyValueError::new_err("invalid offscreen dimensions"));
        }
        if view.len() != 16 || projection.len() != 16 {
            return Err(PyValueError::new_err("camera matrices need 16 floats"));
        }
        let temporary_rows = instances.as_ref().map(|v| v.as_slice()).transpose()?;
        if let Some(rows) = temporary_rows {
            if self.scene.as_ref().map(|s| s.rows.len()) != Some(rows.len()) {
                return Err(PyValueError::new_err("capture rows must match resident instances"));
            }
            let s = self.scene.as_ref().unwrap();
            if rows.chunks_exact(80).zip(s.rows.chunks_exact(80)).any(|(a, b)| a[..72] != b[..72]) {
                return Err(PyValueError::new_err("capture rows may only change visibility and tint"));
            }
        }
        let format = self.config.format;
        let mut aa = antialias::Antialias::new(&self.device, format, &self.look.buffer, width, height);
        let mut transparency = xray::Xray::new(&self.device, format, width, height);
        aa.bind_textures(&self.device, &self.textures);
        transparency.bind_textures(&self.device, &self.textures);
        if let Some(s) = &self.scene {
            aa.bind_scene(&self.device, &self.camera, &s.inst, &s.survivors,
                          &self.look.buffer, &s.edge_records, &s.viewpoints);
            transparency.bind_scene(&self.device, &self.camera, &s.inst, &s.survivors, &self.look.buffer);
        }
        let old_size = (self.config.width, self.config.height);
        let old_camera = self.camera_data.clone();
        let old_style = self.look.data;
        let old_flags = (self.style, self.edges, self.textures_enabled, self.ids_dirty,
                         self.stable_frames, self.pick_pending, self.capture_next);
        let old_capture = self.captured.take();
        // Keep the original resources alive until the transaction has completed.
        let old_aa = std::mem::replace(&mut self.aa, aa);
        let old_transparency = std::mem::replace(&mut self.transparency, transparency);
        let old_ao = std::mem::replace(&mut self.ao, ao::AmbientOcclusion::new(&self.device, format));
        let old_overlay = std::mem::replace(&mut self.overlay, overlay::Overlay::new(&self.device, format));
        let old_color = std::mem::replace(&mut self.offscreen, texture(&self.device, width, height, format));
        let old_depth = std::mem::replace(&mut self.depth, texture(&self.device, width, height, wgpu::TextureFormat::Depth32Float));
        let old_ids = std::mem::replace(&mut self.ids, texture(&self.device, width, height, wgpu::TextureFormat::R32Uint));
        self.config.width = width;
        self.config.height = height;
        if let (Some(rows), Some(s)) = (temporary_rows, &self.scene) {
            self.queue.write_buffer(&s.inst, 0, rows);
        }
        let result = (|| {
            self.set_style(style)?;
            self.set_camera(view, projection)?;
            self.capture_next = true;
            self.render(false)?;
            Ok(self.captured.take().unwrap_or_default())
        })();
        if temporary_rows.is_some() {
            if let Some(s) = &self.scene { self.queue.write_buffer(&s.inst, 0, &s.rows); }
        }
        self.config.width = old_size.0;
        self.config.height = old_size.1;
        self.aa = old_aa;
        self.transparency = old_transparency;
        self.ao = old_ao;
        self.overlay = old_overlay;
        self.offscreen = old_color;
        self.depth = old_depth;
        self.ids = old_ids;
        self.look.data = old_style;
        self.queue.write_buffer(&self.look.buffer, 0, bytemuck::cast_slice(&old_style));
        if !old_camera.is_empty() {
            self.queue.write_buffer(&self.camera, 0, bytemuck::cast_slice(&old_camera));
        }
        self.camera_data = old_camera;
        (self.style, self.edges, self.textures_enabled, self.ids_dirty,
         self.stable_frames, self.pick_pending, self.capture_next) = old_flags;
        self.captured = old_capture;
        result
    }
    fn set_edges(&mut self, enabled: bool) {
        self.ids_dirty |= self.edges != enabled;
        self.edges = enabled;
    }
    fn set_camera(&mut self, view: Vec<f32>, proj: Vec<f32>) -> PyResult<()> {
        let v: [f32; 16] = view
            .try_into()
            .map_err(|_| PyValueError::new_err("view needs 16 floats"))?;
        let p: [f32; 16] = proj
            .try_into()
            .map_err(|_| PyValueError::new_err("projection needs 16 floats"))?;
        let correction = glam::Mat4::from_cols_array(&[
            1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 0.5, 0., 0., 0., 0.5, 1.,
        ]);
        self.ao.camera(correction * glam::Mat4::from_cols_array(&p));
        let vp = correction * glam::Mat4::from_cols_array(&p) * glam::Mat4::from_cols_array(&v);
        let mut data = vp.to_cols_array().to_vec();
        data.extend([
            self.config.width as f32,
            self.config.height as f32,
            self.style as f32,
            if self.textures_enabled { 0. } else { 1. },
        ]);
        let inverse_view = glam::Mat4::from_cols_array(&v).inverse();
        let eye = inverse_view * if p[15] == 0. { glam::Vec4::W } else { glam::Vec4::Z };
        data.extend(eye.to_array());
        data.extend([-1., -1., 1., 1.]);
        if self.camera_data != data {
            self.stable_frames = 0;
            self.ids_dirty = true;
            self.queue.write_buffer(&self.camera, 0, bytemuck::cast_slice(&data));
            self.camera_data = data;
        }
        Ok(())
    }
    /// Kept for the R2a measurement script: anti-aliasing now lives in the
    /// antialias module, so this is the same switch as ``set_antialias``.
    fn update_prototype_materials(&mut self, id: usize, data: PyReadonlyArray1<'_, u8>) -> PyResult<()> {
        let data = data.as_slice()?;
        let s = self.scene.as_mut().ok_or_else(|| PyValueError::new_err("no scene"))?;
        if id >= s.p as usize || data.len()%32 != 0 { return Err(PyValueError::new_err("invalid material rows")); }
        let mut header = [0u32;4];
        if !data.is_empty() {
            let face: Command = bytemuck::pod_read_unaligned(&s.template_data[id*20..id*20+20]);
            header = [face.base as u32, (s.material_data.len()/16) as u32, (data.len()/32) as u32, 0];
        }
        s.material_data[id*16..(id+1)*16].copy_from_slice(bytemuck::bytes_of(&header));
        s.material_data.extend_from_slice(data);
        s.face_ranges = face_ranges(&s.material_data, s.p);
        self.textures.materials = buffer(&self.device, &s.material_data, wgpu::BufferUsages::STORAGE);
        self.texture_groups = [&self.draw, &self.xray].iter().map(|p| self.textures.bind(&self.device,p)).collect();
        self.aa.bind_textures(&self.device, &self.textures);
        self.transparency.bind_textures(&self.device, &self.textures);
        Ok(())
    }
    fn set_materials(&mut self, data: PyReadonlyArray1<'_, u8>) -> PyResult<()> {
        self.ids_dirty = true;
        let data = data.as_slice()?;
        let scene = self.scene.as_mut().ok_or_else(|| PyValueError::new_err("no scene"))?;
        if data.len() % 16 != 0 || data.len() < scene.p as usize * 16
            || data.len() as u64 > self.device.limits().max_storage_buffer_binding_size as u64 {
            return Err(PyValueError::new_err("invalid sparse material stream"));
        }
        let mut resident = data.to_vec();
        for (header, shift) in resident.chunks_exact_mut(16).zip(&scene.material_shifts) {
            let base = u32::from_le_bytes(header[..4].try_into().unwrap());
            header[..4].copy_from_slice(&((i64::from(base) + shift) as u32).to_le_bytes());
        }
        scene.face_ranges = face_ranges(&resident, scene.p);
        scene.material_data = resident.clone();
        let data = resident.as_slice();
        self.gpu_memory = self.gpu_memory.saturating_sub(self.textures.materials.size());
        self.textures.materials = buffer(&self.device, data, wgpu::BufferUsages::STORAGE);
        self.gpu_memory += self.textures.materials.size();
        self.texture_groups = [&self.draw, &self.xray].iter().map(|p| self.textures.bind(&self.device,p)).collect();
        self.aa.bind_textures(&self.device, &self.textures);
        self.transparency.bind_textures(&self.device, &self.textures);
        Ok(())
    }
    fn set_textures(&mut self, width: u32, height: u32, layers: u32, levels: Vec<Vec<u8>>) -> PyResult<()> {
        self.ids_dirty = true;
        let limits = self.device.limits();
        if width == 0 || height == 0 || layers == 0 || width > limits.max_texture_dimension_2d
            || height > limits.max_texture_dimension_2d || layers > limits.max_texture_array_layers
            || levels.len() != (32-width.max(height).leading_zeros()) as usize
            || levels.iter().enumerate().any(|(k,v)| v.len() as u64 != (width>>k).max(1) as u64 * (height>>k).max(1) as u64 * layers as u64 * 4) {
            return Err(PyValueError::new_err("invalid texture array dimensions or mip data"));
        }
        self.gpu_memory = self.gpu_memory.saturating_sub(self.textures.bytes);
        let mut textures = textures::Textures::new(&self.device, &self.queue, width, height, layers, &levels);
        std::mem::swap(&mut textures.materials, &mut self.textures.materials);
        self.textures = textures;
        self.gpu_memory += self.textures.bytes;
        self.texture_groups = [&self.draw, &self.xray].iter().map(|p| self.textures.bind(&self.device,p)).collect();
        self.aa.bind_textures(&self.device, &self.textures);
        self.transparency.bind_textures(&self.device, &self.textures);
        Ok(())
    }
    #[getter]
    fn texture_memory(&self) -> u64 { self.textures.bytes }
    fn set_section_geometry(&mut self, vertices: PyReadonlyArray1<'_, u8>) -> PyResult<()> {
        let bytes = vertices.as_slice()?;
        if bytes.len() % 72 != 0 {
            return Err(PyValueError::new_err("section geometry must contain 24-byte triangle vertices"));
        }
        self.gpu_memory = self.gpu_memory.saturating_sub(self.sections.count as u64 * 24);
        self.sections.upload(&self.device, bytes);
        self.gpu_memory += bytes.len() as u64;
        Ok(())
    }
    fn set_msaa(&mut self, enabled: bool) {
        self.antialias = enabled;
    }
    fn resize(&mut self, w: u32, h: u32, scale: f64) {
        self.ids_dirty = true;
        self.config.width = ((w as f64 * scale) as u32).max(1);
        self.config.height = ((h as f64 * scale) as u32).max(1);
        self.surface.configure(&self.device, &self.config);
        self.transparency.resize(&self.device, self.config.width, self.config.height);
        self.aa.resize(&self.device, self.config.width, self.config.height);
        self.offscreen = texture(&self.device, self.config.width, self.config.height, self.config.format);
        self.depth = texture(
            &self.device,
            self.config.width,
            self.config.height,
            wgpu::TextureFormat::Depth32Float,
        );
        self.ids = texture(
            &self.device,
            self.config.width,
            self.config.height,
            wgpu::TextureFormat::R32Uint,
        );
    }
    #[pyo3(signature = (present=true))]
    fn render(&mut self, present: bool) -> PyResult<(f64, Option<f64>)> {
        let start = Instant::now();
        // Poll completion only; never wait for a timestamp in the render path.
        self.device.poll(wgpu::Maintain::Poll);
        for slot in &mut self.timings {
            let ready = slot.pending.as_ref().and_then(|rx| rx.try_recv().ok());
            if let Some(result) = ready {
                if result.is_ok() {
                    let data = slot.read.slice(..).get_mapped_range();
                    let first = u64::from_le_bytes(data[0..8].try_into().unwrap());
                    let last = u64::from_le_bytes(data[24..32].try_into().unwrap());
                    self.last_gpu = Some(
                        last.saturating_sub(first) as f64
                            * self.queue.get_timestamp_period() as f64
                            / 1e6,
                    );
                    if self.detailed_timestamps {
                        self.pass_gpu = timing::decode(&data, self.queue.get_timestamp_period() as f64);
                        for (name, value) in &mut self.pass_gpu { if !slot.active.contains(&name.as_str()) { *value = 0.; } }
                        let ranges: Vec<_> = slot.active.iter().filter(|n| **n != "frame").filter_map(|name| {
                            let k = timing::index(name) as usize * 8;
                            let a = u64::from_le_bytes(data[k..k+8].try_into().unwrap());
                            let b = u64::from_le_bytes(data[k+8..k+16].try_into().unwrap());
                            (b > a && a > 0).then_some((a,b))
                        }).collect();
                        self.last_gpu = ranges.iter().map(|p| p.0).min().zip(ranges.iter().map(|p| p.1).max()).map(|(a,b)| (b-a) as f64 * self.queue.get_timestamp_period() as f64 / 1e6);
                        self.pass_gpu.insert("frame".into(), self.last_gpu.unwrap_or(0.));
                    }
                    for (k, name) in ["instances_submitted", "culled_frustum", "culled_below_pixel", "triangles_submitted", "edge_quads_input", "edge_quads_surviving"].iter().enumerate() {
                        let at = timing::BYTES + k*4;
                        self.last_counters.insert(name.to_string(), u32::from_le_bytes(data[at..at+4].try_into().unwrap()) as u64);
                    }
                    drop(data);
                    slot.read.unmap();
                }
                slot.pending = None;
            }
        }
        let timing_slot = self.timings.iter().position(|s| s.pending.is_none());
        let s = self
            .scene
            .as_ref()
            .ok_or_else(|| PyValueError::new_err("set_scene first"))?;
        let polled = Instant::now();
        let frame = if present { Some(self.surface.get_current_texture()
            .map_err(|e| PyValueError::new_err(e.to_string()))?) } else { None };
        let target = frame.as_ref().map(|f| &f.texture).unwrap_or(&self.offscreen);
        let acquired = Instant::now();
        self.last_acquire = acquired.duration_since(polled).as_secs_f64() * 1000.;
        let color = target.create_view(&Default::default());
        let depth = self.depth.create_view(&Default::default());
        let ids = self.ids.create_view(&Default::default());
        let mut e = self.device.create_command_encoder(&Default::default());
        let tq = self.queries.as_ref().filter(|_| self.detailed_timestamps);
        self.background.draw(&mut e, &color, tq);
        e.clear_buffer(&s.counters, 0, None);
        e.copy_buffer_to_buffer(if self.look.data[6][0] > 0. { &s.template } else { &s.hard_template }, 0, &s.commands, 0, s.p as u64 * 40);
        {
            let mut pass = e.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: None,
                timestamp_writes: self
                    .queries
                    .as_ref()
                    .map(|q| wgpu::ComputePassTimestampWrites {
                        query_set: q,
                        beginning_of_pass_write_index: Some(timing::index("culling")),
                        end_of_pass_write_index: Some(timing::index("culling")+1),
                    }),
            });
            pass.set_pipeline(&self.compute);
            pass.set_bind_group(0, &s.compute, &[]);
            pass.dispatch_workgroups(s.n.div_ceil(64), 1, 1);
        }
        let plan = PassPlan::new(self.antialias, self.style, self.look.data[6][2] != 0., self.ao.active(self.style));
        let msaa = plan.msaa && !self.pick_pending;
        self.stable_frames = self.stable_frames.saturating_add(1);
        let color_only = !msaa && !self.edges && self.style != 4 && !plan.ao && !plan.xray;
        let draw_ids = if color_only { needs_settled_ids(self.pick_pending, self.ids_dirty, self.stable_frames) }
            else { needs_id_pass(msaa, self.pick_pending, self.ids_dirty, self.stable_frames) };
        if plan.xray { self.transparency.draw(&mut e, &color, s, self.multi, tq); }

        let ao_active = plan.ao;
        for edge_only in [false, true] {
            if edge_only && !(self.edges || self.style == 4 || ao_active) { break; }
            if !msaa || self.pick_pending {
            let mut pass = e.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: None,
                color_attachments: &[
                    Some(wgpu::RenderPassColorAttachment {
                        view: &color,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Load,
                            store: wgpu::StoreOp::Store,
                        },
                    }),
                    (draw_ids || ao_active).then_some(wgpu::RenderPassColorAttachment {
                        view: &ids,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: if edge_only { wgpu::LoadOp::Load } else { wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT) },
                            store: wgpu::StoreOp::Store,
                        },
                    }),
                ],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &depth,
                    depth_ops: Some(wgpu::Operations {
                        load: if edge_only { wgpu::LoadOp::Load } else { wgpu::LoadOp::Clear(1.) },
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: tq.map(|q| {
                    let name = if edge_only { "edge_quads" } else { "faces" };
                    wgpu::RenderPassTimestampWrites { query_set: q,
                        beginning_of_pass_write_index: Some(timing::index(name)),
                        end_of_pass_write_index: Some(timing::index(name)+1) }
                }),
                occlusion_query_set: None,
            });
            pass.set_pipeline(if self.style == 1 || msaa {
                &self.xray
            } else if !draw_ids {
                &self.draw_noids
            } else if self.textures.layers == 1 {
                &self.draw_plain
            } else {
                &self.draw
            });
            pass.set_bind_group(
                0,
                if self.style == 1 || msaa {
                    &s.xray_draw
                } else {
                    &s.draw
                },
                &[],
            );
            pass.set_bind_group(1, &self.look_groups[if self.style == 1 || msaa { 1 } else { 0 }], &[]);
            pass.set_bind_group(2, &self.texture_groups[usize::from(self.style == 1 || msaa)], &[]);
            pass.set_vertex_buffer(0, s.vertex.slice(..));
            pass.set_index_buffer(s.index.slice(..), wgpu::IndexFormat::Uint32);
            if !edge_only && self.style != 4 {
                if self.style != 1 && !msaa {
                    for &(first, count, plain) in &s.face_ranges {
                        pass.set_pipeline(match (plain, draw_ids) {
                            (true, true) => &self.draw_plain, (false, true) => &self.draw,
                            (true, false) => &self.plain_noids, (false, false) => &self.draw_noids,
                        });
                        if self.multi { pass.multi_draw_indexed_indirect(&s.commands, first as u64 * 20, count); }
                        else { for k in first..first+count { pass.draw_indexed_indirect(&s.commands, k as u64 * 20); } }
                    }
                } else if self.multi {
                    pass.multi_draw_indexed_indirect(&s.commands, 0, s.p);
                } else {
                    for k in 0..s.p { pass.draw_indexed_indirect(&s.commands, k as u64 * 20); }
                }
            }
            if !msaa && edge_only && (self.edges || self.style == 4) {
                for hidden in [true, false] {
                    if hidden && self.style != 1 && self.look.data[6][2] == 0. { continue; }
                    pass.set_pipeline(if hidden { &self.xray_edge } else if self.look.data[6][0] == 0. { &self.hard_edge } else { &self.edge });
                    pass.set_bind_group(0, if hidden { &s.xray_edge_draw } else { &s.edge_draw }, &[]);
                    pass.set_bind_group(1, &self.look_groups[if hidden { 3 } else { 2 }], &[]);
                    if self.multi {
                        for k in s.p..s.p*2 { pass.draw_indirect(&s.commands, k as u64*20); }
                    } else {
                        for k in s.p..s.p * 2 { pass.draw_indirect(&s.commands, k as u64 * 20); }
                    }
                }
                if self.style == 1 && self.look.data[6][0] > 0. {
                    pass.set_pipeline(&self.profile_top);
                    pass.set_bind_group(0, &s.profile_draw, &[]);
                    pass.set_bind_group(1, &self.look_groups[4], &[]);
                    if self.multi { for k in s.p..s.p*2 { pass.draw_indirect(&s.commands, k as u64*20); } }
                    else { for k in s.p..s.p*2 { pass.draw_indirect(&s.commands, k as u64*20); } }
                }
            }
            drop(pass);
            }
            if msaa && !self.pick_pending {
                self.aa.draw(&mut e, &color, s, self.style, self.edges, self.look.data[6][0] > 0., self.multi, self.queries.as_ref(), Some(edge_only), self.sections.count > 0);
            }
            if !edge_only && ao_active {
                // Caps must contribute depth before AO reconstructs its normals.
                // Submit once here; the non-AO path keeps the final color pass.
                if self.sections.count > 0 {
                    if msaa {
                        self.sections.draw(&mut e, &self.aa.color_view(), &self.aa.depth_view(), Some(&color), tq, &self.camera_data);
                    } else {
                        self.sections.draw(&mut e, &color, &depth, None, tq, &self.camera_data);
                    }
                }
                if msaa { self.aa.resolve_depth(&self.device, &mut e, &depth, tq); }
                let output = if msaa && !self.pick_pending { self.aa.color_view() } else { target.create_view(&Default::default()) };
                self.ao.draw(&self.device, &self.queue, &mut e, target, &depth, &output, msaa && !self.pick_pending, tq);
            }
        }
        if (!msaa || self.pick_pending) && (draw_ids || ao_active) { self.ids_dirty = false; }
        if self.sections.count > 0 && !ao_active {
            if msaa && !self.pick_pending {
                self.sections.draw(&mut e, &self.aa.color_view(), &self.aa.depth_view(), Some(&color), tq, &self.camera_data);
            } else {
                self.sections.draw(&mut e, &color, &depth, None, tq, &self.camera_data);
            }
        }
        self.overlay
            .draw(&mut e, &color, self.config.width, self.config.height, tq);
        if let (Some(q), Some(k)) = (&self.queries, timing_slot) {
            e.resolve_query_set(q, 0..if self.detailed_timestamps { timing::COUNT } else { 4 }, &self.resolve, 0);
            e.copy_buffer_to_buffer(&self.resolve, 0, &self.timings[k].read, 0, timing::BYTES as u64);
            e.copy_buffer_to_buffer(&s.counters, 0, &self.timings[k].read, timing::BYTES as u64, 32);
        }
        let stride = (self.config.width * 4).div_ceil(256) * 256;
        let capture = self.capture_next.then(|| {
            let read = self.device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("surface capture"),
                size: stride as u64 * self.config.height as u64,
                usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                mapped_at_creation: false,
            });
            e.copy_texture_to_buffer(
                wgpu::TexelCopyTextureInfo {
                    texture: target,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                wgpu::TexelCopyBufferInfo {
                    buffer: &read,
                    layout: wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some(stride),
                        rows_per_image: Some(self.config.height),
                    },
                },
                wgpu::Extent3d {
                    width: self.config.width,
                    height: self.config.height,
                    depth_or_array_layers: 1,
                },
            );
            read
        });
        let command = e.finish();
        let encoded = Instant::now();
        self.queue.submit([command]);
        let submitted = Instant::now();
        if let Some(read) = capture {
            let (tx, rx) = std::sync::mpsc::channel();
            read.slice(..).map_async(wgpu::MapMode::Read, move |r| {
                let _ = tx.send(r);
            });
            self.device.poll(wgpu::Maintain::Wait);
            rx.recv()
                .map_err(|e| PyValueError::new_err(e.to_string()))?
                .map_err(|e| PyValueError::new_err(e.to_string()))?;
            let mapped = read.slice(..).get_mapped_range();
            let mut rgba =
                Vec::with_capacity((self.config.width * self.config.height * 4) as usize);
            for row in mapped.chunks_exact(stride as usize) {
                rgba.extend_from_slice(&row[..self.config.width as usize * 4]);
            }
            if matches!(
                self.config.format,
                wgpu::TextureFormat::Bgra8UnormSrgb | wgpu::TextureFormat::Bgra8Unorm
            ) {
                for pixel in rgba.chunks_exact_mut(4) {
                    pixel.swap(0, 2);
                }
            }
            drop(mapped);
            read.unmap();
            self.captured = Some(rgba);
            self.capture_next = false;
        }
        let before_present = Instant::now();
        if let Some(frame) = frame { frame.present(); }
        self.frame_stages = [polled.duration_since(start), acquired.duration_since(polled),
            encoded.duration_since(acquired), submitted.duration_since(encoded), before_present.elapsed()]
            .map(|d| d.as_secs_f64()*1000.);
        let cpu = start.elapsed().as_secs_f64() * 1000.;
        if let (Some(_), Some(k)) = (&self.queries, timing_slot) {
            let (tx, rx) = std::sync::mpsc::channel();
            self.timings[k]
                .read
                .slice(..)
                .map_async(wgpu::MapMode::Read, move |r| {
                    let _ = tx.send(r);
                });
            self.timings[k].pending = Some(rx);
            let mut active = vec!["background", "culling", "overlay", "frame"];
            if self.sections.count > 0 { active.push("section_caps"); }
            if !msaa { active.push("faces"); if !msaa && (self.edges || self.style == 4) { active.push("edge_quads"); } }
            if msaa && !self.pick_pending { active.push("antialias"); if ao_active || self.edges || self.style == 4 { active.push("antialias_edges"); } }
            if self.style == 1 { active.extend(["xray_accumulation", "xray_composite"]); }
            if ao_active && msaa { active.push("ao_inputs"); }
            if ao_active { active.extend(["ao_kernel", "ao_blur_x", "ao_blur_y", "ao_upsample_composite"]); }
            self.timings[k].active = active;
        }
        if msaa && needs_settled_ids(false, self.ids_dirty, self.stable_frames) { self.ensure_ids()?; }
        self.last_cpu = cpu;
        Ok((cpu, self.last_gpu))
    }
    /// Poll/readback, acquire, encode, submit, present, in milliseconds.
    fn frame_stage_timings(&self) -> Vec<f64> { self.frame_stages.to_vec() }
    fn request_capture(&mut self) {
        self.capture_next = true;
    }
    fn take_capture(&mut self) -> Option<Vec<u8>> {
        self.captured.take()
    }
    fn set_overlay(
        &mut self,
        width: u32,
        height: u32,
        rgba: PyReadonlyArray1<'_, u8>,
    ) -> PyResult<()> {
        let bytes = rgba.as_slice()?;
        if width != self.config.width
            || height != self.config.height
            || bytes.len() as u64 != width as u64 * height as u64 * 4
        {
            return Err(PyValueError::new_err(
                "overlay must match physical surface RGBA dimensions",
            ));
        }
        self.overlay
            .upload(&self.device, &self.queue, width, height, bytes);
        Ok(())
    }
    fn last_timings(&self) -> (f64, Option<f64>, f64, std::collections::BTreeMap<String, Option<f64>>, std::collections::BTreeMap<String, u64>) {
        let mut counters = self.last_counters.clone();
        counters.insert("texture_layers".into(), self.textures.layers as u64);
        counters.insert("instances_input".into(), self.scene.as_ref().map_or(0, |s| s.n as u64));
        counters.insert("depth_prepass".into(), 0);
        let mut passes: std::collections::BTreeMap<_, _> = self.pass_gpu.iter().map(|(n,v)| (n.clone(), Some(*v))).collect();
        passes.insert("id".into(), self.last_pick_gpu);
        for name in ["profile_top", "profile_classification", "present"] {
            passes.insert(name.into(), None);
        }
        passes.insert("depth_prepass".into(), Some(0.));
        (self.last_cpu, self.last_gpu, self.last_acquire, passes, counters)
    }
    fn ensure_ids(&mut self) -> PyResult<()> { self.ensure_ids_region(None) }
    fn ensure_ids_region(&mut self, cursor: Option<(u32, u32)>) -> PyResult<()> {
        if !self.ids_dirty { return Ok(()); }
        // Wireframe IDs include edge-only geometry; retain its existing semantics.
        if self.style == 4 {
            self.pick_pending = true;
            let result = self.render(false);
            self.pick_pending = false;
            result?;
        } else {
            let s = self.scene.as_ref().ok_or_else(|| PyValueError::new_err("set_scene first"))?;
            let mut encoder = self.device.create_command_encoder(&Default::default());
            encoder.copy_buffer_to_buffer(&s.hard_template, 0, &s.commands, 0, s.p as u64 * 40);
            let cursor_group = cursor.filter(|_| self.camera_data.len() == 28).map(|(x,y)| {
                let mut camera = self.camera_data.clone();
                let margin = self.look.data[2][3].max(self.look.data[6][1]).max(1.);
                camera[24..28].copy_from_slice(&pick_bounds(x, y, self.config.width, self.config.height, margin));
                let camera = buffer(&self.device, bytemuck::cast_slice(&camera), wgpu::BufferUsages::UNIFORM);
                bind_prototypes(&self.device, &self.compute.get_bind_group_layout(0),
                    &[&camera, &s.inst, &s.protos, &s.commands, &s.survivors, &s.viewpoints, &s.counters], s.p)
            });
            {
                let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
                pass.set_pipeline(if cursor_group.is_some() { &self.compute_pick } else { &self.compute });
                pass.set_bind_group(0, cursor_group.as_ref().unwrap_or(&s.compute), &[]);
                pass.dispatch_workgroups(s.n.div_ceil(64), 1, 1);
            }
            let color = self.offscreen.create_view(&Default::default());
            let ids = self.ids.create_view(&Default::default());
            let depth = self.depth.create_view(&Default::default());
            {
                // Depth-only color writes retain texture alpha rejection, but no
                // background, edges, AO, multisampling, overlay or presentation.
                let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("pick IDs"),
                    color_attachments: &[
                        Some(wgpu::RenderPassColorAttachment { view: &color, resolve_target: None,
                            ops: wgpu::Operations { load: wgpu::LoadOp::Load, store: wgpu::StoreOp::Store } }),
                        Some(wgpu::RenderPassColorAttachment { view: &ids, resolve_target: None,
                            ops: wgpu::Operations { load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT), store: wgpu::StoreOp::Store } }),
                    ],
                    depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                        view: &depth, stencil_ops: None,
                        depth_ops: Some(wgpu::Operations { load: wgpu::LoadOp::Clear(1.), store: wgpu::StoreOp::Store }),
                    }),
                    timestamp_writes: timing::writes(self.queries.as_ref(), "id"), occlusion_query_set: None,
                });
                if let Some((x, y)) = cursor { pass.set_scissor_rect(x, y, 1, 1); }
                pass.set_pipeline(&self.xray);
                pass.set_bind_group(0, &s.xray_draw, &[]);
                pass.set_bind_group(1, &self.look_groups[1], &[]);
                pass.set_bind_group(2, &self.texture_groups[1], &[]);
                pass.set_vertex_buffer(0, s.vertex.slice(..));
                pass.set_index_buffer(s.index.slice(..), wgpu::IndexFormat::Uint32);
                if self.multi { pass.multi_draw_indexed_indirect(&s.commands, 0, s.p); }
                else { for k in 0..s.p { pass.draw_indexed_indirect(&s.commands, k as u64 * 20); } }
                // Loose line prototypes have no faces to identify. Keep those
                // pickable without replaying the edges of shaded prototypes.
                if self.edges {
                    pass.set_pipeline(&self.edge);
                    pass.set_bind_group(0, &s.edge_draw, &[]);
                    pass.set_bind_group(1, &self.look_groups[2], &[]);
                    for k in 0..s.p as usize {
                        if s.template_data[k*20..k*20+4] == [0; 4] {
                            pass.draw_indirect(&s.commands, (s.p as usize+k) as u64 * 20);
                        }
                    }
                }
            }
            self.queue.submit(Some(encoder.finish()));
            self.ids_dirty = !ids_complete(cursor);
        }
        Ok(())
    }
    /// Visible IDs in a physical-pixel, half-open rectangle; explicit picking may wait.
    fn pick_rect(&mut self, x0: u32, y0: u32, x1: u32, y1: u32) -> PyResult<Vec<u32>> {
        let x = x0.min(x1).min(self.config.width);
        let y = y0.min(y1).min(self.config.height);
        let w = x0.max(x1).min(self.config.width) - x;
        let h = y0.max(y1).min(self.config.height) - y;
        if w == 0 || h == 0 {
            return Ok(vec![]);
        }
        self.ensure_ids()?;
        let stride = (w * 4).div_ceil(256) * 256;
        let read = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("rectangle pick"),
            size: stride as u64 * h as u64,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mut e = self.device.create_command_encoder(&Default::default());
        e.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &self.ids,
                mip_level: 0,
                origin: wgpu::Origin3d { x, y, z: 0 },
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &read,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(stride),
                    rows_per_image: Some(h),
                },
            },
            wgpu::Extent3d {
                width: w,
                height: h,
                depth_or_array_layers: 1,
            },
        );
        self.queue.submit([e.finish()]);
        let (tx, rx) = std::sync::mpsc::channel();
        read.slice(..).map_async(wgpu::MapMode::Read, move |r| {
            let _ = tx.send(r);
        });
        self.device.poll(wgpu::Maintain::Wait);
        rx.recv()
            .map_err(|e| PyValueError::new_err(e.to_string()))?
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        let bytes = read.slice(..).get_mapped_range();
        let mut ids = std::collections::BTreeSet::new();
        for row in bytes.chunks_exact(stride as usize) {
            for b in row[..w as usize * 4].chunks_exact(4) {
                let id = u32::from_le_bytes(b.try_into().unwrap());
                if id != 0 {
                    ids.insert(id - 1);
                }
            }
        }
        drop(bytes);
        read.unmap();
        Ok(ids.into_iter().collect())
    }
    #[getter]
    fn gpu_memory(&self) -> u64 {
        self.scene.as_ref().map_or(0, |s| {
            [&s.vertex, &s.index, &s.edge_records, &s.inst, &s.protos,
             &s.survivors, &s.viewpoints, &s.commands, &s.template, &s.hard_template]
                .iter().map(|b| b.size()).sum::<u64>() + 112 + 416
        }) + self.textures.bytes + self.textures.materials.size()
    }

    #[getter]
    fn pick_cache_valid(&self) -> bool { !self.ids_dirty }

    fn pick(&mut self, x: u32, y: u32) -> PyResult<i64> {
        if x >= self.config.width || y >= self.config.height {
            return Ok(-1);
        }
        let measure_id = self.ids_dirty && self.style != 4 && self.queries.is_some();
        self.ensure_ids_region(Some((x, y)))?;
        let mut e = self.device.create_command_encoder(&Default::default());
        e.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &self.ids,
                mip_level: 0,
                origin: wgpu::Origin3d { x, y, z: 0 },
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &self.read,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(256),
                    rows_per_image: Some(1),
                },
            },
            wgpu::Extent3d {
                width: 1,
                height: 1,
                depth_or_array_layers: 1,
            },
        );
        if measure_id {
            let first = timing::index("id");
            e.resolve_query_set(self.queries.as_ref().unwrap(), first..first+2, &self.resolve, 0);
            e.copy_buffer_to_buffer(&self.resolve, 0, &self.read, 8, 16);
        }
        self.queue.submit([e.finish()]);
        let b = self.readback(if measure_id { 24 } else { 4 })?;
        self.last_pick_gpu = measure_id.then(|| {
            let first = u64::from_le_bytes(b[8..16].try_into().unwrap());
            let last = u64::from_le_bytes(b[16..24].try_into().unwrap());
            last.saturating_sub(first) as f64 * self.queue.get_timestamp_period() as f64 / 1e6
        });
        Ok(u32::from_le_bytes(b[..4].try_into().unwrap()) as i64 - 1)
    }
}
impl Renderer {
    fn readback(&self, n: u64) -> PyResult<Vec<u8>> {
        let slice = self.read.slice(..n);
        let (tx, rx) = std::sync::mpsc::channel();
        slice.map_async(wgpu::MapMode::Read, move |r| {
            let _ = tx.send(r);
        });
        self.device.poll(wgpu::Maintain::Wait);
        rx.recv()
            .unwrap()
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        let bytes = slice.get_mapped_range().to_vec();
        self.read.unmap();
        Ok(bytes)
    }
}
#[pymodule]
fn ingetrazo_render(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Renderer>()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn indirect_layout() {
        assert_eq!(std::mem::size_of::<Command>(), 20);
        assert_eq!(std::mem::offset_of!(Command, start), 16);
        assert_eq!(std::mem::offset_of!(Command, instances), 4);
    }
}

/// Reference of the shader's conservative homogeneous eight-corner test.
#[cfg(test)]
fn visible(
    vp: glam::Mat4,
    world: glam::Mat4,
    lo: glam::Vec3,
    hi: glam::Vec3,
    size: glam::Vec2,
) -> bool {
    let m = vp * world;
    let mut rejected = [0; 6];
    let mut low = glam::Vec2::splat(f32::INFINITY);
    let mut high = glam::Vec2::splat(f32::NEG_INFINITY);
    let mut crosses = false;
    for k in 0..8 {
        let p = glam::vec3(
            if k & 1 != 0 { hi.x } else { lo.x },
            if k & 2 != 0 { hi.y } else { lo.y },
            if k & 4 != 0 { hi.z } else { lo.z },
        );
        let q = m * p.extend(1.);
        for (i, out) in [
            q.x < -q.w,
            q.y < -q.w,
            q.z < 0.,
            q.x > q.w,
            q.y > q.w,
            q.z > q.w,
        ]
        .iter()
        .enumerate()
        {
            rejected[i] += *out as u32;
        }
        if q.w <= 0. {
            crosses = true;
        } else {
            let xy = glam::vec2(q.x, q.y) / q.w;
            low = low.min(xy);
            high = high.max(xy);
        }
    }
    !rejected.contains(&8) && (crosses || ((high - low) * size * 0.5).max_element() >= 1.)
}
#[cfg(test)]
mod reference_tests {
    use super::*;
    use glam::*;
    #[test]
    fn clip_planes_and_pixel_size() {
        let lo = vec3(-0.1, -0.1, 0.2);
        let hi = vec3(0.1, 0.1, 0.4);
        assert!(visible(
            Mat4::IDENTITY,
            Mat4::IDENTITY,
            lo,
            hi,
            Vec2::splat(1000.)
        ));
        for shift in [
            vec3(2., 0., 0.),
            vec3(-2., 0., 0.),
            vec3(0., 2., 0.),
            vec3(0., -2., 0.),
            vec3(0., 0., 2.),
            vec3(0., 0., -2.),
        ] {
            assert!(!visible(
                Mat4::IDENTITY,
                Mat4::from_translation(shift),
                lo,
                hi,
                Vec2::splat(1000.)
            ));
        }
        assert!(!visible(
            Mat4::IDENTITY,
            Mat4::from_scale(Vec3::splat(0.001)),
            lo,
            hi,
            Vec2::splat(1000.)
        ));
    }
    #[test]
    fn mirrored_and_sheared_boxes_remain_visible() {
        let world = Mat4::from_cols(
            vec4(-2., 0., 0., 0.),
            vec4(0.5, 1., 0., 0.),
            Vec4::Z,
            Vec4::W,
        );
        assert!(visible(
            Mat4::IDENTITY,
            world,
            vec3(-0.1, -0.1, 0.),
            vec3(0.1, 0.1, 0.5),
            Vec2::splat(1000.)
        ));
    }
    #[test]
    fn compact_into_disjoint_capacity_ranges() {
        let codes = [1, 0, 1, 2, 0];
        let keep = [true, false, true, true, true];
        let starts = [0, 2, 4];
        let mut counts = [0; 3];
        let mut out = [u32::MAX; 5];
        for (i, &code) in codes.iter().enumerate() {
            if keep[i] {
                out[starts[code] + counts[code]] = i as u32;
                counts[code] += 1;
            }
        }
        assert_eq!(counts, [1, 2, 1]);
        assert_eq!(out, [4, u32::MAX, 0, 2, 3]);
        // Reset between frames; no stale counts may survive the template copy.
        counts.fill(0);
        assert_eq!(counts, [0, 0, 0]);
    }
}

// The single-sample path supplies color and IDs together. MSAA only needs
// the extra pass for an explicit pick or once after the camera settles.
fn needs_id_pass(msaa: bool, pick_pending: bool, dirty: bool, stable_frames: u32) -> bool {
    !msaa || pick_pending || (dirty && stable_frames >= 2)
}

#[cfg(test)]
mod id_schedule_tests {
    #[test]
    fn multisample_color_does_not_replay_geometry_for_idle_picking() {
        assert!(!super::needs_id_pass(true, false, true, 1));
        assert!(super::needs_id_pass(true, true, true, 0));
        assert!(super::needs_id_pass(false, false, true, 0));
        assert!(super::needs_id_pass(false, true, true, 0));
        assert!(super::needs_id_pass(true, false, true, 2));
        assert!(!super::needs_id_pass(true, false, false, 3));
    }
}

#[cfg(test)]
mod update_tests {
    use super::*;

    #[test]
    fn growth_doubles_and_never_shrinks() {
        assert_eq!(grown_capacity(8, 9), 16);
        assert_eq!(grown_capacity(16, 4), 16);
        assert_eq!(grown_capacity(8, 33), 64);
        assert_eq!(grown_capacity(0, 0), 1);
    }

    #[test]
    fn scattered_updates_use_one_enclosing_write() {
        assert_eq!(row_runs(vec![4, 1, 2, 2, 8]), vec![(1, 9)]);
        assert!(row_runs(vec![]).is_empty());
        assert_eq!(row_runs((0..1000).rev().collect()), vec![(0, 1000)]);
    }

    #[test]
    fn row_updates_preserve_selection_and_hover() {
        assert_eq!(merge_instance_flags(6, 1), 7);
        assert_eq!(merge_instance_flags(7, 0), 6);
        assert_eq!(merge_instance_flags(0, 6), 0);
    }
}

// Sparse rows contain a back color followed by front/back texture indices.
// Only the fragment texture branch is specialized: vertex paint lookup stays.
fn face_ranges(data: &[u8], prototypes: u32) -> Vec<(u32, u32, bool)> {
    let word = |at: usize| data.get(at..at+4).map(|b| u32::from_le_bytes(b.try_into().unwrap()));
    let mut runs: Vec<(u32, u32, bool)> = Vec::new();
    for p in 0..prototypes {
        let header = p as usize * 16;
        let plain = match (word(header+4), word(header+8)) {
            (Some(start), Some(count)) => (0..count as usize).all(|i| {
                let row = (start as usize+i*2+1)*16;
                word(row+4) == Some(0) && word(row+8) == Some(0)
            }),
            _ => false,
        };
        if let Some(last) = runs.last_mut().filter(|r| r.2 == plain) { last.1 += 1; }
        else { runs.push((p, 1, plain)); }
    }
    runs
}
#[cfg(test)]
mod plain_face_tests {
    #[test]
    fn sparse_texture_indices_split_only_textured_prototypes() {
        let mut words = vec![0u32; 24];
        words[5] = 3; words[6] = 1; // prototype 1 has one sparse vertex
        words[17] = 2; // its front texture
        assert_eq!(super::face_ranges(bytemuck::cast_slice(&words), 3), vec![(0,1,true),(1,1,false),(2,1,true)]);
        words[17] = 0; words[18] = 2; // back texture also needs alpha rejection
        assert_eq!(super::face_ranges(bytemuck::cast_slice(&words), 3)[1], (1,1,false));
        words[18] = 0;
        assert_eq!(super::face_ranges(bytemuck::cast_slice(&words), 3), vec![(0,3,true)]);
        assert_eq!(super::face_ranges(&[], 1), vec![(0,1,false)]);
    }
}

struct PassPlan { msaa: bool, ao: bool, xray: bool }
impl PassPlan {
    fn new(antialias: bool, mode: u32, back_edges: bool, ao: bool) -> Self {
        Self { msaa: antialias && mode != 1 && !back_edges,
            ao: ao && mode != 1 && mode != 4, xray: mode == 1 }
    }
}
#[cfg(test)]
mod pass_plan_tests {
    #[test]
    fn disabled_features_encode_no_optional_passes() {
        let p = super::PassPlan::new(false, 0, false, false);
        assert!(!p.msaa && !p.ao && !p.xray);
        let p = super::PassPlan::new(true, 1, false, true);
        assert!(p.xray && !p.msaa && !p.ao);
        let p = super::PassPlan::new(true, 4, true, true);
        assert!(!p.msaa && !p.ao && !p.xray);
        let p = super::PassPlan::new(true, 0, false, true);
        assert!(p.msaa && p.ao && !p.xray);
    }
}

fn needs_settled_ids(pick: bool, dirty: bool, stable: u32) -> bool { pick || (dirty && stable >= 2) }
#[cfg(test)]
mod color_only_schedule_tests {
    #[test]
    fn settled_color_does_not_clear_or_write_an_id_target() {
        assert!(!super::needs_settled_ids(false, false, 4));
        assert!(!super::needs_settled_ids(false, true, 1));
        assert!(super::needs_settled_ids(false, true, 2));
        assert!(super::needs_settled_ids(true, true, 0));
    }
}

#[cfg(test)]
mod cursor_schedule_tests {
    #[test]
    fn cursor_refine_does_not_validate_the_full_frame() {
        assert!(!super::ids_complete(Some((10, 20))));
        assert!(super::ids_complete(None));
        assert!(!super::needs_settled_ids(false, true, 1));
        assert!(super::needs_settled_ids(false, true, 2));
        assert!(super::needs_settled_ids(true, true, 0));
    }
}
fn ids_complete(cursor: Option<(u32, u32)>) -> bool { cursor.is_none() }

fn pick_bounds(x: u32, y: u32, width: u32, height: u32, margin: f32) -> [f32; 4] {
    [2.*(x as f32-margin)/width as f32-1., 1.-2.*(y as f32+1.+margin)/height as f32,
     2.*(x as f32+1.+margin)/width as f32-1., 1.-2.*(y as f32-margin)/height as f32]
}
#[cfg(test)]
mod pick_bounds_tests {
    #[test]
    fn cursor_bounds_include_pixel_and_wide_loose_edges() {
        let b = super::pick_bounds(49, 49, 100, 100, 2.);
        for p in [[-0.02,0.02], [0.,0.], [-0.05,0.05]] {
            assert!(p[0] >= b[0] && p[0] <= b[2] && p[1] >= b[1] && p[1] <= b[3]);
        }
        assert!(b[0] < 0. && b[1] < 0. && b[2] > 0. && b[3] > 0.);
    }
}
