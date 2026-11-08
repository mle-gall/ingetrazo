//! Batch triangulation across prototypes, then fill disjoint final buffer slices.
//! Only triangle indices/normals survive the count pass; packed vertices are never
//! concatenated. NumPy takes ownership of the final Vec allocations.
use crate::facegeom::{self, Hypot, V3};
use numpy::{PyArray1, PyReadonlyArray1, PyReadonlyArray2};
use pyo3::{exceptions::PyValueError, prelude::*};
use rayon::prelude::*;
use std::collections::HashMap;

struct Prepared {
    triangles: Vec<([u32; 3], V3, [u8; 4])>,
    edges: Vec<[u32; 2]>,
    bounds: [f32; 8],
}

fn prepare(
    p: &[V3],
    c: &[u32],
    sizes: &[i64],
    counts: &[i64],
    colors: &[[u8; 4]],
    hidden: &[bool],
    edges: &[[u32; 2]],
    flags: &[u8],
    h: Hypot,
) -> Prepared {
    let mut bounds = [0.; 8];
    if !p.is_empty() {
        bounds = [
            f32::INFINITY,
            f32::INFINITY,
            f32::INFINITY,
            0.,
            f32::NEG_INFINITY,
            f32::NEG_INFINITY,
            f32::NEG_INFINITY,
            0.,
        ];
        for v in p {
            for (k, x) in [v.0, v.1, v.2].into_iter().enumerate() {
                bounds[k] = bounds[k].min(x);
                bounds[k + 4] = bounds[k + 4].max(x);
            }
        }
    }
    let mut edge_list = Vec::new();
    let mut edge_flags = Vec::new();
    let mut seen = HashMap::new();
    let mut insert = |a: u32, b: u32, flag: u8| {
        if a == b {
            return;
        }
        let key = (a.min(b), a.max(b));
        if let Some(&i) = seen.get(&key) {
            edge_flags[i] |= flag;
        } else {
            seen.insert(key, edge_list.len());
            edge_list.push([a, b]);
            edge_flags.push(flag);
        }
    };
    for (e, f) in edges.iter().zip(flags) {
        insert(e[0], e[1], *f);
    }
    let mut triangles = Vec::new();
    let (mut r, mut k) = (0, 0);
    for (f, &count) in counts.iter().enumerate() {
        let mut rings = Vec::with_capacity(count as usize);
        for _ in 0..count {
            let n = sizes[r] as usize;
            let ring = &c[k..k + n];
            for i in 0..n {
                insert(ring[i], ring[(i + 1) % n], 0);
            }
            rings.push(ring);
            k += n;
            r += 1;
        }
        if !hidden[f] {
            let (tris, normal) = facegeom::resident_geometry(p, &rings, h);
            triangles.extend(tris.into_iter().map(|t| (t, normal, colors[f])));
        }
    }
    let edges = edge_list
        .into_iter()
        .zip(edge_flags)
        .filter_map(|(e, f)| if f & 3 == 0 { Some(e) } else { None })
        .collect();
    Prepared {
        triangles,
        edges,
        bounds,
    }
}

fn fill(p: &[V3], prepared: &Prepared, bytes: &mut [u8], indices: &mut [u32]) {
    let mut cursor = 0;
    let mut vertex = |i: u32, n: V3, color: [u8; 4]| {
        let v = p[i as usize];
        let dst = &mut bytes[cursor * 28..(cursor + 1) * 28];
        for (slot, x) in dst[..24]
            .chunks_exact_mut(4)
            .zip([v.0, v.1, v.2, n.0, n.1, n.2])
        {
            slot.copy_from_slice(&x.to_le_bytes());
        }
        dst[24..].copy_from_slice(&color);
        indices[cursor] = cursor as u32;
        cursor += 1;
    };
    for &(t, n, color) in &prepared.triangles {
        for i in t {
            vertex(i, n, color);
        }
    }
    for &e in &prepared.edges {
        for i in e {
            vertex(i, V3(0., 0., 1.), [0; 4]);
        }
    }
}

