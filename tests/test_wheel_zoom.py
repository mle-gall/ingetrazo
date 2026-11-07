"""Natural scrolling normalization is limited to Mac trackpads."""
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QInputDevice, QPointingDevice, QWheelEvent
from views import wheel_zoom


@pytest.mark.parametrize('platform', ['darwin', 'linux', 'win32'])
@pytest.mark.parametrize('touchpad', [False, True])
@pytest.mark.parametrize('natural', [False, True])
@pytest.mark.parametrize('delta', [-120, 120, 0, 30])
@pytest.mark.parametrize('override', [False, True])
def test_zoom_direction(monkeypatch, platform, touchpad, natural, delta, override):
    monkeypatch.setattr(wheel_zoom.sys, 'platform', platform)
    device = QPointingDevice(
        'test', 1,
        QInputDevice.DeviceType.TouchPad if touchpad else QInputDevice.DeviceType.Mouse,
        QPointingDevice.PointerType.Finger if touchpad else QPointingDevice.PointerType.Generic,
        QInputDevice.Capability.Position, 2, 3)
    event = QWheelEvent(QPointF(100, 100), QPointF(100, 100),
                        QPoint(0, delta) if touchpad else QPoint(), QPoint(0, delta),
                        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, natural,
                        Qt.MouseEventNotSynthesized, device)
    expected = delta / 120
    if platform == 'darwin' and touchpad and natural:
        expected *= -1
    if override:
        expected *= -1
    assert wheel_zoom.zoom_steps(event, override) == expected
