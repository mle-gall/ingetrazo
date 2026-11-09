//! Expand resident line commands once at upload; the GPU supplies pixel width.
//! Keeping the public 28-byte ABI avoids forcing scene producers to duplicate
//! topology. The resident 52-byte layout appends two adjacency normals to each
//! vertex. Edge vertices repurpose normal for the opposite endpoint and red
//! for the side sign; blue distinguishes synthesized profile candidates.
//! Face positions, normals, colors and command ranges remain unchanged.
pub fn expand(vertices: &[u8], indices: &[u8], commands: &[u8], prototypes: usize)
    -> Result<(Vec<u8>, Vec<u8>, Vec<u8>), &'static str>
{
    let mut v = Vec::new();
    for vertex in vertices.chunks_exact(28) {
        v.extend_from_slice(vertex);
        v.extend_from_slice(&[0; 24]);
    }
    let mut ix = indices.to_vec();
    let mut cmd = commands.to_vec();
    for (prototype, row) in cmd.chunks_exact_mut(20).skip(prototypes).enumerate() {
        let face: crate::Command = bytemuck::pod_read_unaligned(&commands[prototype*20..prototype*20+20]);
        let adjacency = adjacency(vertices, indices, face);
        let mut c: crate::Command = bytemuck::pod_read_unaligned(row);
        if c.count % 2 != 0 {
            return Err("edge command must contain endpoint pairs");
        }
        let first = ix.len() / 4;
        let mut pairs = Vec::new();
        let mut hard = std::collections::HashSet::new();
        for pair in indices[c.first as usize * 4..(c.first + c.count) as usize * 4].chunks_exact(8) {
            let endpoint = |offset| {
                let index = u32::from_le_bytes(pair[offset..offset+4].try_into().unwrap());
                let start = (i64::from(index) + i64::from(c.base)) as usize * 28;
                vertices[start..start+12].to_vec()
            };
            let a = endpoint(0); let b = endpoint(4);
            hard.insert(key(&a,&b));
            pairs.push((a,b,false));
        }
        for (k,n) in &adjacency {
            if !hard.contains(k) && (n[1] == [0.;3] || glam::Vec3::from(n[0]).dot(glam::Vec3::from(n[1])) < 0.99999) {
                pairs.push((k[..12].to_vec(),k[12..].to_vec(),true));
            }
        }
        let count = pairs.len();
        for (a,b,soft) in pairs {
            let a = a.as_slice(); let b = b.as_slice();
            for (end, side) in [(false, 0), (false, 255), (true, 255),
                                (false, 0), (true, 255), (true, 0)] {
                let index = u32::try_from(v.len()/52).map_err(|_| "edge buffer too large")?;
                ix.extend_from_slice(&index.to_le_bytes());
                v.extend_from_slice(if end { b } else { a });
                v.extend_from_slice(if end { a } else { b });
                v.extend_from_slice(&[side, u8::from(end)*255, u8::from(soft)*255, 0]);
                let normals = adjacency.get(&key(a,b)).copied().unwrap_or([[0.;3];2]);
                v.extend_from_slice(bytemuck::cast_slice(&normals));
            }
        }
        c.first = u32::try_from(first).map_err(|_| "edge buffer too large")?;
        c.count = u32::try_from(count*6).map_err(|_| "edge buffer too large")?;
        c.base = 0;
        row.copy_from_slice(bytemuck::bytes_of(&c));
    }
    Ok((v, ix, cmd))
}

#[cfg(test)]
mod tests {
    #[test]
    fn expands_endpoint_pairs_without_changing_face_commands() {
        let mut vertices = vec![0u8; 56];
        vertices[28..32].copy_from_slice(&2f32.to_le_bytes());
        let indices = bytemuck::cast_slice(&[0u32, 1]).to_vec();
        let commands = [crate::Command { count: 0, instances: 0, first: 0, base: 0, start: 0 },
            crate::Command { count: 2, instances: 0, first: 0, base: 0, start: 0 }];
        let (v, ix, cmd) = super::expand(&vertices, &indices, bytemuck::cast_slice(&commands), 1).unwrap();
        assert_eq!(&cmd[..20], bytemuck::bytes_of(&commands[0]));
        assert_eq!(v.len(), 8*52);
        assert_eq!(ix.len(), 8*4);
        let edge: crate::Command = bytemuck::pod_read_unaligned(&cmd[20..]);
        assert_eq!((edge.first, edge.count, edge.base), (2, 6, 0));
        assert_eq!(&v[104..116], &vertices[..12]);
        assert_eq!(&v[116..128], &vertices[28..40]);
        assert_eq!(v[128], 0);
        assert_eq!(v[180], 255);
    }
}

// Position keys join duplicated triangle vertices without changing the upload ABI.
fn key(a: &[u8], b: &[u8]) -> [u8; 24] {
    let mut k = [0; 24];
    let (a,b) = if a < b { (a,b) } else { (b,a) };
    k[..12].copy_from_slice(a); k[12..].copy_from_slice(b); k
}
fn adjacency(vertices: &[u8], indices: &[u8], c: crate::Command)
    -> std::collections::HashMap<[u8;24], [[f32;3];2]> {
    let mut result = std::collections::HashMap::new();
    for tri in indices[c.first as usize*4..(c.first+c.count) as usize*4].chunks_exact(12) {
        let points: Vec<_> = tri.chunks_exact(4).map(|i| {
            let index = u32::from_le_bytes(i.try_into().unwrap());
            let offset = (i64::from(index)+i64::from(c.base)) as usize*28;
            &vertices[offset..offset+12]
        }).collect();
        let point = |i: usize| glam::Vec3::from_array(bytemuck::pod_read_unaligned::<[f32;3]>(points[i]));
        let normal = (point(1)-point(0)).cross(point(2)-point(0)).normalize_or_zero().to_array();
        for (a,b) in [(0,1),(1,2),(2,0)] {
            let entry = result.entry(key(points[a],points[b])).or_insert([[0.;3];2]);
            if entry[0] == [0.;3] { entry[0] = normal; } else { entry[1] = normal; }
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
    fn boundary_and_opposed_faces_are_profiles() {
        assert!(super::silhouette(1.,1.,true));
        assert!(super::silhouette(-1.,1.,false));
        assert!(super::silhouette(1.,-1.,false));
        assert!(!super::silhouette(1.,1.,false));
        assert!(!super::silhouette(-1.,-1.,false));
    }
}
