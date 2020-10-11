from pophttp.lifx import Message as LifxMessage
from pophttp import pophttp
try:
    from unittest.mock import call
except ImportError:
    from mock import call

def mock_time(mocker):
    class TimeMock(object):
        def __init__(self):
            self.now = 0

        def set_now(self, now):
            self.now = now

        def __call__(self):
            return self.now

    time_mock = TimeMock()
    mocker.patch('time.time', TimeMock())
    return time_mock

def replay_messages(handler, time_mock, msg_seq):
    for msg_time, bridge_addr, msg in sorted(msg_seq):
        time_mock.set_now(msg_time)
        handler.handle_msg(bridge_addr, msg)

class FakeConfig(object):
    def get_urls(self, hue, saturation, brightness, kelvin, power):
        return ['http://example.com']

def build_action_msg_seq(start=0, bridge_addr=('10.0.0.1', 56700), on=True, hue=24102, saturation=31097, brightness=32768, kelvin=3612, sequence=None):
    #The bridge sends multiple of the same message sequence SetPower/SetColour over a several second period all for the same action
    #This is because the LIFX protocol is UDP-based and does not guarantee delivery of messages
    power_msg = LifxMessage.Light_SetPower(level=65535 if on else 0, duration=1000)
    color_msg = LifxMessage.Light_SetColor(stream=0, hue=hue, saturation=saturation, brightness=brightness, kelvin=kelvin, duration=1000)
    return (bridge_addr, power_msg, color_msg), [
        (start + 0.000, bridge_addr, power_msg),
        (start + 0.002, bridge_addr, color_msg),
        (start + 0.055, bridge_addr, power_msg),
        (start + 0.057, bridge_addr, color_msg),
        (start + 0.134, bridge_addr, power_msg),
        (start + 0.141, bridge_addr, color_msg),
        (start + 0.275, bridge_addr, power_msg),
        (start + 0.277, bridge_addr, color_msg),
        (start + 0.509, bridge_addr, power_msg),
        (start + 0.510, bridge_addr, color_msg),
        (start + 0.873, bridge_addr, power_msg),
        (start + 0.875, bridge_addr, color_msg),
        (start + 1.469, bridge_addr, power_msg),
        (start + 1.472, bridge_addr, color_msg),
        (start + 2.443, bridge_addr, power_msg),
        (start + 2.444, bridge_addr, color_msg),
        (start + 4.042, bridge_addr, power_msg),
        (start + 4.045, bridge_addr, color_msg)
    ]

def build_idle_msg_seq(start=0, bridge_addr=('10.0.0.1', 56700)):
    #The Pop bridge will periodically send a Get & GetVersion message to keep track of available devices and their current power/color
    #It will also send it very shortly after sending a button action
    return [
        (start + 0.000, bridge_addr, LifxMessage.Light_Get()),
        (start + 0.003, bridge_addr, LifxMessage.Device_GetVersion()),
        (start + 0.307, bridge_addr, LifxMessage.Light_Get()),
        (start + 0.310, bridge_addr, LifxMessage.Device_GetVersion()),
        (start + 0.312, bridge_addr, LifxMessage.Light_Get()),
        (start + 0.313, bridge_addr, LifxMessage.Device_GetVersion())
    ]




class TestSingleBridge(object):
    def test_single_trigger(self, mocker):
        trigger_mock = mocker.patch('pophttp.pophttp.MessageHandler.trigger_action')
        time_mock = mock_time(mocker)
        hdlr = pophttp.MessageHandler(FakeConfig())

        _, msg_seq = build_action_msg_seq()
        replay_messages(hdlr, time_mock, msg_seq)
        trigger_mock.assert_called_once()

    def test_on_then_off_with_delay(self, mocker):
        trigger_mock = mocker.patch('pophttp.pophttp.MessageHandler.trigger_action')
        time_mock = mock_time(mocker)
        hdlr = pophttp.MessageHandler(FakeConfig())

        expect_call, msg_seq = build_action_msg_seq(start=0, on=True)
        replay_messages(hdlr, time_mock, msg_seq)
        trigger_mock.assert_called_once_with(*expect_call)
        trigger_mock.reset_mock()

        expect_call, msg_seq = build_action_msg_seq(start=10, on=False)
        replay_messages(hdlr, time_mock, msg_seq)
        trigger_mock.assert_called_once_with(*expect_call)

    def test_on_then_off_quickly(self, mocker):
        trigger_mock = mocker.patch('pophttp.pophttp.MessageHandler.trigger_action')
        time_mock = mock_time(mocker)
        hdlr = pophttp.MessageHandler(FakeConfig())

        expect_call_1, msg_seq_1 = build_action_msg_seq(start=0, on=True)
        expect_call_2, msg_seq_2 = build_action_msg_seq(start=2, on=False)
        msg_seq = [m for m in msg_seq_1 if m[0] < 2] #The pop bridge stops sending messages of a new sequence is started so restrict to first 2 seconds
        msg_seq += msg_seq_2

        replay_messages(hdlr, time_mock, msg_seq)
        trigger_mock.assert_has_calls([
            call(*expect_call_1),
            call(*expect_call_2)
        ])
        assert trigger_mock.call_count == 2


