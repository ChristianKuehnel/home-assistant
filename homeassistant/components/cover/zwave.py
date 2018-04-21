"""
Support for Z-Wave cover components.

For more details about this platform, please refer to the documentation
https://home-assistant.io/components/cover.zwave/
"""
# Because we do not compile openzwave on CI
# pylint: disable=import-error
import logging
from homeassistant.components.cover import (
    DOMAIN, SUPPORT_OPEN, SUPPORT_CLOSE, ATTR_POSITION)
from homeassistant.components.zwave import ZWaveDeviceEntity
from homeassistant.components import zwave
from homeassistant.components.zwave import async_setup_platform  # noqa # pylint: disable=unused-import
from homeassistant.components.zwave import workaround
from homeassistant.components.cover import CoverDevice

_LOGGER = logging.getLogger(__name__)

SUPPORT_GARAGE = SUPPORT_OPEN | SUPPORT_CLOSE


def _to_hex_str(id_in_bytes):
    """convert a two byte value to a hex string.

     Example: 0x1234 --> '0x1234' """
    return '0x{:04x}'.format(id_in_bytes)

# For whatever reason node.manufacturer_id is of type string. So we need
# to convert the values.
FIBARO = _to_hex_str(workaround.FIBARO)
FIBARO_SHUTTERS = [_to_hex_str(workaround.FGR222_SHUTTER2),
                   _to_hex_str(workaround.FGRM222_SHUTTER2)]


def get_device(hass, values, node_config, **kwargs):
    """Create Z-Wave entity device."""
    invert_buttons = node_config.get(zwave.CONF_INVERT_OPENCLOSE_BUTTONS)
    if (values.primary.command_class ==
            zwave.const.COMMAND_CLASS_SWITCH_MULTILEVEL
            and values.primary.index == 0):
        if values.primary.node.manufacturer_id == FIBARO \
                and values.primary.node.product_type in FIBARO_SHUTTERS:
            # TODO: also check for venetian blind mode
            # need to read the ZWave configuration of the device for that
            return FibaroFGM222(hass, values, invert_buttons)
        else:
            return ZwaveRollershutter(hass, values, invert_buttons)
    elif (values.primary.command_class ==
          zwave.const.COMMAND_CLASS_SWITCH_BINARY):
        return ZwaveGarageDoorSwitch(values)
    elif (values.primary.command_class ==
          zwave.const.COMMAND_CLASS_BARRIER_OPERATOR):
        return ZwaveGarageDoorBarrier(values)
    return None


class ZwaveRollershutter(zwave.ZWaveDeviceEntity, CoverDevice):
    """Representation of an Z-Wave cover."""

    def __init__(self, hass, values, invert_buttons):
        """Initialize the Z-Wave rollershutter."""
        ZWaveDeviceEntity.__init__(self, values, DOMAIN)
        # pylint: disable=no-member
        self._network = hass.data[zwave.const.DATA_NETWORK]
        self._open_id = None
        self._close_id = None
        self._current_position = None
        self._invert_buttons = invert_buttons

        self._workaround = workaround.get_device_mapping(values.primary)
        if self._workaround:
            _LOGGER.debug("Using workaround %s", self._workaround)
        self.update_properties()

    def update_properties(self):
        """Handle data changes for node values."""
        # Position value
        self._current_position = self.values.primary.data

        if self.values.open and self.values.close and \
                self._open_id is None and self._close_id is None:
            if self._invert_buttons:
                self._open_id = self.values.close.value_id
                self._close_id = self.values.open.value_id
            else:
                self._open_id = self.values.open.value_id
                self._close_id = self.values.close.value_id

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        if self.current_cover_position is None:
            return None
        if self.current_cover_position > 0:
            return False
        return True

    @property
    def current_cover_position(self):
        """Return the current position of Zwave roller shutter."""
        if self._workaround == workaround.WORKAROUND_NO_POSITION:
            return None
        if self._current_position is not None:
            if self._current_position <= 5:
                return 0
            elif self._current_position >= 95:
                return 100
            return self._current_position

    def open_cover(self, **kwargs):
        """Move the roller shutter up."""
        self._network.manager.pressButton(self._open_id)

    def close_cover(self, **kwargs):
        """Move the roller shutter down."""
        self._network.manager.pressButton(self._close_id)

    def set_cover_position(self, **kwargs):
        """Move the roller shutter to a specific position."""
        self.node.set_dimmer(self.values.primary.value_id,
                             kwargs.get(ATTR_POSITION))

    def stop_cover(self, **kwargs):
        """Stop the roller shutter."""
        self._network.manager.releaseButton(self._open_id)


