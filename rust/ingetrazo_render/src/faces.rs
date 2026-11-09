//! Drop the source edge-only vertex/index tails without changing corner order.
//! Per-prototype vertex translation is also applied to sparse material headers.
pub fn compact(vertices: &[u8], indices: &[u8], commands: &mut [u8], prototypes: usize)
    -> (Vec<u8>, Vec<u8>, Vec<i64>) {
    let mut v = Vec::new();
    let mut ix = Vec::new();
    let mut shifts = Vec::new();
    for row in commands.chunks_exact_mut(20).take(prototypes) {
        let mut c: crate::Command = bytemuck::pod_read_unaligned(row);
        let source = &indices[c.first as usize * 4..(c.first + c.count) as usize * 4];
        let mut lo = usize::MAX;
        let mut hi = 0;
        for index in source.chunks_exact(4) {
            let j = (i64::from(u32::from_le_bytes(index.try_into().unwrap())) + i64::from(c.base)) as usize;
            lo = lo.min(j);
            hi = hi.max(j);
        }
        let shift = if source.is_empty() { 0 } else { v.len() as i64 / 28 - lo as i64 };
        if !source.is_empty() { v.extend_from_slice(&vertices[lo*28..(hi+1)*28]); }
        c.base = (i64::from(c.base) + shift) as i32;
        c.first = (ix.len() / 4) as u32;
        ix.extend_from_slice(source);
        shifts.push(shift);
        row.copy_from_slice(bytemuck::bytes_of(&c));
    }
    if v.is_empty() { v.resize(28, 0); }
    if ix.is_empty() { ix.resize(4, 0); }
    (v, ix, shifts)
}

#[cfg(test)]
mod tests {
    #[test]
    fn drops_edge_tails_and_accounts_only_resident_bytes() {
        let vertices = vec![0u8; 12*28];
        let indices = [0u32,1,2,3,4,5,0,1,2,3,4,5];
        let mut commands = bytemuck::cast_slice(&[
            crate::Command { count:3, instances:0, first:0, base:0, start:0 },
            crate::Command { count:3, instances:0, first:6, base:6, start:1 },
        ]).to_vec();
        let (v, ix, shifts) = super::compact(&vertices, bytemuck::cast_slice(&indices), &mut commands, 2);
        assert_eq!(shifts, [0, -3]);
        assert_eq!(v.len() + ix.len(), 6*28 + 6*4);
        let second: crate::Command = bytemuck::pod_read_unaligned(&commands[20..]);
        assert_eq!((second.first,second.base), (3,3));
    }
}
