//! Style uniforms are independent of scene buffers and survive scene replacement.
use pyo3::{exceptions::PyValueError, prelude::*, types::PyDict};
use wgpu::util::DeviceExt;

pub struct Style {
    pub buffer: wgpu::Buffer,
    pub data: [[f32; 4]; 9],
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
            [1., 1., 0., 4.],
            [0.; 4],
            [0.7, 0.7, 0.7, 0.],
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
            if let Some(v) = d.get_item("fade_color")? {
                let rgb: [f32; 3] = v.extract()?;
                if rgb.iter().any(|x| !x.is_finite() || !(0. ..=1.).contains(x)) {
                    return Err(PyValueError::new_err("invalid fade color"));
                }
                next[8][..3].copy_from_slice(&rgb);
            }
            if let Some(v) = d.get_item("fade")? {
                let fade: f32 = v.extract()?;
                if !fade.is_finite() || !(0. ..=1.).contains(&fade) {
                    return Err(PyValueError::new_err("invalid fade factor"));
                }
                next[8][3] = fade;
            }
            if let Some(v) = d.get_item("section_plane")? {
                let plane: [f32; 4] = v.extract()?;
                if plane.iter().any(|v| !v.is_finite()) {
                    return Err(PyValueError::new_err("section plane must be finite"));
                }
                next[7] = plane;
            }
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
            for (index, name) in [(0, "profiles"), (2, "back_edges")] {
                if let Some(v) = d.get_item(name)? { next[6][index] = if v.extract::<bool>()? { 1. } else { 0. }; }
            }
            for (index, name) in [(1, "profile_width"), (3, "dash_width")] {
                if let Some(v) = d.get_item(name)? {
                    let width: f32 = v.extract()?;
                    if !width.is_finite() || !(0.0..=64.0).contains(&width) {
                        return Err(PyValueError::new_err("profile/dash width must be in [0,64]"));
                    }
                    next[6][index] = width;
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

#[cfg(test)]
mod section_tests {
    #[test]
    fn section_and_fade_uniform_offsets() {
        let data = [[0f32; 4]; 9];
        assert_eq!(std::mem::size_of_val(&data), 144);
        assert_eq!(data[7].as_ptr() as usize - data.as_ptr() as usize, 112);
        assert_eq!(data[8].as_ptr() as usize - data.as_ptr() as usize, 128);
    }

    #[test]
    fn every_geometry_fragment_path_applies_the_section() {
        let shader = include_str!("shading.wgsl");
        for name in ["face_pixel", "edge_pixel", "depth_fs"] {
            let body = shader.split(&format!("fn {name}(")).nth(1).unwrap();
            assert!(body.split("let front").next().unwrap().contains("section_distance < 0."));
        }
        assert!(include_str!("xray.wgsl").contains("face_pixel(i, front)"));
        assert!(include_str!("antialias.rs").contains("shading.wgsl"));
        assert!(include_str!("edges.wgsl").contains("o.section_distance ="));
    }
}
