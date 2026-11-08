//! Style uniforms are independent of scene buffers and survive scene replacement.
use pyo3::{exceptions::PyValueError, prelude::*, types::PyDict};
use wgpu::util::DeviceExt;

pub struct Style {
    pub buffer: wgpu::Buffer,
    pub data: [[f32; 4]; 6],
}
impl Style {
    pub fn new(d: &wgpu::Device) -> Self {
        let data = [
            [1., 1., 1., 0.],
            [0.62, 0.70, 0.78, 0.],
            [0.13, 0.17, 0.23, 1.],
            [0.9, 0.91, 0.92, 1.],
            [0.925, 0.935, 0.945, 2.],
            [0.815, 0.820, 0.815, 0.],
        ];
        let buffer = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("display style"),
            contents: bytemuck::cast_slice(&data),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        Self { buffer, data }
    }
    pub fn update(
        &mut self,
        value: &Bound<'_, PyAny>,
        q: &wgpu::Queue,
    ) -> PyResult<(u32, Option<bool>)> {
        let mut next = self.data;
        let (name, edges) = if let Ok(d) = value.cast::<PyDict>() {
            for (i, key) in [
                "front_color",
                "back_color",
                "edge_color",
                "background",
                "sky_color",
                "ground_color",
            ]
            .iter()
            .enumerate()
            {
                if let Some(v) = d.get_item(key)? {
                    let rgb: Vec<f32> = v.extract()?;
                    if rgb.len() != 3
                        || rgb
                            .iter()
                            .any(|x| !x.is_finite() || !(0. ..=1.).contains(x))
                    {
                        return Err(PyValueError::new_err(
                            "style colors must be three finite values in [0,1]",
                        ));
                    }
                    next[i][..3].copy_from_slice(&rgb);
                }
            }
            if let Some(v) = d.get_item("edge_width")? {
                let width: f32 = v.extract()?;
                if !width.is_finite() || !(0.0..=64.0).contains(&width) {
                    return Err(PyValueError::new_err("edge width must be in [0,64] physical pixels"));
                }
                next[2][3] = width;
            }
            if let Some(v) = d.get_item("sky")? {
                next[3][3] = if v.extract::<bool>()? { 1. } else { 0. };
            }
            if let Some(v) = d.get_item("horizon")? {
                let h: f32 = v.extract()?;
                if !h.is_finite() {
                    return Err(PyValueError::new_err("nonfinite horizon"));
                }
                next[4][3] = h;
            }
            (
                d.get_item("face_mode")?
                    .map(|v| v.extract::<String>())
                    .transpose()?
                    .unwrap_or("textures".into()),
                d.get_item("edges")?
                    .map(|v| v.extract::<bool>())
                    .transpose()?,
            )
        } else {
            (value.extract::<String>()?, None)
        };
        let mode = match name.as_str() {
            "shaded" | "textures" => 0,
            "xray" => 1,
            "hidden_line" => 2,
            "monochrome" => 3,
            "wireframe" => 4,
            _ => return Err(PyValueError::new_err("unknown display style")),
        };
        if next != self.data {
            q.write_buffer(&self.buffer, 0, bytemuck::cast_slice(&next));
            self.data = next;
        }
        Ok((mode, edges))
    }
}
