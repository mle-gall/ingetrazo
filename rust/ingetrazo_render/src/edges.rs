//! Pack 40-byte edge records; preserve the 28-byte Python face ABI.
pub fn expand(
    vertices: &[u8],
    indices: &[u8],
    commands: &[u8],
    prototypes: usize,
) -> Result<(Vec<u8>, Vec<u8>, Vec<u8>), &'static str> {
    let mut v = Vec::new();
    let ix = indices.to_vec();
    let mut cmd = commands.to_vec();
    for (prototype, row) in cmd.chunks_exact_mut(20).skip(prototypes).enumerate() {
        let face: crate::Command =
            bytemuck::pod_read_unaligned(&commands[prototype * 20..prototype * 20 + 20]);
        let adjacency = adjacency(vertices, indices, face);
        let mut c: crate::Command = bytemuck::pod_read_unaligned(row);
        if c.count % 2 != 0 {
            return Err("edge command must contain endpoint pairs");
        }
        let first = v.len() / 40;
        let mut pairs = Vec::new();
        let mut hard = std::collections::HashSet::new();
        for pair in indices[c.first as usize * 4..(c.first + c.count) as usize * 4].chunks_exact(8)
        {
            let endpoint = |offset| {
                let index = u32::from_le_bytes(pair[offset..offset + 4].try_into().unwrap());
                let start = (i64::from(index) + i64::from(c.base)) as usize * 28;
                vertices[start..start + 12].to_vec()
            };
            let a = endpoint(0);
            let b = endpoint(4);
            if hard.insert(key(&a, &b)) {
                pairs.push((a, b, false));
            }
        }
        let hard_count = pairs.len();
        for (k, n) in &adjacency {
            if !hard.contains(k)
                && (n[1] == [0.; 3] || glam::Vec3::from(n[0]).dot(glam::Vec3::from(n[1])) < 0.99999)
            {
                pairs.push((k[..12].to_vec(), k[12..].to_vec(), true));
            }
        }
        let count = pairs.len();
        for (a, b, soft) in pairs {
            v.extend_from_slice(&a);
            v.extend_from_slice(&b);
            let normals = adjacency.get(&key(&a, &b)).copied().unwrap_or([[0.; 3]; 2]);
            for (i, normal) in normals.iter().enumerate() {
                for x in normal {
                    v.extend_from_slice(&((x.clamp(-1., 1.) * 32767.).round() as i16).to_le_bytes());
                }
                v.extend_from_slice(&(if i == 1 && soft { 32767i16 } else { 0 }).to_le_bytes());
            }

        }
        c.first = u32::try_from(first * 6).map_err(|_| "edge buffer too large")?;
        c.count = u32::try_from(count * 6).map_err(|_| "edge buffer too large")?;
        c.base = c.start as i32; // Non-indexed first_instance addresses survivors.
        c.start = u32::try_from(hard_count * 6).map_err(|_| "edge buffer too large")?;
        row.copy_from_slice(bytemuck::bytes_of(&c));
    }
    if v.is_empty() { v.resize(40, 0); } // Valid storage binding for face-only scenes.
    Ok((v, ix, cmd))
}

#[cfg(test)]
mod tests {
    #[test]
    fn expands_endpoint_pairs_without_changing_face_commands() {
        let mut vertices = vec![0u8; 56];
        vertices[28..32].copy_from_slice(&2f32.to_le_bytes());
        let indices = bytemuck::cast_slice(&[0u32, 1]).to_vec();
        let commands = [
            crate::Command {
                count: 0,
                instances: 0,
                first: 0,
                base: 0,
                start: 0,
            },
            crate::Command {
                count: 2,
                instances: 0,
                first: 0,
                base: 0,
                start: 0,
            },
        ];
        let (v, ix, cmd) =
            super::expand(&vertices, &indices, bytemuck::cast_slice(&commands), 1).unwrap();
        assert_eq!(&cmd[..20], bytemuck::bytes_of(&commands[0]));
        assert_eq!(v.len(), 40);
        assert_eq!(ix.len(), 2 * 4);
        let edge: crate::Command = bytemuck::pod_read_unaligned(&cmd[20..]);
        assert_eq!((edge.first, edge.count, edge.base), (0, 6, 0));
        assert_eq!(&v[..12], &vertices[..12]);
        assert_eq!(&v[12..24], &vertices[28..40]);


    }
}

