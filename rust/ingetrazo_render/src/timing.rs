//! Diagnostic timestamps preserve the existing render-pass boundaries.
use std::collections::BTreeMap;
pub const NAMES: [&str; 16] = ["background", "culling", "faces", "edge_quads",
    "profile_top", "ao_inputs", "ao_kernel", "ao_blur_x", "ao_blur_y",
    "ao_upsample_composite", "antialias", "antialias_edges", "xray_accumulation", "xray_composite", "overlay", "frame"];
pub const COUNT: u32 = 4 + NAMES.len() as u32 * 2;
pub const BYTES: usize = COUNT as usize * 8;
pub fn index(name: &str) -> u32 {
    4 + 2 * NAMES.iter().position(|n| *n == name).expect("known timing") as u32
}
pub fn writes<'a>(q: Option<&'a wgpu::QuerySet>, name: &str) -> Option<wgpu::RenderPassTimestampWrites<'a>> {
    q.map(|q| wgpu::RenderPassTimestampWrites { query_set: q,
        beginning_of_pass_write_index: Some(index(name)), end_of_pass_write_index: Some(index(name)+1) })
}
pub fn decode(bytes: &[u8], period: f64) -> BTreeMap<String, f64> {
    NAMES.iter().map(|name| {
        let k = index(name) as usize * 8;
        let start = u64::from_le_bytes(bytes[k..k+8].try_into().unwrap());
        let end = u64::from_le_bytes(bytes[k+8..k+16].try_into().unwrap());
        (name.to_string(), end.saturating_sub(start) as f64 * period / 1e6)
    }).collect()
}
#[cfg(test)]
mod tests {
    #[test]
    fn table_has_unique_pairs_and_millisecond_units() {
        let mut bytes = vec![0; super::BYTES];
        for name in super::NAMES {
            let k = super::index(name) as usize * 8;
            bytes[k+8..k+16].copy_from_slice(&1_000_000u64.to_le_bytes());
        }
        let table = super::decode(&bytes, 1.);
        assert_eq!(table.len(), super::NAMES.len());
        assert!(table.values().all(|v| *v == 1.));
    }
}
