// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 IngeTrazo contributors.
//! Corner-angle-weighted soft-edge fans without Python mesh objects.
use std::collections::HashMap;
use crate::facegeom::{self, Hypot, V3};

fn root(parent: &mut [usize], mut i: usize) -> usize {
    while parent[i] != i {
        parent[i] = parent[parent[i]];
        i = parent[i];
    }
    i
}

pub fn corners(pos: &[V3], normals: &[V3], corners: &[i64], sizes: &[i64],
               counts: &[i64], edges: &[[i64; 2]], soft: &[bool],
               starts: &[i64], adjacent: &[i64], h: Hypot)
    -> HashMap<(usize, usize), V3> {
    let mut incident = vec![Vec::new(); pos.len()];
    let mut curved = vec![false; normals.len()];
    for (e, ends) in edges.iter().enumerate() {
        if soft[e] && starts[e+1] - starts[e] > 1 {
            for &v in ends { incident[v as usize].push(e); }
            for &f in &adjacent[starts[e] as usize..starts[e+1] as usize] {
                curved[f as usize] = true;
            }
        }
    }
    let mut angles = HashMap::new();
    let (mut r, mut offset) = (0, 0);
    for (f, &count) in counts.iter().enumerate() {
        for _ in 0..count {
            let n = sizes[r] as usize;
            if curved[f] && n > 0 {
                let ring = &corners[offset..offset+n];
                for i in 0..n {
                    let v = ring[i] as usize;
                    let a = pos[ring[(i+n-1)%n] as usize].sub(pos[v]);
                    let b = pos[ring[(i+1)%n] as usize].sub(pos[v]);
                    let cross = a.cross(b, h);
                    let mut angle = (facegeom::length(cross, h) as f64)
                        .atan2(a.dot(b, h) as f64);
                    if cross.dot(normals[f], h) > 0.0 {
                        angle = 2.0 * std::f64::consts::PI - angle;
                    }
                    angles.insert((v, f), angle);
                }
            }
            offset += n;
            r += 1;
        }
    }
    let mut output = HashMap::new();
    for (v, es) in incident.iter().enumerate() {
        if es.is_empty() { continue; }
        let mut ids = HashMap::new();
        let mut members = Vec::new();
        let mut parent = Vec::new();
        for &e in es {
            let fs = &adjacent[starts[e] as usize..starts[e+1] as usize];
            let mut first = None;
            for &f in fs {
                let f = f as usize;
                let idx = *ids.entry(f).or_insert_with(|| {
                    let i = members.len(); members.push(f); parent.push(i); i
                });
                let other = root(&mut parent, idx);
                if let Some(r) = first { parent[other] = r; }
                else { first = Some(other); }
            }
        }
        let mut groups: HashMap<usize, Vec<usize>> = HashMap::new();
        for i in 0..members.len() {
            groups.entry(root(&mut parent, i)).or_default().push(members[i]);
        }
        for fs in groups.values() {
            if fs.len() < 2 { continue; }
            let reference = normals[fs[0]];
            let mut sum = [0.0f64; 3];
            for &f in fs {
                let n = normals[f];
                let weight = *angles.get(&(v, f)).unwrap_or(&0.0);
                let (x, y, z) = (n.0 as f64 * weight, n.1 as f64 * weight,
                                  n.2 as f64 * weight);
                let sign = if x * reference.0 as f64 + y * reference.1 as f64
                              + z * reference.2 as f64 >= 0.0 { 1.0 } else { -1.0 };
                sum[0] += sign*x; sum[1] += sign*y; sum[2] += sign*z;
            }
            let len = (sum[0]*sum[0] + sum[1]*sum[1] + sum[2]*sum[2]).sqrt();
            if len < 1e-9 { continue; }
            let (x, y, z) = (sum[0]/len, sum[1]/len, sum[2]/len);
            for &f in fs {
                let n = normals[f];
                let sign = if n.0 as f64*x + n.1 as f64*y + n.2 as f64*z >= 0.0
                           { 1.0 } else { -1.0 };
                output.insert((v, f), V3((sign*x) as f32, (sign*y) as f32, (sign*z) as f32));
            }
        }
    }
    output
}
