"""Official source adapters. Upstream failures are errors, never empty success."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping
import xml.etree.ElementTree as ET

import httpx


class SourceError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.status, self.retryable = code, message, status, retryable


@dataclass(frozen=True)
class SourceQuery:
    query: str
    limit: int = 100
    cursor: str | None = None
    since: str | None = None
    until: str | None = None


@dataclass
class SourceEnvelope:
    source: str
    external_id: str
    raw_payload: Any
    normalized: dict[str, Any]
    source_updated: Any
    fetched_at: str
    content_hash: str
    observation_seq: int | None = None
    request_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourcePage:
    source: str
    items: list[SourceEnvelope]
    next_cursor: str | None
    coverage: dict[str, Any] = field(default_factory=dict)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def date_value(value: Any, *, kind: str = "source_reported") -> dict[str, Any]:
    """Preserve source precision; do not invent a day for a month/year."""
    if isinstance(value, Mapping):
        if "precision" in value:
            return dict(value)
        value = value.get("date") or value.get("value")
    value = str(value or "").strip()
    if re.fullmatch(r"\d{4}(-\d{2}){0,2}", value):
        return {"value": value, "precision": {4: "year", 7: "month", 10: "day"}[len(value)], "kind": kind}
    # ESummary returns dates such as '2024 Jan 9' or '2024 Jan'.
    for fmt, precision in [("%Y %b %d", "day"), ("%Y %b", "month"), ("%Y/%m/%d %H:%M", "day")]:
        try:
            d = datetime.strptime(value, fmt)
            return {"value": d.strftime("%Y-%m-%d" if precision == "day" else "%Y-%m"), "precision": precision, "kind": kind}
        except ValueError:
            pass
    return {"value": None, "precision": "unknown", "kind": "unknown"}


class _HTTPSource:
    source = ""
    # Share per-source rate limits across adapter instances in the same worker.
    _limits: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    def __init__(self, *, client: httpx.AsyncClient | None = None, timeout: float | None = None, retries: int | None = None, min_interval: float | None = None, max_attempts: int | None = None):
        self.timeout = float(timeout if timeout is not None else os.getenv("PHARMA_SOURCE_TIMEOUT", "30"))
        self.retries = max(0, int(max_attempts) - 1) if max_attempts is not None else max(0, int(os.getenv("PHARMA_SOURCE_RETRIES", "2")) if retries is None else retries)
        self.min_interval = max(0., float(min_interval if min_interval is not None else os.getenv("PHARMA_SOURCE_MIN_INTERVAL", "1" if self.source == "ctgov" else ".5")))
        self._client, self._owned_client = client, None

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        client = self._client or self._owned_client
        if client is None:
            self._owned_client = client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": "PharmaScope/1.0 (source metadata synchronization)"})
        loop = asyncio.get_running_loop()
        limits = self._limits.setdefault(loop, {})
        limiter = limits.setdefault(self.source, {"lock": asyncio.Lock(), "next": 0.})
        deadline = loop.time() + self.timeout
        for attempt in range(self.retries + 1):
            try:
                async with limiter["lock"]:
                    wait = max(0., limiter["next"] - loop.time()) if self.min_interval else 0.
                    if wait >= deadline - loop.time():
                        raise SourceError("timeout", "Source rate-limit wait exceeds request deadline", retryable=True)
                    if wait:
                        await asyncio.sleep(wait)
                    limiter["next"] = loop.time() + self.min_interval
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise SourceError("timeout", "Source request deadline exhausted", retryable=True)
                # Stream and cap decompressed bytes; never allocate unbounded
                # snapshots from an upstream payload or HTML error page.
                async with asyncio.timeout(remaining):
                    async with client.stream(method, url, timeout=remaining, **kwargs) as response:
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 8 * 1024 * 1024:
                                raise SourceError("SOURCE_PAYLOAD_TOO_LARGE", "Source response exceeds 8 MiB")
                        decoded_headers = {k: v for k, v in response.headers.items() if k.lower() not in {'content-encoding', 'content-length'}}
                        r = httpx.Response(response.status_code, headers=decoded_headers, content=bytes(data), request=response.request)
            except (httpx.RequestError, TimeoutError) as exc:
                error = SourceError("timeout" if isinstance(exc, (httpx.TimeoutException, TimeoutError)) else "unavailable", f"Source transport failed ({type(exc).__name__})", retryable=True)
                delay = .5 * 2 ** attempt
            else:
                if r.status_code < 400:
                    return r
                code = {401: "auth", 403: "auth", 404: "not_found", 429: "rate_limited"}.get(r.status_code, "unavailable" if r.status_code >= 500 else "invalid_request")
                error = SourceError(code, f"Source returned HTTP {r.status_code}", status=r.status_code, retryable=r.status_code == 429 or r.status_code >= 500)
                delay = .5 * 2 ** attempt + random.random() / 10
                if r.headers.get("retry-after"):
                    try:
                        delay = max(delay, float(r.headers["retry-after"]))
                    except ValueError:
                        try:
                            delay = max(delay, (parsedate_to_datetime(r.headers["retry-after"]) - datetime.now(timezone.utc)).total_seconds())
                        except (TypeError, ValueError):
                            pass
            if not error.retryable or attempt >= self.retries or delay >= deadline - loop.time():
                raise error
            await asyncio.sleep(delay)
        raise SourceError("unavailable", "Source retry budget exhausted")

    async def aclose(self) -> None:
        if self._owned_client:
            await self._owned_client.aclose()
            self._owned_client = None

    async def health(self) -> dict[str, Any]:
        try:
            await self.search(SourceQuery("cancer", limit=1))
            return {"source": self.source, "configured": True, "state": "healthy", "last_error_code": None}
        except SourceError as exc:
            return {"source": self.source, "configured": exc.code != "configuration", "state": "unavailable", "last_error_code": exc.code}


class ClinicalTrialsGovAdapter(_HTTPSource):
    source = "ctgov"
    base_url = "https://clinicaltrials.gov/api/v2"

    def __init__(self, *, base_url: str | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.base_url = (base_url or os.getenv("CTGOV_API_BASE_URL") or os.getenv("CLINICALTRIALS_BASE_URL") or self.base_url).rstrip("/")

    @staticmethod
    def normalize(payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            p = payload["protocolSection"]
            ident, status, conditions, design = (p.get(k) or {} for k in ("identificationModule", "statusModule", "conditionsModule", "designModule"))
            if not re.fullmatch(r"NCT\d{8}", str(ident.get("nctId", ""))):
                raise ValueError("invalid NCT ID")
            enrollment = design.get("enrollmentInfo") or {}
            raw_status = status.get("overallStatus")
            valid_status = {"NOT_YET_RECRUITING", "RECRUITING", "ENROLLING_BY_INVITATION", "ACTIVE_NOT_RECRUITING", "SUSPENDED", "TERMINATED", "COMPLETED", "WITHDRAWN", "UNKNOWN"}
            return {"title": ident.get("briefTitle") or ident.get("officialTitle") or "", "status": raw_status if raw_status in valid_status else "OTHER" if raw_status else "UNKNOWN", "raw_status": raw_status,
                    "source_updated": date_value(status.get("lastUpdatePostDateStruct")), "conditions": conditions.get("conditions", []), "phases": design.get("phases", []),
                    "enrollment": {"count": enrollment["count"], "type": str(enrollment.get("type", "unknown")).lower() if str(enrollment.get("type", "unknown")).lower() in {"estimated", "actual"} else "unknown"} if isinstance(enrollment.get("count"), int) else None,
                    "sponsor": ((p.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name"),
                    "primary_outcomes": [{"measure": x.get("measure", ""), "description": x.get("description"), "time_frame": x.get("timeFrame")} for x in (p.get("outcomesModule") or {}).get("primaryOutcomes", [])],
                    "has_results": payload.get("hasResults")}
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise SourceError("schema_changed", "ClinicalTrials.gov study response is invalid") from exc

    def _envelope(self, payload: Mapping[str, Any]) -> SourceEnvelope:
        normalized = self.normalize(payload)
        eid = payload["protocolSection"]["identificationModule"]["nctId"]
        return SourceEnvelope(self.source, eid, dict(payload), normalized, normalized["source_updated"], _utc_now(), stable_hash(payload), request_meta={"adapter": "clinicaltrials.gov-v2"})

    async def fetch(self, external_id: str) -> SourceEnvelope:
        if not re.fullmatch(r"NCT\d{8}", external_id):
            raise SourceError("invalid_request", "external_id must match NCT########")
        r = await self._request("GET", f"{self.base_url}/studies/{external_id}", headers={"Accept": "application/json"})
        try:
            item = self._envelope(r.json())
        except ValueError as exc:
            raise SourceError("schema_changed", "ClinicalTrials.gov response was not JSON") from exc
        if item.external_id != external_id:
            raise SourceError("schema_changed", "ClinicalTrials.gov returned an unexpected record ID")
        return item

    async def search(self, query: SourceQuery) -> SourcePage:
        params: dict[str, Any] = {"query.term": query.query, "pageSize": min(max(query.limit, 1), 100), "format": "json"}
        if query.cursor:
            params["pageToken"] = query.cursor
        if query.since or query.until:
            params["filter.advanced"] = f"AREA[LastUpdatePostDate]RANGE[{(query.since or 'MIN')[:10]},{(query.until or 'MAX')[:10]}]"
        r = await self._request("GET", f"{self.base_url}/studies", params=params, headers={"Accept": "application/json"})
        try:
            body = r.json()
            if not isinstance(body.get("studies"), list):
                raise ValueError("missing studies")
            items = [self._envelope(x) for x in body["studies"]]
        except (ValueError, TypeError, AttributeError) as exc:
            raise SourceError("schema_changed", "ClinicalTrials.gov search response is invalid") from exc
        return SourcePage(self.source, items, body.get("nextPageToken"), {"returned": len(items), "truncated": bool(body.get("nextPageToken"))})


class PubMedAdapter(_HTTPSource):
    source = "pubmed"
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, *, api_key: str | None = None, email: str | None = None, base_url: str | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.base_url = (base_url or os.getenv("PUBMED_API_BASE_URL") or os.getenv("PUBMED_BASE_URL") or self.base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("NCBI_API_KEY")
        self.email = email if email is not None else os.getenv("NCBI_EMAIL")
        if not self.email and os.getenv("PHARMA_RUNTIME_MODE", "live") in {"live", "gptr"}:
            raise SourceError("configuration", "NCBI_EMAIL is required in live mode; NCBI_API_KEY is optional")

    def _params(self, **params: Any) -> dict[str, Any]:
        result = {"db": "pubmed", "retmode": "json", "tool": "pharmascope", **params}
        if self.api_key:
            result["api_key"] = self.api_key
        if self.email:
            result["email"] = self.email
        return result

    @staticmethod
    def normalize(payload: Mapping[str, Any], *, pmid: str | None = None) -> dict[str, Any]:
        article = payload.get("result", {}).get(pmid or "") if "result" in payload else payload
        if not isinstance(article, Mapping) or article.get("error"):
            raise SourceError("schema_changed", "PubMed response has no valid article")
        eid = str(pmid or article.get("uid") or article.get("pmid") or "")
        if not eid.isdigit():
            raise SourceError("schema_changed", "PubMed response has no PMID")
        doi = next((x.get("value") for x in article.get("articleids", []) if x.get("idtype") == "doi"), article.get("doi"))
        return {"pmid": eid, "doi": doi, "title": article.get("title") or "", "abstract_text": article.get("abstracttext") or article.get("abstract"),
                "authors": [x.get("name", "") if isinstance(x, dict) else str(x) for x in article.get("authors", [])], "journal": article.get("fulljournalname") or article.get("source"),
                "publication_date": date_value(article.get("pubdate")), "publication_types": article.get("pubtype", []), "correction_relations": []}

    @staticmethod
    def _xml_article(article: ET.Element) -> tuple[str, dict[str, Any], dict[str, Any]]:
        eid = article.findtext("./MedlineCitation/PMID")
        if not eid or not eid.isdigit():
            raise SourceError("schema_changed", "PubMed EFetch article has no PMID")
        def text(path: str) -> str:
            node = article.find(path)
            return "".join(node.itertext()).strip() if node is not None else ""
        def date(path: str) -> dict[str, Any]:
            node = article.find(path)
            if node is None:
                return date_value(None)
            year, month, day = node.findtext("Year"), node.findtext("Month"), node.findtext("Day")
            if year:
                if month and not month.isdigit():
                    try:
                        month = str(datetime.strptime(month[:3], "%b").month)
                    except ValueError:
                        month = None
                return date_value(year + ("-" + month.zfill(2) if month else "") + ("-" + day.zfill(2) if month and day else ""))
            return date_value(node.findtext("MedlineDate"))
        normalized = {"pmid": eid, "title": text(".//ArticleTitle"), "doi": next((x.text for x in article.findall(".//ArticleId") if x.attrib.get("IdType") == "doi"), None),
                      "abstract_text": "\n".join(((x.get("Label") + ": ") if x.get("Label") else "") + "".join(x.itertext()) for x in article.findall(".//AbstractText")) or None,
                      "authors": [" ".join(filter(None, [x.findtext("LastName"), x.findtext("ForeName")])) or x.findtext("CollectiveName", "") for x in article.findall(".//Author")],
                      "journal": text(".//Journal/Title") or None, "publication_date": date(".//JournalIssue/PubDate"),
                      "publication_types": ["".join(x.itertext()) for x in article.findall(".//PublicationType")],
                      "correction_relations": [{"relation": x.get("RefType", "unknown"), "external_id": x.findtext("PMID")} for x in article.findall(".//CommentsCorrections") if x.findtext("PMID")]}
        return eid, normalized, date("./MedlineCitation/DateRevised")

    async def _fetch_many(self, ids: list[str]) -> list[SourceEnvelope]:
        r = await self._request("GET", f"{self.base_url}/efetch.fcgi", params=self._params(id=",".join(ids), rettype="abstract", retmode="xml"))
        try:
            root = ET.fromstring(r.content)
            if root.find(".//ERROR") is not None:
                raise ValueError("EUtilities error")
            result = {}
            for article in root.findall(".//PubmedArticle"):
                eid, normalized, updated = self._xml_article(article)
                raw = {"format": "xml", "article": ET.tostring(article, encoding="unicode")}
                result[eid] = SourceEnvelope(self.source, eid, raw, normalized, updated, _utc_now(), stable_hash(raw), request_meta={"adapter": "ncbi-eutils", "format": "xml"})
            if set(ids) - result.keys():
                raise ValueError("requested article missing")
            return [result[eid] for eid in ids]
        except (ValueError, ET.ParseError) as exc:
            raise SourceError("schema_changed", "PubMed EFetch response is invalid or missing requested articles") from exc

    async def search(self, query: SourceQuery) -> SourcePage:
        try:
            start = int(query.cursor or 0)
        except ValueError as exc:
            raise SourceError("invalid_request", "PubMed cursor must be an integer offset") from exc
        if start < 0 or start >= 9999:
            raise SourceError("invalid_request", "PubMed ESearch offset must be between 0 and 9998")
        params = self._params(term=query.query, retmax=min(max(query.limit, 1), 100, 9999-start), usehistory="n", retstart=start)
        if query.since or query.until:
            params.update(mindate=(query.since or "1000")[:10].replace("-", "/"), maxdate=(query.until or "3000")[:10].replace("-", "/"), datetype="pdat")
        r = await self._request("GET", f"{self.base_url}/esearch.fcgi", params=params)
        try:
            payload = r.json()
            body = payload["esearchresult"]
            if payload.get("error") or body.get("errorlist") or not isinstance(body.get("idlist"), list):
                raise ValueError("EUtilities returned error")
            ids, count = [str(x) for x in body["idlist"]], int(body["count"])
            if any(not x.isdigit() for x in ids) or (count > start and not ids):
                raise ValueError("inconsistent result count")
        except (KeyError, ValueError, TypeError) as exc:
            raise SourceError("schema_changed", "PubMed ESearch response is invalid") from exc
        items = await self._fetch_many(ids) if ids else []
        nxt = str(start + len(ids)) if start + len(ids) < min(count, 9999) else None
        return SourcePage(self.source, items, nxt, {"returned": len(items), "count": count, "truncated": start + len(ids) < count, "search_limit": 9999})

    async def fetch(self, external_id: str) -> SourceEnvelope:
        if not external_id.isdigit():
            raise SourceError("invalid_request", "PubMed external_id must be a PMID")
        return (await self._fetch_many([external_id]))[0]


def adapter_for(source: str, **kwargs: Any) -> _HTTPSource:
    if source in ("ctgov", "clinicaltrials_gov"):
        return ClinicalTrialsGovAdapter(**kwargs)
    if source == "pubmed":
        return PubMedAdapter(**kwargs)
    raise ValueError(f"unsupported source: {source}")

ClinicalTrialsAdapter = ClinicalTrialsGovAdapter
