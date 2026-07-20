"""Client NCBI E-utilities (PubMed) per l'ingest del corpus (S0).

Responsabilità:
  - leggere `NCBI_API_KEY` / `NCBI_EMAIL` dall'ambiente (`.env`),
  - interrogare PubMed (`esearch`) e scaricare gli abstract (`efetch`),
  - rispettare il rate limit (10 req/s con key, 3 senza) tramite `RateLimiter`,
  - riprovare con backoff esponenziale sugli errori transitori,
  - normalizzare i campi chiave e conservare SEMPRE la risposta grezza per la cache.

⚠️  STATO: **NON ESEGUITO.** Questo modulo richiede `biopython` (non installato:
    va creato il venv, "previa conferma") e una `NCBI_API_KEY` valida nel `.env`.
    Il codice è scritto a specifica ma non è ancora stato eseguito end-to-end
    contro PubMed. La logica di temporizzazione è isolata in `rate_limiter.py` ed
    è invece coperta da test eseguiti.

Riferimenti: DesignArchitecture §3 (ingest), §5 (pipeline), §6.1 (schema cache).
"""

from __future__ import annotations

import os
import re
import time
import urllib.error
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from http.client import IncompleteRead
from typing import TYPE_CHECKING, Any

from .rate_limiter import RateLimiter

if TYPE_CHECKING:  # evita di importare Bio/cache a runtime dove non serve
    from .cache import Cache

# HTTP status su cui ha senso ritentare (throttling / errori server transitori).
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


@dataclass(frozen=True)
class ParsedPaper:
    """Vista normalizzata di un articolo PubMed. `raw` conserva la risposta intatta.

    `pub_date`, quando presente, inizia sempre con l'anno a 4 cifre (YYYY o
    YYYY-MM[-DD]): è il contratto atteso da `Cache.year_counts()`.
    """

    pmid: str
    pub_date: str | None
    journal: str | None
    title: str | None
    abstract: str | None
    raw: dict[str, Any]


@dataclass
class CorpusReport:
    """Esito di un download di corpus — sorgente del 'report a una riga' di S0."""

    query: str
    found: int          # PMID restituiti da esearch
    fetched: int        # nuovi paper effettivamente scaricati e messi in cache
    cached_total: int   # totale paper in cache dopo il download

    def as_line(self) -> str:
        return (
            f"corpus: found={self.found} fetched={self.fetched} "
            f"cached_total={self.cached_total} | query={self.query!r}"
        )


