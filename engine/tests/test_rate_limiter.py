"""Test del RateLimiter con orologio finto (nessuna attesa reale).

`unittest.TestCase`: eseguibili subito con la sola stdlib. Il clock finto avanza
solo quando il limiter "dorme", così possiamo asserire gli intervalli esatti.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ingest.rate_limiter import RateLimiter  # noqa: E402


class FakeClock:
    """Orologio virtuale: `sleep` avanza il tempo, come farebbe quello reale."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.sleeps.append(d)
        self.t += d


class RateLimiterTest(unittest.TestCase):
    def test_invalid_rate_raises(self) -> None:
        with self.assertRaises(ValueError):
            RateLimiter(0)
        with self.assertRaises(ValueError):
            RateLimiter(-5)

    def test_first_acquire_never_sleeps(self) -> None:
        clock = FakeClock()
        rl = RateLimiter(10, clock=clock.time, sleep=clock.sleep)
        rl.acquire()
        self.assertEqual(clock.sleeps, [])

    def test_enforces_min_interval(self) -> None:
        clock = FakeClock()
        rl = RateLimiter(10, clock=clock.time, sleep=clock.sleep)  # intervallo 0.1s
        for _ in range(3):
            rl.acquire()
        # 3 chiamate a raffica -> 2 attese da 0.1s; tempo totale trascorso 0.2s.
        self.assertEqual(len(clock.sleeps), 2)
        for d in clock.sleeps:
            self.assertAlmostEqual(d, 0.1, places=9)
        self.assertAlmostEqual(clock.t, 0.2, places=9)

    def test_no_sleep_when_enough_time_already_passed(self) -> None:
        clock = FakeClock()
        rl = RateLimiter(10, clock=clock.time, sleep=clock.sleep)
        rl.acquire()
        clock.t += 0.5  # il chiamante ha già speso più dell'intervallo facendo altro
        rl.acquire()
        self.assertEqual(clock.sleeps, [])  # nessuna attesa necessaria

    def test_rate_of_three_per_second(self) -> None:
        clock = FakeClock()
        rl = RateLimiter(3, clock=clock.time, sleep=clock.sleep)  # senza API key: 3/s
        for _ in range(4):
            rl.acquire()
        self.assertEqual(len(clock.sleeps), 3)
        for d in clock.sleeps:
            self.assertAlmostEqual(d, 1.0 / 3.0, places=9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
