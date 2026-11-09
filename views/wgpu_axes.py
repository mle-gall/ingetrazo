"""Small axes uniform, independent of global core.axes state across documents."""
from PySide6.QtGui import QMatrix4x4


def axes_state(scene, camera, source=None):
    frame = scene.drawing_frame
    visible = (scene.show_axes or frame is not None)
    if source is not None:
        visible = visible and source.plano_style is None and source.style_override is None
    return (tuple((frame if frame is not None else QMatrix4x4()).data()),
            max(camera.distance * .008, 1e-4), visible)