class EntrezClient:
    """Wrapper tipizzato attorno a `Bio.Entrez`, con rate limiting e retry."""

    def __init__(
        self,
        *,
        email: str,
        api_key: str | None = None,
        tool: str = "swanson-lbd",
        rate_per_sec: float = 10.0,
        max_retries: int = 4,
        base_backoff: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not email:
            raise ValueError("NCBI richiede un'email di contatto (NCBI_EMAIL).")
        # Import ritardato: Bio serve solo se si usa davvero il client.
        from Bio import Entrez

        self._entrez = Entrez
        Entrez.email = email
        Entrez.tool = tool
        if api_key:
            Entrez.api_key = api_key

        # Senza API key NCBI impone max 3 req/s: si abbassa il rate per sicurezza.
        effective_rate = rate_per_sec if api_key else min(rate_per_sec, 3.0)
        self._limiter = RateLimiter(effective_rate)
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._sleep = sleep
        self.has_api_key = bool(api_key)

    # -- costruzione da ambiente ------------------------------------------

    @classmethod
    def from_env(cls, *, rate_per_sec: float = 10.0, tool: str = "swanson-lbd") -> EntrezClient:
        """Costruisce il client leggendo i segreti da `.env`/ambiente.

        Carica `.env` con python-dotenv se disponibile; altrimenti usa `os.environ`.
        """
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ModuleNotFoundError:
            pass
        email = os.environ.get("NCBI_EMAIL", "")
        api_key = os.environ.get("NCBI_API_KEY") or None
        if not email:
            raise RuntimeError("NCBI_EMAIL non impostata nel .env / ambiente.")
        return cls(email=email, api_key=api_key, rate_per_sec=rate_per_sec, tool=tool)

    # -- query -------------------------------------------------------------

    def search_pmids(
        self,
        query: str,
        *,
        retmax: int,
        min_year: int | None = None,
        max_year: int | None = None,
    ) -> list[str]:
        """Ritorna i PMID che soddisfano la query MeSH.

        NB: una singola `esearch` restituisce al massimo ~9999 ID; per il corpus
        pilota (`retmax` ~5000) basta una chiamata. Oltre quella soglia servirà la
        paginazione con `usehistory` (non necessaria ora).
        """
        kwargs: dict[str, Any] = {"db": "pubmed", "term": query, "retmax": retmax}
        if min_year is not None:
            kwargs["datetype"] = "pdat"
            kwargs["mindate"] = str(min_year)
            kwargs["maxdate"] = str(max_year) if max_year is not None else "3000"

        def _call() -> dict[str, Any]:
            handle = self._entrez.esearch(**kwargs)
            try:
                return dict(self._entrez.read(handle))
            finally:
                handle.close()

        record = self._with_retry(_call)
        return [str(pmid) for pmid in record.get("IdList", [])]

    def fetch_records(
        self, pmids: Sequence[str], *, batch_size: int = 200
    ) -> Iterator[ParsedPaper]:
        """Scarica e normalizza gli abstract, a batch. `raw` resta sempre integrale."""
        for start in range(0, len(pmids), batch_size):
            batch = pmids[start : start + batch_size]
            if not batch:
                continue

            def _call(ids: Sequence[str] = batch) -> dict[str, Any]:
                handle = self._entrez.efetch(
                    db="pubmed", id=",".join(ids), rettype="xml", retmode="xml"
                )
                try:
                    return dict(self._entrez.read(handle))
                finally:
                    handle.close()

            record = self._with_retry(_call)
            for article in record.get("PubmedArticle", []):
                parsed = _parse_article(article)
                if parsed is not None:
                    yield parsed

    # -- retry -------------------------------------------------------------

    def _with_retry(self, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Esegue `fn` rispettando il rate limit; ritenta con backoff esponenziale
        (2s, 4s, 8s, 16s) sugli errori transitori. Rilancia gli errori non transitori."""
        attempt = 0
        while True:
            self._limiter.acquire()
            try:
                return fn()
            except urllib.error.HTTPError as exc:
                if exc.code not in _RETRYABLE_STATUS or attempt >= self._max_retries:
                    raise
            except (urllib.error.URLError, IncompleteRead, TimeoutError, ConnectionError):
                if attempt >= self._max_retries:
                    raise
            self._sleep(self._base_backoff * (2**attempt))
            attempt += 1


# --- parsing (funzioni pure, senza stato) --------------------------------


def _parse_article(article: Any) -> ParsedPaper | None:
    """Estrae i campi chiave da un elemento `PubmedArticle`. Best-effort: se manca
    un campo opzionale resta None, ma `raw` conserva tutto."""
    try:
        citation = article["MedlineCitation"]
        pmid = str(citation["PMID"])
    except (KeyError, TypeError):
        return None
    art = citation.get("Article", {})
    return ParsedPaper(
        pmid=pmid,
        pub_date=_extract_pub_date(art),
        journal=_extract_journal(art),
        title=_extract_title(art),
        abstract=_extract_abstract(art),
        raw=_to_plain(article),
    )


def _extract_title(article: Any) -> str | None:
    title = article.get("ArticleTitle")
    return str(title) if title else None


def _extract_journal(article: Any) -> str | None:
    title = article.get("Journal", {}).get("Title")
    return str(title) if title else None


def _extract_abstract(article: Any) -> str | None:
    parts = article.get("Abstract", {}).get("AbstractText")
    if not parts:
        return None
    if isinstance(parts, (list, tuple)):
        return "\n".join(str(p) for p in parts if str(p)) or None
    return str(parts) or None


def _extract_pub_date(article: Any) -> str | None:
    """Ritorna una data che inizia con l'anno a 4 cifre (contratto di `year_counts`)."""
    for adate in article.get("ArticleDate", []) or []:
        ymd = _ymd(adate)
        if ymd:
            return ymd
    pubdate = article.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
    ymd = _ymd(pubdate)
    if ymd:
        return ymd
    # PubDate a volte è testuale ("2010 Jan-Feb"): prendo il primo anno a 4 cifre.
    medline = pubdate.get("MedlineDate")
    if medline:
        match = re.search(r"\d{4}", str(medline))
        if match:
            return match.group(0)
    return None


def _ymd(date_el: Any) -> str | None:
    year = date_el.get("Year")
    if not year:
        return None
    year = str(year)
    if len(year) != 4 or not year.isdigit():
        return None
    month = _month_num(date_el.get("Month"))
    day = date_el.get("Day")
    if month and day and str(day).isdigit():
        return f"{year}-{month:02d}-{int(day):02d}"
    if month:
        return f"{year}-{month:02d}"
    return year


def _month_num(month: Any) -> int | None:
    if not month:
        return None
    text = str(month).strip().lower()
    if text.isdigit():
        n = int(text)
        return n if 1 <= n <= 12 else None
    return _MONTHS.get(text[:3])


def _to_plain(obj: Any) -> Any:
    """Converte gli elementi di Bio.Entrez (sottotipi di dict/list/str) in tipi
    puri, così la cache può serializzarli in JSON in modo stabile."""
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (int, float)):
        return obj
    return str(obj)


# --- orchestrazione S0: esearch -> efetch -> cache -----------------------


def download_corpus(
    client: EntrezClient,
    cache: Cache,
    *,
    query: str,
    retmax: int,
    min_year: int | None = None,
    batch_size: int = 200,
    skip_cached: bool = True,
) -> CorpusReport:
    """Scarica il corpus e lo persiste in cache. Idempotente: i PMID già presenti
    vengono saltati (re-run offline), a meno di `skip_cached=False`."""
    pmids = client.search_pmids(query, retmax=retmax, min_year=min_year)
    to_fetch = [p for p in pmids if not (skip_cached and cache.has_paper(p))]
    fetched = 0
    for paper in client.fetch_records(to_fetch, batch_size=batch_size):
        cache.upsert_paper(
            paper.pmid,
            pub_date=paper.pub_date,
            journal=paper.journal,
            title=paper.title,
            abstract=paper.abstract,
            raw=paper.raw,
        )
        fetched += 1
    return CorpusReport(
        query=query, found=len(pmids), fetched=fetched, cached_total=cache.count_papers()
    )
