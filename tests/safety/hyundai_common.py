import numpy as np
from typing import Tuple

import panda.tests.safety.common as common
from panda.tests.safety.common import make_msg


class Buttons:
  NONE = 0
  RESUME = 1
  SET = 2
  CANCEL = 4


MAX_ACCEL = 2.0
MIN_ACCEL = -3.5
PREV_BUTTON_SAMPLES = 8
ENABLE_BUTTONS = (Buttons.RESUME, Buttons.SET, Buttons.CANCEL)


class HyundaiButtonBase:
  # pylint: disable=no-member,abstract-method
  BUTTONS_BUS = 0  # tx on this bus, rx on 0. added to all `self._tx(self._button_msg(...))`
  SCC_BUS = 0  # rx on this bus

  def test_button_sends(self):
    """
      Only RES and CANCEL buttons are allowed
      - RES allowed while controls allowed
      - CANCEL allowed while cruise is enabled
    """
    self.safety.set_controls_allowed(0)
    self.assertFalse(self._tx(self._button_msg(Buttons.RESUME, bus=self.BUTTONS_BUS)))
    self.assertFalse(self._tx(self._button_msg(Buttons.SET, bus=self.BUTTONS_BUS)))

    self.safety.set_controls_allowed(1)
    self.assertTrue(self._tx(self._button_msg(Buttons.RESUME, bus=self.BUTTONS_BUS)))
    self.assertFalse(self._tx(self._button_msg(Buttons.SET, bus=self.BUTTONS_BUS)))

    for enabled in (True, False):
      self._rx(self._pcm_status_msg(enabled))
      self.assertEqual(enabled, self._tx(self._button_msg(Buttons.CANCEL, bus=self.BUTTONS_BUS)))

  def test_enable_control_allowed_from_cruise(self):
    """
      Hyundai non-longitudinal only enables on PCM rising edge and recent button press. Tests PCM enabling with:
      - disallowed: No buttons
      - disallowed: Buttons that don't enable cruise
      - allowed: Buttons that do enable cruise
      - allowed: Main button with all above combinations
    """
    for main_button in (0, 1):
      for btn in range(8):
        for _ in range(PREV_BUTTON_SAMPLES):  # reset
          self._rx(self._button_msg(Buttons.NONE))

        self._rx(self._pcm_status_msg(False))
        self.assertFalse(self.safety.get_controls_allowed())
        self._rx(self._button_msg(btn, main_button=main_button))
        self._rx(self._pcm_status_msg(True))
        controls_allowed = btn in ENABLE_BUTTONS or main_button
        self.assertEqual(controls_allowed, self.safety.get_controls_allowed())

  def test_sampling_cruise_buttons(self):
    """
      Test that we allow controls on recent button press, but not as button leaves sliding window
    """
    self._rx(self._button_msg(Buttons.SET))
    for i in range(2 * PREV_BUTTON_SAMPLES):
      self._rx(self._pcm_status_msg(False))
      self.assertFalse(self.safety.get_controls_allowed())
      self._rx(self._pcm_status_msg(True))
      controls_allowed = i < PREV_BUTTON_SAMPLES
      self.assertEqual(controls_allowed, self.safety.get_controls_allowed())
      self._rx(self._button_msg(Buttons.NONE))


class HyundaiLongitudinalBase:
  # pylint: disable=no-member,abstract-method

  DISABLED_ECU_UDS_MSG: Tuple[int, int]
  DISABLED_ECU_ACTUATION_MSG: Tuple[int, int]

  # override these tests from PandaSafetyTest, hyundai longitudinal uses button enable
  def test_disable_control_allowed_from_cruise(self):
    pass

  def test_enable_control_allowed_from_cruise(self):
    pass

  def test_sampling_cruise_buttons(self):
    pass

  def test_cruise_engaged_prev(self):
    pass

  def test_button_sends(self):
    pass

  def _pcm_status_msg(self, enable):
    raise Exception

  def _accel_msg(self, accel, aeb_req=False, aeb_decel=0):
    raise NotImplementedError

  def test_set_resume_buttons(self):
    """
      SET and RESUME enter controls allowed on their falling edge.
    """
    for btn in range(8):
      self.safety.set_controls_allowed(0)
      for _ in range(10):
        self._rx(self._button_msg(btn))
        self.assertFalse(self.safety.get_controls_allowed())

      # should enter controls allowed on falling edge
      if btn in (Buttons.RESUME, Buttons.SET):
        self._rx(self._button_msg(Buttons.NONE))
        self.assertTrue(self.safety.get_controls_allowed())

  def test_cancel_button(self):
    self.safety.set_controls_allowed(1)
    self._rx(self._button_msg(Buttons.CANCEL))
    self.assertFalse(self.safety.get_controls_allowed())

  def test_accel_safety_check(self):
    for controls_allowed in [True, False]:
      for accel in np.arange(MIN_ACCEL - 1, MAX_ACCEL + 1, 0.01):
        accel = round(accel, 2) # floats might not hit exact boundary conditions without rounding
        self.safety.set_controls_allowed(controls_allowed)
        send = MIN_ACCEL <= accel <= MAX_ACCEL if controls_allowed else accel == 0
        self.assertEqual(send, self._tx(self._accel_msg(accel)), (controls_allowed, accel))

  def test_tester_present_allowed(self):
    """
      Ensure tester present diagnostic message is allowed to keep ECU knocked out
      for longitudinal control.
    """

    addr, bus = self.DISABLED_ECU_UDS_MSG
    tester_present = common.package_can_msg((addr, 0, b"\x02\x3E\x80\x00\x00\x00\x00\x00", bus))
    self.assertTrue(self.safety.safety_tx_hook(tester_present))

    not_tester_present = common.package_can_msg((addr, 0, b"\x03\xAA\xAA\x00\x00\x00\x00\x00", bus))
    self.assertFalse(self.safety.safety_tx_hook(not_tester_present))

  def test_disabled_ecu_alive(self):
    """
      If the ECU knockout failed, make sure the relay malfunction is shown
    """

    addr, bus = self.DISABLED_ECU_ACTUATION_MSG
    self.assertFalse(self.safety.get_relay_malfunction())
    self._rx(make_msg(bus, addr, 8))
    self.assertTrue(self.safety.get_relay_malfunction())

