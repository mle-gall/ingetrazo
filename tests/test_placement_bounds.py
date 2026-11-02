import numpy as np
from PySide6.QtGui import QMatrix4x4, QVector3D
from views.placement_bounds import affine_bounds


def test_batch_bounds_contain_qt_corners_for_rotations_scales_and_mirrors():
    rng = np.random.default_rng(13)
    matrices, boxes = [], []
    for i in range(300):
        m = QMatrix4x4()
        m.translate(*rng.uniform(-1e4, 1e4, 3).tolist())
        m.rotate(float(rng.uniform(-180, 180)), QVector3D(*rng.normal(size=3).tolist()))
        m.scale(*rng.uniform(-3, 3, 3).tolist())
        matrices.append(m)
        a = rng.uniform(-100, 100, 3)
        boxes.append([a, a+rng.uniform(.01, 100, 3)])
    lo, hi = affine_bounds(boxes, [m.data() for m in matrices])
    for i, (box, m) in enumerate(zip(boxes, matrices)):
        points = np.asarray([m.map(QVector3D(x,y,z)).toTuple()
                             for x in (box[0][0], box[1][0])
                             for y in (box[0][1], box[1][1])
                             for z in (box[0][2], box[1][2])])
        assert (lo[i] <= points.min(axis=0)).all()
        assert (hi[i] >= points.max(axis=0)).all()
        # Bounds remain tight, despite outward rounding.
        np.testing.assert_allclose(lo[i], points.min(axis=0), atol=.02, rtol=1e-5)
        np.testing.assert_allclose(hi[i], points.max(axis=0), atol=.02, rtol=1e-5)
