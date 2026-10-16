"""PPO actions stay long or flat."""

from services.model_train_service.trainers.rl_actions import apply_position


def test_buy_opens_a_long_from_cash():
    assert apply_position(0, 1) == 1.0


def test_sell_closes_the_long():
    assert apply_position(1, 2) == 0.0


def test_sell_does_not_open_a_short():
    assert apply_position(0, 2) == 0.0
    assert apply_position(-1, 2) == 0.0


def test_hold_keeps_the_current_side():
    assert apply_position(0, 0) == 0.0
    assert apply_position(1, 0) == 1.0
    assert apply_position(1, 1) == 1.0
