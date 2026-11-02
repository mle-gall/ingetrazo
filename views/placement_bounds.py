# SPDX-License-Identifier: GPL-3.0-or-later
"""Conservative affine placement bounds, in batches without Qt point objects."""
import numpy as np


def affine_bounds(boxes, matrices):
    """Map local AABBs by column-major matrices; return float32 world AABBs.

    Double precision accumulation plus outward float32 rounding avoids
    clipping vertices at the boundary when Qt/the GPU uses fused arithmetic.
    Perspective matrices are deliberately left to the scalar Qt path.
    """
    boxes = np.asarray(boxes, dtype=np.float32).astype(np.float64)
    m = np.asarray(matrices, dtype=np.float32).reshape(-1, 4, 4).transpose(0, 2, 1)
    linear = m[:, :3, :3].astype(np.float64)
    a = linear * boxes[:, None, 0, :]
    b = linear * boxes[:, None, 1, :]
    lo = np.minimum(a, b).sum(axis=2) + m[:, :3, 3]
    hi = np.maximum(a, b).sum(axis=2) + m[:, :3, 3]
    # Exact axis-aligned maps use Qt's same float32 multiply/add order.
    diagonal = ((np.count_nonzero(linear, axis=2) <= 1).all(axis=1)
                & ((linear == 0) | (np.abs(linear) == 1)).all(axis=(1, 2)))
    low, high = lo.astype(np.float32), hi.astype(np.float32)
    general = ~diagonal
    if general.any():
        error = (np.maximum(np.abs(a), np.abs(b)).sum(axis=2)
                 + np.abs(m[:, :3, 3])) * (4 * np.finfo(np.float32).eps)
        low[general] = np.nextafter((lo-error)[general].astype(np.float32), -np.inf)
        high[general] = np.nextafter((hi+error)[general].astype(np.float32), np.inf)
    return low, high
