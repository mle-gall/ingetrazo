//! Pack resident face vertices directly, avoiding Python triangle gathers.
use crate::facegeom;
use numpy::{PyArray1, PyReadonlyArray1, PyReadonlyArray2};
use pyo3::{exceptions::PyValueError, prelude::*};
use rayon::prelude::*;

#[pyfunction]
pub fn bake_vertices<'py>(
    py: Python<'py>,
    pos: PyReadonlyArray2<'_, f32>,
    corners: PyReadonlyArray1<'_, i64>,
    sizes: PyReadonlyArray1<'_, i64>,
    counts: PyReadonlyArray1<'_, i64>,
    colors: PyReadonlyArray2<'_, u8>,
    hidden: PyReadonlyArray1<'_, bool>,
    hypot: &str,
) -> PyResult<Bound<'py, PyArray1<u8>>> {
    let p = pos.as_array();
    let colors = colors.as_array();
    let hidden = hidden.as_slice()?.to_vec();
    if p.shape()[1] != 3 || colors.shape() != [counts.len()?, 4] || hidden.len() != counts.len()? {
        return Err(PyValueError::new_err(
            "invalid position or face color shape",
        ));
    }
    let pts: Vec<_> = p
        .rows()
        .into_iter()
        .map(|r| facegeom::V3(r[0], r[1], r[2]))
        .collect();
    if corners
        .as_array()
        .iter()
        .any(|&x| x < 0 || x as usize >= pts.len() || x > u32::MAX as i64)
    {
        return Err(PyValueError::new_err("corner out of range"));
    }
    let corners: Vec<u32> = corners.as_array().iter().map(|&x| x as u32).collect();
    if corners.iter().any(|&x| x as usize >= pts.len()) {
        return Err(PyValueError::new_err("corner out of range"));
    }
    let mut offsets = vec![0usize];
    for &n in sizes.as_slice()? {
        if n < 3 {
            return Err(PyValueError::new_err("ring needs three corners"));
        }
        offsets.push(
            offsets
                .last()
                .unwrap()
                .checked_add(n as usize)
                .ok_or_else(|| PyValueError::new_err("ring overflow"))?,
        );
    }
    let mut faces = vec![0usize];
    for &n in counts.as_slice()? {
        if n < 1 {
            return Err(PyValueError::new_err("face needs a ring"));
        }
        faces.push(
            faces
                .last()
                .unwrap()
                .checked_add(n as usize)
                .ok_or_else(|| PyValueError::new_err("face overflow"))?,
        );
    }
    if offsets.last() != Some(&corners.len()) || faces.last() != Some(&(offsets.len() - 1)) {
        return Err(PyValueError::new_err("ring sizes/counts mismatch"));
    }
    let h = crate::hypot_of(hypot)?;
    let palette: Vec<[u8; 4]> = colors
        .rows()
        .into_iter()
        .map(|r| [r[0], r[1], r[2], r[3]])
        .collect();
    let packed: Vec<Vec<u8>> = py.detach(|| {
        (0..palette.len())
            .into_par_iter()
            .map(|f| {
                if hidden[f] {
                    return Vec::new();
                }
                let rings: Vec<_> = (faces[f]..faces[f + 1])
                    .map(|r| &corners[offsets[r]..offsets[r + 1]])
                    .collect();
                let g = facegeom::face_geometry(&pts, &rings, h, true);
                let n = facegeom::normalized(g.normal, h);
                let mut out = Vec::with_capacity(g.tris.len() * 84);
                for tri in g.tris {
                    for i in tri {
                        let p = pts[i as usize];
                        for x in [p.0, p.1, p.2, n.0, n.1, n.2] {
                            out.extend_from_slice(&x.to_le_bytes());
                        }
                        out.extend_from_slice(&palette[f]);
                    }
                }
                out
            })
            .collect()
    });
    Ok(PyArray1::from_vec(
        py,
        packed.into_iter().flatten().collect(),
    ))
}

fn edge_bytes(pos: &[[f32; 3]], edges: &[[usize; 2]], flags: &[u8]) -> (Vec<u8>, [[f32; 3]; 2]) {
    let mut bounds = [[f32::INFINITY; 3], [f32::NEG_INFINITY; 3]];
    for p in pos {
        for k in 0..3 {
            bounds[0][k] = bounds[0][k].min(p[k]);
            bounds[1][k] = bounds[1][k].max(p[k]);
        }
    }
    if pos.is_empty() {
        bounds = [[0.; 3]; 2];
    }
    let mut bytes = Vec::new();
    for (edge, flag) in edges.iter().zip(flags) {
        if flag & 3 != 0 {
            continue;
        }
        for &i in edge {
            for x in pos[i].into_iter().chain([0., 0., 1.]) {
                bytes.extend_from_slice(&x.to_le_bytes());
            }
            bytes.extend_from_slice(&[0; 4]);
        }
    }
    (bytes, bounds)
}

/// Hard edges use the same packed vertex ABI as faces.
#[pyfunction]
pub fn bake_edges<'py>(
    py: Python<'py>,
    pos: PyReadonlyArray2<'_, f32>,
    edges: PyReadonlyArray2<'_, i64>,
    flags: PyReadonlyArray1<'_, u8>,
) -> PyResult<(Bound<'py, PyArray1<u8>>, [[f32; 3]; 2])> {
    let p = pos.as_array();
    let e = edges.as_array();
    if p.shape()[1] != 3 || e.shape()[1] != 2 || e.shape()[0] != flags.len()? {
        return Err(PyValueError::new_err("edge array shape"));
    }
    let pts: Vec<_> = p.rows().into_iter().map(|r| [r[0], r[1], r[2]]).collect();
    if e.iter().any(|&i| i < 0 || i as usize >= pts.len()) {
        return Err(PyValueError::new_err("edge index"));
    }
    let edges: Vec<_> = e
        .rows()
        .into_iter()
        .map(|r| [r[0] as usize, r[1] as usize])
        .collect();
    let (bytes, bounds) = edge_bytes(&pts, &edges, flags.as_slice()?);
    Ok((PyArray1::from_vec(py, bytes), bounds))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn edge_flags_and_bounds() {
        let (bytes, bounds) =
            edge_bytes(&[[0., -2., 3.], [1., 2., -3.]], &[[0, 1]; 4], &[0, 1, 2, 3]);
        assert_eq!(bytes.len(), 56);
        assert_eq!(bounds, [[0., -2., -3.], [1., 2., 3.]]);
    }
    #[test]
    fn concave_face_and_hole() {
        use facegeom::{face_geometry, Hypot, V3};
        let pts = [
            V3(0., 0., 0.),
            V3(4., 0., 0.),
            V3(4., 4., 0.),
            V3(0., 4., 0.),
            V3(1., 1., 0.),
            V3(1., 3., 0.),
            V3(3., 3., 0.),
            V3(3., 1., 0.),
        ];
        let g = face_geometry(
            &pts,
            &[&[0, 1, 2, 3], &[4, 5, 6, 7]],
            Hypot::LibCxxFma,
            true,
        );
        let area: f32 = g
            .tris
            .iter()
            .map(|t| {
                let a = pts[t[0] as usize];
                let b = pts[t[1] as usize];
                let c = pts[t[2] as usize];
                ((b.0 - a.0) * (c.1 - a.1) - (b.1 - a.1) * (c.0 - a.0)).abs() * 0.5
            })
            .sum();
        assert_eq!(area, 12.);
        let g = face_geometry(&pts, &[&[0, 1, 7, 4, 5, 3]], Hypot::LibCxxFma, true);
        assert_eq!(g.tris.len(), 4);
    }
}