class ZwaveGarageDoorBase(zwave.ZWaveDeviceEntity, CoverDevice):
    """Base class for a Zwave garage door device."""

    def __init__(self, values):
        """Initialize the zwave garage door."""
        ZWaveDeviceEntity.__init__(self, values, DOMAIN)
        self._state = None
        self.update_properties()

    def update_properties(self):
        """Handle data changes for node values."""
        self._state = self.values.primary.data
        _LOGGER.debug("self._state=%s", self._state)

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return 'garage'

    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORT_GARAGE


class ZwaveGarageDoorSwitch(ZwaveGarageDoorBase):
    """Representation of a switch based Zwave garage door device."""

    @property
    def is_closed(self):
        """Return the current position of Zwave garage door."""
        return not self._state

    def close_cover(self, **kwargs):
        """Close the garage door."""
        self.values.primary.data = False

    def open_cover(self, **kwargs):
        """Open the garage door."""
        self.values.primary.data = True


class ZwaveGarageDoorBarrier(ZwaveGarageDoorBase):
    """Representation of a barrier operator Zwave garage door device."""

    @property
    def is_opening(self):
        """Return true if cover is in an opening state."""
        return self._state == "Opening"

    @property
    def is_closing(self):
        """Return true if cover is in a closing state."""
        return self._state == "Closing"

    @property
    def is_closed(self):
        """Return the current position of Zwave garage door."""
        return self._state == "Closed"

    def close_cover(self, **kwargs):
        """Close the garage door."""
        self.values.primary.data = "Closed"

    def open_cover(self, **kwargs):
        """Open the garage door."""
        self.values.primary.data = "Opened"


class FibaroFGM222(ZwaveRollershutter):
    """Implementation of proprietary features for Fibaro FGR-222 / FGRM-222.

    This adds support for the tile feature for the ventian blind mode.
    For this to work, you need to set the Zwave device configuration.
    """
    # TODO: describe the required configuration parameters

    def __init__(self, hass, values, invert_buttons):
        """Initialize the FFM222 with tilt mode enabled"""
        self._cached_value_blinds = None
        self._cached_value_tilt = None
        super().__init__(hass, values, invert_buttons)
        _LOGGER.debug('Device is a Fibaro FGR-222/FGRM-222 with tilt mode.')

    @property
    def current_cover_tilt_position(self):
        """Get the tilt of the bilnds."""
        if self._value_tilt is None:
            return None
        return self._value_tilt.data

    def set_cover_tilt_position(self, tilt_position, **kwargs):
        """Move the cover tilt to a specific position."""
        _LOGGER.debug("setting tilt to %d", tilt_position)
        if self._value_tilt is not None:
            self._value_tilt.data = tilt_position

    def open_cover_tilt(self, **kwargs):
        """Set slats to horizontal position."""
        self.set_cover_tilt_position(50)

    def close_cover_tilt(self, **kwargs):
        """Close the slats."""
        self.set_cover_tilt_position(0)

    @property
    def _value_blinds(self):
        """Read the blind position."""
        if self._cached_value_blinds is None:
            self._find_values()
        return self._cached_value_blinds

    @property
    def _value_tilt(self):
        """Read the tilt position."""
        if self._cached_value_tilt is None:
            self._find_values()
        return self._cached_value_tilt

    def set_cover_position(self, position, **kwargs):
        """Move the roller shutter to a specific position."""
        if self._value_blinds is not None:
            self._value_blinds.data = position

    def _find_values(self):
        """Get the current position from the zwave library."""
        values = self.node.get_values(class_id=0x91)
        for _, value in values.items():
            if value.index == 0:
                self._cached_value_blinds = value
            elif value.index == 1:
                self._cached_value_tilt = value
            else:
                _LOGGER.warning('Undefined index %d for this command class',
                                value.index)

    def update_properties(self):
        """React on properties being updated."""
        super().update_properties()
        if self._value_blinds is not None:
            self._current_position = self._value_blinds.data