class TestMultiplleBridges(object):
    BRIDGE_1 = ('10.0.0.1', 56700)
    BRIDGE_2 = ('10.0.0.2', 56700)

    def test_single_trigger(self, mocker):
        trigger_mock = mocker.patch('pophttp.pophttp.MessageHandler.trigger_action')
        time_mock = mock_time(mocker)
        hdlr = pophttp.MessageHandler(FakeConfig())

        expect_call, msg_seq_b1 = build_action_msg_seq(bridge_addr=self.BRIDGE_1)
        _,           msg_seq_b2 = build_action_msg_seq(bridge_addr=self.BRIDGE_2, start=0.01)
        replay_messages(hdlr, time_mock, msg_seq_b1 + msg_seq_b2)
        trigger_mock.assert_called_once_with(*expect_call)

    def test_on_then_off_with_delay(self, mocker):
        trigger_mock = mocker.patch('pophttp.pophttp.MessageHandler.trigger_action')
        time_mock = mock_time(mocker)
        hdlr = pophttp.MessageHandler(FakeConfig())

        expect_call, msg_seq_b1 = build_action_msg_seq(start=0.00, bridge_addr=self.BRIDGE_1)
        _,           msg_seq_b2 = build_action_msg_seq(start=0.01, bridge_addr=self.BRIDGE_2)
        replay_messages(hdlr, time_mock, msg_seq_b1 + msg_seq_b2)
        trigger_mock.assert_called_once_with(*expect_call)
        trigger_mock.reset_mock()

        expect_call, msg_seq_b1 = build_action_msg_seq(start=10.00, bridge_addr=self.BRIDGE_1, on=False)
        _,           msg_seq_b2 = build_action_msg_seq(start=10.01, bridge_addr=self.BRIDGE_2, on=False)
        replay_messages(hdlr, time_mock, msg_seq_b1 + msg_seq_b2)
        trigger_mock.assert_called_once_with(*expect_call)

    def test_on_then_off_quickly(self, mocker):
        trigger_mock = mocker.patch('pophttp.pophttp.MessageHandler.trigger_action')
        time_mock = mock_time(mocker)
        hdlr = pophttp.MessageHandler(FakeConfig())

        expect_call_1, msg_seq_1_b1 = build_action_msg_seq(start=0.00, bridge_addr=self.BRIDGE_1, on=True)
        _,             msg_seq_1_b2 = build_action_msg_seq(start=0.01, bridge_addr=self.BRIDGE_2, on=True)
        expect_call_2, msg_seq_2_b1 = build_action_msg_seq(start=2.00, bridge_addr=self.BRIDGE_1, on=False)
        _,             msg_seq_2_b2 = build_action_msg_seq(start=2.01, bridge_addr=self.BRIDGE_2, on=False)
        msg_seq = [m for m in msg_seq_1_b1 if m[0] < 2] + [m for m in msg_seq_1_b2 if m[0] < 2.01] #The pop bridge stops sending messages of a new sequence is started so restrict to first 2 seconds
        msg_seq += msg_seq_2_b1 + msg_seq_2_b2

        replay_messages(hdlr, time_mock, msg_seq)
        trigger_mock.assert_has_calls([
            call(*expect_call_1),
            call(*expect_call_2)
        ])
        assert trigger_mock.call_count == 2

    def test_on_then_off_quickly_bridge_2_slow(self, mocker):
        trigger_mock = mocker.patch('pophttp.pophttp.MessageHandler.trigger_action')
        time_mock = mock_time(mocker)
        hdlr = pophttp.MessageHandler(FakeConfig())

        expect_call_1, msg_seq_1_b1 = build_action_msg_seq(start=0.00, bridge_addr=self.BRIDGE_1, on=True)
        _,             msg_seq_1_b2 = build_action_msg_seq(start=0.01, bridge_addr=self.BRIDGE_2, on=True)
        expect_call_2, msg_seq_2_b1 = build_action_msg_seq(start=2.00, bridge_addr=self.BRIDGE_1, on=False)
        _,             msg_seq_2_b2 = build_action_msg_seq(start=4.01, bridge_addr=self.BRIDGE_2, on=False)
        msg_seq = [m for m in msg_seq_1_b1 if m[0] < 2] + [m for m in msg_seq_1_b2 if m[0] < 4.01] #The pop bridge stops sending messages of a new sequence is started so restrict to first 2 seconds
        msg_seq += msg_seq_2_b1 + msg_seq_2_b2

        replay_messages(hdlr, time_mock, msg_seq)
        trigger_mock.assert_has_calls([
            call(*expect_call_1),
            call(*expect_call_2)
        ])
        assert trigger_mock.call_count == 2
