//! Resident material image array. Repeat and trilinear filtering match GL.
pub struct Textures {
    pub view: wgpu::TextureView,
    pub sampler: wgpu::Sampler,
    pub bytes: u64,
    pub materials: wgpu::Buffer,
}
impl Textures {
    pub fn new(
        d: &wgpu::Device,
        q: &wgpu::Queue,
        width: u32,
        height: u32,
        layers: u32,
        levels: &[Vec<u8>],
    ) -> Self {
        let texture = d.create_texture(&wgpu::TextureDescriptor {
            label: Some("material image array"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: layers,
            },
            mip_level_count: levels.len() as u32,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        for (level, data) in levels.iter().enumerate() {
            let w = (width >> level).max(1);
            let h = (height >> level).max(1);
            q.write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: &texture,
                    mip_level: level as u32,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                data,
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(w * 4),
                    rows_per_image: Some(h),
                },
                wgpu::Extent3d {
                    width: w,
                    height: h,
                    depth_or_array_layers: layers,
                },
            );
        }
        Self {
            materials: crate::buffer(d, &[0;16], wgpu::BufferUsages::STORAGE),
            view: texture.create_view(&wgpu::TextureViewDescriptor {
                dimension: Some(wgpu::TextureViewDimension::D2Array),
                ..Default::default()
            }),
            sampler: d.create_sampler(&wgpu::SamplerDescriptor {
                address_mode_u: wgpu::AddressMode::Repeat,
                address_mode_v: wgpu::AddressMode::Repeat,
                mag_filter: wgpu::FilterMode::Linear,
                min_filter: wgpu::FilterMode::Linear,
                mipmap_filter: wgpu::FilterMode::Linear,
                ..Default::default()
            }),
            bytes: levels.iter().map(|v| v.len() as u64).sum(),
        }
    }
    pub fn bind(&self, d: &wgpu::Device, p: &wgpu::RenderPipeline) -> wgpu::BindGroup {
        d.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("material textures"),
            layout: &p.get_bind_group_layout(2),
            entries: &[
                wgpu::BindGroupEntry { binding: 2, resource: self.materials.as_entire_binding() },
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&self.view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                },
            ],
        })
    }
}
