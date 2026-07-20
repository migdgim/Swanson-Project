"""Client NCBI E-utilities (PubMed) via Biopython.Entrez.

Responsabilita': cercare PMID per una query MeSH e scaricare i relativi record,
con rate limiting corretto, retry con backoff esponenziale e cache grezza su disco.
Il client e' agnostico alla config: parametri (query, finestre, tetti) arrivano dal
chiamante, che li legge da `engine/config/pilot.yaml`.
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import urllib.error
from collections.abc import Callable
from datetime import datetime, timezone
from http.client import IncompleteRead
from typing import Any, TypeVar, cast

from Bio import Entrez

from .cache import Cache

T = TypeVar("T")


def _is_retryable(exc: Exception) -> bool:
    """True per errori transitori: rete giu', 5xx/429 di NCBI, risposta troncata."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429
    return isinstance(exc, (urllib.error.URLError, IncompleteRead, TimeoutError, ConnectionError))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_plain(obj: Any) -> Any:
    """Converte le strutture Entrez (sottoclassi di str/dict/list) in tipi puri JSON."""
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


class EntrezClient:
    def __init__(
        self,
        *,
        api_key: str,
        email: str,
        cache: Cache,
        rate_per_sec: int = 10,
        tool: str = "swanson-lbd",
        max_retries: int = 4,
    ) -> None:
        if not api_key:
            raise ValueError("NCBI_API_KEY mancante: prerequisito bloccante per l'ingest.")
        if not email:
            raise ValueError("NCBI_EMAIL mancante: E-utilities richiede un contatto.")
        Entrez.email = email
        Entrez.api_key = api_key
        Entrez.tool = tool
        self.cache = cache
        self.max_retries = max_retries
        self._min_interval = 1.0 / float(rate_per_sec)
        self._last_call = 0.0

    # --- infrastruttura -------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _with_retry(self, fn: Callable[[], T]) -> T:
        attempt = 0
        while True:
            self._throttle()
            try:
                return fn()
            except Exception as exc:  # pragma: no cover - dipende dalla rete
                if not _is_retryable(exc):
                    raise
                attempt += 1
                if attempt > self.max_retries:
                    raise
                backoff = 2.0**attempt
                print(f"    [retry {attempt}/{self.max_retries}] {type(exc).__name__}: {exc} "
                      f"-> attendo {backoff:.0f}s")
                time.sleep(backoff)

    @staticmethod
    def _key(endpoint: str, params: dict[str, Any]) -> str:
        blob = endpoint + "|" + json.dumps(params, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # --- esearch --------------------------------------------------------

    def search_pmids(
        self,
        query: str,
        *,
        retmax: int,
        min_year: int | None = None,
        max_year: int | None = None,
        sort: str = "pub_date",
    ) -> tuple[list[str], int]:
        """Ritorna (pmids, total_hits). `total_hits` e' il conteggio reale su PubMed,
        anche quando supera `retmax` (per rendere esplicita l'eventuale troncatura)."""
        params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retmax": retmax,
            "retmode": "xml",
            "sort": sort,
            "datetype": "pdat",
        }
        if min_year is not None:
            params["mindate"] = str(min_year)
        if max_year is not None:
            params["maxdate"] = str(max_year)

        cache_key = self._key("esearch", params)
        cached = self.cache.get_eutils(cache_key)
        if cached is not None:
            record = json.loads(cached)
        else:
            def _call() -> dict[str, Any]:
                handle = Entrez.esearch(**params)
                try:
                    return cast("dict[str, Any]", _to_plain(Entrez.read(handle)))
                finally:
                    handle.close()

            record = self._with_retry(_call)
            self.cache.put_eutils(cache_key, "esearch", params, json.dumps(record), _utc_now_iso())

        pmids = [str(p) for p in record.get("IdList", [])]
        total = int(record.get("Count", len(pmids)))
        return pmids, total

    # --- efetch ---------------------------------------------------------

    def fetch_papers(self, pmids: list[str], *, batch_size: int = 200) -> int:
        """Scarica e persiste i record mancanti. Ritorna il numero di paper nuovi salvati.
        I PMID gia' in cache sono saltati (idempotente / offline-ripetibile)."""
        known = self.cache.known_pmids(pmids)
        missing = [p for p in pmids if p not in known]
        saved = 0
        total_batches = (len(missing) + batch_size - 1) // batch_size
        for bi, i in enumerate(range(0, len(missing), batch_size), start=1):
            batch = missing[i : i + batch_size]
            print(f"    efetch batch {bi}/{total_batches} ({len(batch)} pmid)")
            articles = self._efetch_batch(batch)
            rows = [self._parse_article(a) for a in articles]
            rows = [r for r in rows if r is not None]
            if rows:
                self.cache.upsert_papers(rows)  # type: ignore[arg-type]
                saved += len(rows)
        return saved

    def _efetch_batch(self, pmids: list[str]) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        cache_key = self._key("efetch", params)
        cached = self.cache.get_eutils(cache_key)
        if cached is not None:
            record = json.loads(cached)
        else:
            def _call() -> dict[str, Any]:
                handle = Entrez.efetch(**params)
                try:
                    raw = handle.read()
                finally:
                    handle.close()
                data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
                return cast("dict[str, Any]", _to_plain(Entrez.read(io.BytesIO(data))))

            record = self._with_retry(_call)
            self.cache.put_eutils(cache_key, "efetch", params, json.dumps(record), _utc_now_iso())

        return list(record.get("PubmedArticle", []))

    # --- parsing --------------------------------------------------------

    @staticmethod
    def _parse_article(article: dict[str, Any]) -> dict[str, Any] | None:
        try:
            citation = article["MedlineCitation"]
            pmid = str(citation["PMID"])
            art = citation["Article"]
        except (KeyError, TypeError):
            return None

        title = art.get("ArticleTitle")
        abstract = EntrezClient._extract_abstract(art)
        journal = None
        journal_obj = art.get("Journal", {})
        if isinstance(journal_obj, dict):
            journal = journal_obj.get("Title")
        pub_date, pub_year = EntrezClient._extract_pubdate(art, citation)

        return {
            "pmid": pmid,
            "pub_date": pub_date,
            "pub_year": pub_year,
            "journal": str(journal) if journal is not None else None,
            "title": str(title) if title is not None else None,
            "abstract": abstract,
            "raw": article,
            "fetched_at": _utc_now_iso(),
        }

    @staticmethod
    def _extract_abstract(art: dict[str, Any]) -> str | None:
        abstract_obj = art.get("Abstract")
        if not isinstance(abstract_obj, dict):
            return None
        parts = abstract_obj.get("AbstractText")
        if parts is None:
            return None
        if isinstance(parts, list):
            texts = [str(p) for p in parts if str(p).strip()]
            return "\n".join(texts) if texts else None
        text = str(parts).strip()
        return text or None

    @staticmethod
    def _extract_pubdate(
        art: dict[str, Any], citation: dict[str, Any]
    ) -> tuple[str | None, int | None]:
        pub_date = None
        year: int | None = None
        journal = art.get("Journal", {})
        issue = journal.get("JournalIssue", {}) if isinstance(journal, dict) else {}
        pd = issue.get("PubDate", {}) if isinstance(issue, dict) else {}

        if isinstance(pd, dict):
            y = pd.get("Year")
            if y is not None:
                year = EntrezClient._safe_year(str(y))
                pub_date = str(y)
                month = EntrezClient._month_num(pd.get("Month"))
                if month:
                    pub_date = f"{y}-{month:02d}"
                    day = pd.get("Day")
                    if day is not None and str(day).isdigit():
                        pub_date = f"{y}-{month:02d}-{int(day):02d}"
            elif pd.get("MedlineDate"):
                med = str(pd["MedlineDate"])
                pub_date = med
                year = EntrezClient._safe_year(med[:4])

        # Fallback: data di completamento MEDLINE (raro, ma meglio di None per il time-slicing).
        if year is None:
            dc = citation.get("DateCompleted") or citation.get("DateRevised")
            if isinstance(dc, dict) and dc.get("Year"):
                year = EntrezClient._safe_year(str(dc["Year"]))
                if pub_date is None:
                    pub_date = str(dc["Year"])

        return pub_date, year

    @staticmethod
    def _safe_year(s: str) -> int | None:
        s = s.strip()[:4]
        return int(s) if s.isdigit() else None

    @staticmethod
    def _month_num(month: Any) -> int | None:
        if month is None:
            return None
        m = str(month).strip()
        if m.isdigit():
            n = int(m)
            return n if 1 <= n <= 12 else None
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        return months.get(m[:3].lower())