#[pyfunction]
pub fn bake_scene<'py>(
    py: Python<'py>,
    pos: PyReadonlyArray2<'_, f32>,
    corners: PyReadonlyArray1<'_, i64>,
    sizes: PyReadonlyArray1<'_, i64>,
    counts: PyReadonlyArray1<'_, i64>,
    colors: PyReadonlyArray2<'_, u8>,
    hidden: PyReadonlyArray1<'_, bool>,
    edges: PyReadonlyArray2<'_, i64>,
    flags: PyReadonlyArray1<'_, u8>,
    offsets: PyReadonlyArray2<'_, i64>,
    attributes: PyReadonlyArray1<'_, i64>,
    hypot: &str,
) -> PyResult<(
    Bound<'py, PyArray1<u8>>,
    Bound<'py, PyArray1<u32>>,
    Bound<'py, PyArray1<f32>>,
    Bound<'py, PyArray1<u32>>,
)> {
    let invalid = || PyValueError::new_err("invalid scene array shape or offsets");
    let p = pos.as_array();
    let e = edges.as_array();
    let col = colors.as_array();
    let off = offsets.as_array();
    let c = corners.as_slice()?;
    let s = sizes.as_slice()?;
    let f = counts.as_slice()?;
    let hidden = hidden.as_slice()?;
    let flags = flags.as_slice()?;
    if p.shape()[1] != 3
        || e.shape()[1] != 2
        || col.shape()[1] != 4
        || attributes.len()? != f.len()
        || hidden.len() != f.len()
        || flags.len() != e.shape()[0]
        || off.shape()[1] != 5
        || off.shape()[0] == 0
    {
        return Err(invalid());
    }
    let ends = [p.shape()[0], c.len(), s.len(), f.len(), e.shape()[0]];
    let offsets: Vec<[usize; 5]> = off
        .rows()
        .into_iter()
        .map(|r| std::array::from_fn(|k| r[k] as usize))
        .collect();
    if offsets[0] != [0; 5] || *offsets.last().unwrap() != ends {
        return Err(invalid());
    }
    for pair in offsets.windows(2) {
        let (a, b) = (pair[0], pair[1]);
        if (0..5).any(|k| a[k] > b[k] || b[k] > ends[k]) {
            return Err(invalid());
        }
        if s[a[2]..b[2]].iter().any(|&v| v < 3)
            || f[a[3]..b[3]].iter().any(|&v| v < 1)
            || s[a[2]..b[2]].iter().sum::<i64>() != (b[1] - a[1]) as i64
            || f[a[3]..b[3]].iter().sum::<i64>() != (b[2] - a[2]) as i64
            || c[a[1]..b[1]]
                .iter()
                .chain(e.slice(numpy::ndarray::s![a[4]..b[4], ..]).iter())
                .any(|&v| v < 0 || v as usize >= b[0] - a[0])
        {
            return Err(invalid());
        }
    }
    let pts: Vec<_> = p.rows().into_iter().map(|r| V3(r[0], r[1], r[2])).collect();
    let corners: Vec<_> = c.iter().map(|&v| v as u32).collect();
    let edges: Vec<_> = e
        .rows()
        .into_iter()
        .map(|r| [r[0] as u32, r[1] as u32])
        .collect();
    let attributes = attributes.as_slice()?;
    if attributes
        .iter()
        .any(|&a| a < 0 || a as usize >= col.shape()[0])
    {
        return Err(invalid());
    }
    let colors: Vec<_> = attributes
        .iter()
        .map(|&a| {
            let r = col.row(a as usize);
            [r[0], r[1], r[2], r[3]]
        })
        .collect();
    let h = crate::hypot_of(hypot)?;
    // Borrowed read-only NumPy slices stay alive throughout this synchronous call.
    let (bytes, indices, bounds, table) = py.detach(|| {
        let prepared: Vec<_> = offsets
            .par_windows(2)
            .map(|pair| {
                let (a, b) = (pair[0], pair[1]);
                let result = prepare(
                    &pts[a[0]..b[0]],
                    &corners[a[1]..b[1]],
                    &s[a[2]..b[2]],
                    &f[a[3]..b[3]],
                    &colors[a[3]..b[3]],
                    &hidden[a[3]..b[3]],
                    &edges[a[4]..b[4]],
                    &flags[a[4]..b[4]],
                    h,
                );
                result
            })
            .collect();
        let total: usize = prepared
            .iter()
            .map(|p| p.triangles.len() * 3 + p.edges.len() * 2)
            .sum();
        let mut bytes = vec![0u8; total * 28];
        let mut indices = vec![0u32; total];
        let mut bounds = Vec::with_capacity(prepared.len() * 8);
        let mut table = Vec::with_capacity(prepared.len() * 3);
        let mut jobs = Vec::new();
        let mut byte_tail = bytes.as_mut_slice();
        let mut index_tail = indices.as_mut_slice();
        let mut first = 0;
        for (i, p) in prepared.iter().enumerate() {
            let nf = p.triangles.len() * 3;
            let n = nf + p.edges.len() * 2;
            bounds.extend_from_slice(&p.bounds);
            table.extend_from_slice(&[first as u32, nf as u32, (n - nf) as u32]);
            let (dst, rest) = byte_tail.split_at_mut(n * 28);
            byte_tail = rest;
            let (idx, rest) = index_tail.split_at_mut(n);
            index_tail = rest;
            jobs.push((i, p, dst, idx));
            first += n;
        }
        jobs.into_par_iter()
            .for_each(|(i, p, dst, idx)| fill(&pts[offsets[i][0]..offsets[i + 1][0]], p, dst, idx));
        (bytes, indices, bounds, table)
    });
    Ok((
        PyArray1::from_vec(py, bytes),
        PyArray1::from_vec(py, indices),
        PyArray1::from_vec(py, bounds),
        PyArray1::from_vec(py, table),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn multiple_mesh_offsets_bounds() {
        let pts = [V3(0., -2., 1.), V3(2., 0., 1.), V3(0., 3., 1.)];
        let p = prepare(
            &pts,
            &[0, 1, 2],
            &[3],
            &[1],
            &[[255; 4]],
            &[false],
            &[],
            &[],
            Hypot::LibCxxFma,
        );
        assert_eq!(p.bounds, [0., -2., 1., 0., 2., 3., 1., 0.]);
        let n = p.triangles.len() * 3 + p.edges.len() * 2;
        let mut bytes = vec![0; n * 28 * 2];
        let mut indices = vec![0; n * 2];
        for (b, i) in bytes.chunks_mut(n * 28).zip(indices.chunks_mut(n)) {
            fill(&pts, &p, b, i);
        }
        assert_eq!(&bytes[..n * 28], &bytes[n * 28..]);
        assert_eq!(
            indices,
            (0..n as u32).cycle().take(n * 2).collect::<Vec<_>>()
        );
    }
}