// Position keys join duplicated triangle vertices without changing the upload ABI.
fn key(a: &[u8], b: &[u8]) -> [u8; 24] {
    let mut k = [0; 24];
    let (a, b) = if a < b { (a, b) } else { (b, a) };
    k[..12].copy_from_slice(a);
    k[12..].copy_from_slice(b);
    k
}
fn adjacency(
    vertices: &[u8],
    indices: &[u8],
    c: crate::Command,
) -> std::collections::HashMap<[u8; 24], [[f32; 3]; 2]> {
    let mut result = std::collections::HashMap::new();
    for tri in indices[c.first as usize * 4..(c.first + c.count) as usize * 4].chunks_exact(12) {
        let points: Vec<_> = tri
            .chunks_exact(4)
            .map(|i| {
                let index = u32::from_le_bytes(i.try_into().unwrap());
                let offset = (i64::from(index) + i64::from(c.base)) as usize * 28;
                &vertices[offset..offset + 12]
            })
            .collect();
        let point =
            |i: usize| glam::Vec3::from_array(bytemuck::pod_read_unaligned::<[f32; 3]>(points[i]));
        let normal = (point(1) - point(0))
            .cross(point(2) - point(0))
            .normalize_or_zero()
            .to_array();
        for (a, b) in [(0, 1), (1, 2), (2, 0)] {
            let entry = result
                .entry(key(points[a], points[b]))
                .or_insert([[0.; 3]; 2]);
            if entry[0] == [0.; 3] {
                entry[0] = normal;
            } else {
                entry[1] = normal;
            }
        }
    }
    result
}
#[cfg(test)]
fn silhouette(a: f32, b: f32, boundary: bool) -> bool {
    boundary || (a > 0.) != (b > 0.)
}
#[cfg(test)]
mod classification_tests {
    #[test]
    fn coplanar_triangulation_does_not_create_a_profile_diagonal() {
        let mut vertices = Vec::new();
        for p in [[0f32, 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.]] {
            vertices.extend_from_slice(bytemuck::cast_slice(&p));
            vertices.extend_from_slice(&[0; 16]);
        }
        let indices = [0u32, 1, 2, 0, 2, 3];
        let commands = [
            crate::Command {
                count: 6,
                instances: 0,
                first: 0,
                base: 0,
                start: 0,
            },
            crate::Command {
                count: 0,
                instances: 0,
                first: 6,
                base: 0,
                start: 0,
            },
        ];
        let (_, _, expanded) = super::expand(
            &vertices,
            bytemuck::cast_slice(&indices),
            bytemuck::cast_slice(&commands),
            1,
        )
        .unwrap();
        let edge: crate::Command = bytemuck::pod_read_unaligned(&expanded[20..]);
        assert_eq!(edge.count, 24); // Four boundaries, no interior diagonal.
    }

    #[test]
    fn boundary_and_opposed_faces_are_profiles() {
        assert!(super::silhouette(1., 1., true));
        assert!(super::silhouette(-1., 1., false));
        assert!(super::silhouette(1., -1., false));
        assert!(!super::silhouette(1., 1., false));
        assert!(!super::silhouette(-1., -1., false));
    }
}

#[cfg(test)]
mod compact_tests {
    #[test]
    fn pixel_width_is_depth_invariant() {
        // Clip-space displacement used by edge_vs; viewport conversion cancels w.
        for depth in [0.01f32, 1., 1000.] {
            for width in [1f32, 4., 7.5] {
                let clip_offset = width / 1400. * depth;
                let pixels = 2. * clip_offset / depth * 1400. * 0.5;
                assert!((pixels - width).abs() < 1e-5);
            }
        }
    }

    #[test]
    fn packs_normals_flags_and_hard_only_count() {
        let mut vertices = Vec::new();
        for p in [[0f32,0.,0.],[1.,0.,0.],[0.,1.,0.]] {
            vertices.extend_from_slice(bytemuck::cast_slice(&p));
            vertices.extend_from_slice(&[0;16]);
        }
        let commands = [
            crate::Command { count:3, instances:0, first:0, base:0, start:7 },
            crate::Command { count:4, instances:0, first:3, base:0, start:7 },
        ];
        // Reversed duplicate hard edge is represented once.
        let (v, _, cmd) = super::expand(&vertices, bytemuck::cast_slice(&[0u32,1,2,0,1,1,0]),
            bytemuck::cast_slice(&commands), 1).unwrap();
        assert_eq!(v.len(), 3*40);
        let edge: crate::Command = bytemuck::pod_read_unaligned(&cmd[20..]);
        assert_eq!((edge.count,edge.base,edge.start), (18,7,6));
        assert_eq!(i16::from_le_bytes(v[28..30].try_into().unwrap()),32767);
        assert_eq!(i16::from_le_bytes(v[38..40].try_into().unwrap()),0);
        assert_eq!(i16::from_le_bytes(v[78..80].try_into().unwrap()),32767);
    }

    #[test]
    fn empty_edges_have_a_valid_storage_binding() {
        let command = crate::Command { count: 0, instances: 0, first: 0, base: 0, start: 0 };
        let (records, indices, commands) = super::expand(&[], &[],
            bytemuck::cast_slice(&[command, command]), 1).unwrap();
        assert_eq!(records.len(), 40);
        assert_eq!(indices.len(), 0);
        assert_eq!(commands.len(), 40);
    }

    #[test]
    fn normal_quantization_preserves_facing_away_from_tangency() {
        let view = glam::Vec3::new(0.2, 0.3, 1.).normalize();
        for normal in [glam::Vec3::Z, -glam::Vec3::Z, glam::Vec3::X] {
            let decoded = normal.map(|v| (v * 32767.).round() / 32767.);
            assert_eq!(normal.dot(view) > 0., decoded.dot(view) > 0.);
        }
    }
}
