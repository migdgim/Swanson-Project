"""Rate limiter a intervallo minimo, per rispettare i limiti delle API esterne.

NCBI E-utilities ammette 10 richieste/secondo con API key (3 senza); PubTator3 ha
un limite analogo. Questa utility impone l'intervallo minimo fra chiamate successive
ed è condivisa dai client di ingest (`entrez_client`, in seguito `pubtator_client`).

Solo standard library. `clock`/`sleep` sono iniettabili: in produzione usano
`time.monotonic`/`time.sleep`, nei test un orologio finto — così la logica di
temporizzazione è verificabile senza attese reali.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class RateLimiter:
    """Garantisce almeno `1/rate_per_sec` secondi fra due `acquire()` consecutivi."""

    def __init__(
        self,
        rate_per_sec: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError(f"rate_per_sec deve essere > 0, ricevuto {rate_per_sec!r}")
        self._min_interval = 1.0 / rate_per_sec
        self._clock = clock
        self._sleep = sleep
        self._next_allowed: float | None = None

    def acquire(self) -> None:
        """Blocca (dorme) quanto basta perché non si superi il rate configurato."""
        now = self._clock()
        wait = 0.0 if self._next_allowed is None else self._next_allowed - now
        if wait > 0:
            self._sleep(wait)
            now = now + wait  # tempo logico dopo l'attesa (non dipende dal clock reale)
        self._next_allowed = now + self._min_interval
