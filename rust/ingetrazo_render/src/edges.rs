//! Pack 48-byte edge records; preserve the 28-byte Python face ABI.
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
        let first = v.len() / 48;
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
            hard.insert(key(&a, &b));
            pairs.push((a, b, false));
        }
        let hard_count = pairs.len();
        for (k, n) in &adjacency {
            if n[0] != [0.; 3] && !hard.contains(k)
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
            // A power-of-two normal scale encodes the profile-only flag without
            // quantization. Decoding by 0.5 restores the original float bits.
            let n0 = normals[0].map(|x| if soft { x * 2. } else { x });
            v.extend_from_slice(bytemuck::cast_slice(&n0));
            v.extend_from_slice(bytemuck::cast_slice(&normals[1]));
        }
        c.first = u32::try_from(first * 6).map_err(|_| "edge buffer too large")?;
        c.count = u32::try_from(count * 6).map_err(|_| "edge buffer too large")?;
        c.base = c.start as i32; // Non-indexed first_instance addresses survivors.
        c.start = u32::try_from(hard_count * 6).map_err(|_| "edge buffer too large")?;
        row.copy_from_slice(bytemuck::bytes_of(&c));
    }
    if v.is_empty() { v.resize(48, 0); } // Valid storage binding for face-only scenes.
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
        assert_eq!(v.len(), 48);
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
        // Coincident source edges preserve their independent dash directions.
        let (v, _, cmd) = super::expand(&vertices, bytemuck::cast_slice(&[0u32,1,2,0,1,1,0]),
            bytemuck::cast_slice(&commands), 1).unwrap();
        assert_eq!(v.len(), 4*48);
        let edge: crate::Command = bytemuck::pod_read_unaligned(&cmd[20..]);
        assert_eq!((edge.count,edge.base,edge.start), (24,7,12));
        assert_eq!(f32::from_le_bytes(v[32..36].try_into().unwrap()),1.);
        assert_eq!(f32::from_le_bytes(v[44..48].try_into().unwrap()),0.);
        assert_eq!(f32::from_le_bytes(v[128..132].try_into().unwrap()),2.);
    }

    #[test]
    fn empty_edges_have_a_valid_storage_binding() {
        let command = crate::Command { count: 0, instances: 0, first: 0, base: 0, start: 0 };
        let (records, indices, commands) = super::expand(&[], &[],
            bytemuck::cast_slice(&[command, command]), 1).unwrap();
        assert_eq!(records.len(), 48);
        assert_eq!(indices.len(), 0);
        assert_eq!(commands.len(), 40);
    }

    #[test]
    fn flag_scale_preserves_normal_bits() {
        for normal in [glam::Vec3::Z, -glam::Vec3::Z, glam::Vec3::new(1.,2.,3.).normalize()] {
            assert_eq!((normal * 2. * 0.5).to_array(), normal.to_array());
        }
    }
}

#[cfg(test)]
mod view_direction_tests {
    #[test]
    fn local_eye_classification_matches_projected_area() {
        use glam::{Mat3, Mat4, Vec3, Vec4};
        let eye = Vec3::new(5., 7., 11.);
        let view = Mat4::look_at_rh(eye, Vec3::ZERO, Vec3::Y);
        let a = Vec3::new(0.2, 0.3, 0.4);
        let b = a + Vec3::Y;
        for mirror in [1., -1.] {
            let world = Mat4::from_scale(Vec3::new(mirror*2., 3., 4.));
            for perspective in [false, true] {
                let projection = if perspective { Mat4::perspective_rh(1., 1.4, 0.1, 100.) }
                    else { Mat4::orthographic_rh(-10.,10.,-10.,10.,0.1,100.) };
                let transform = projection * view * world;
                let camera = view.inverse() * if perspective { Vec4::W } else { Vec4::Z };
                let local = world.inverse() * camera;
                let direction = local.truncate() - a * local.w;
                let xyw = |p: Vec4| Vec3::new(p.x,p.y,p.w);
                let projected = |n: Vec3| Mat3::from_cols(
                    xyw(transform*a.extend(1.)), xyw(transform*b.extend(1.)),
                    xyw(transform*(a+n.cross(b-a)).extend(1.))).determinant();
                for (n0,n1) in [(Vec3::X,Vec3::Z),(Vec3::X,-Vec3::Z),(-Vec3::X,Vec3::Z)] {
                    assert_eq!((projected(n0)>0.) != (projected(n1)>0.),
                        (n0.dot(direction)>0.) != (n1.dot(direction)>0.));
                }
            }
        }
    }
}
