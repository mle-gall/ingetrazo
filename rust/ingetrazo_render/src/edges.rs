//! Expand resident line commands once at upload; the GPU supplies pixel width.
//! Keeping the public 28-byte ABI avoids forcing scene producers to duplicate
//! topology. Edge vertices repurpose normal for the opposite endpoint and red
//! for the side sign. Face vertices are unchanged.
pub fn expand(vertices: &[u8], indices: &[u8], commands: &[u8], prototypes: usize)
    -> Result<(Vec<u8>, Vec<u8>, Vec<u8>), &'static str>
{
    let mut v = vertices.to_vec();
    let mut ix = indices.to_vec();
    let mut cmd = commands.to_vec();
    for row in cmd.chunks_exact_mut(20).skip(prototypes) {
        let mut c: crate::Command = bytemuck::pod_read_unaligned(row);
        if c.count % 2 != 0 {
            return Err("edge command must contain endpoint pairs");
        }
        let first = ix.len() / 4;
        for pair in indices[c.first as usize * 4..(c.first + c.count) as usize * 4].chunks_exact(8) {
            let endpoint = |offset| {
                let index = u32::from_le_bytes(pair[offset..offset+4].try_into().unwrap());
                let start = (i64::from(index) + i64::from(c.base)) as usize * 28;
                &vertices[start..start+12]
            };
            let a = endpoint(0);
            let b = endpoint(4);
            for (end, side) in [(false, 0), (false, 255), (true, 255),
                                (false, 0), (true, 255), (true, 0)] {
                let index = u32::try_from(v.len()/28).map_err(|_| "edge buffer too large")?;
                ix.extend_from_slice(&index.to_le_bytes());
                v.extend_from_slice(if end { b } else { a });
                v.extend_from_slice(if end { a } else { b });
                v.extend_from_slice(&[side, u8::from(end)*255, 0, 0]);
            }
        }
        c.first = u32::try_from(first).map_err(|_| "edge buffer too large")?;
        c.count = c.count.checked_mul(3).ok_or("edge buffer too large")?;
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
        assert_eq!(v.len(), 8*28);
        assert_eq!(ix.len(), 8*4);
        let edge: crate::Command = bytemuck::pod_read_unaligned(&cmd[20..]);
        assert_eq!((edge.first, edge.count, edge.base), (2, 6, 0));
        assert_eq!(&v[56..68], &vertices[..12]);
        assert_eq!(&v[68..80], &vertices[28..40]);
        assert_eq!(v[80], 0);
        assert_eq!(v[108], 255);
    }
}
