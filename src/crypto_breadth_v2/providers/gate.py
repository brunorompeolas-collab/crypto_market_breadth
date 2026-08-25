"""Gate-only native 4h/1d adapter with explicit frozen mappings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import socket
from time import sleep as default_sleep
import random
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..candles import CanonicalCandle, CandleContractError, validate_candle
from ..contracts import ContractBundle
from ..timeframes import Timeframe, close_time, duration


GATE_BASE_URL = "https://api.gateio.ws/api/v4"
GATE_SOURCE_ID = "gate-spot-usdt"
GATE_MAX_CANDLES = 1000
UTC = timezone.utc


class GateError(RuntimeError):
    pass


class GateMappingError(GateError):
    pass


class GateSchemaError(GateError):
    pass


class GateCandleValidationError(GateError):
    pass


class GateInstrumentUnavailableError(GateError):
    pass


class GatePayloadConflictError(GateError):
    pass


class GateTimeoutError(GateError):
    pass


class GateRateLimitError(GateError):
    def __init__(self, retry_after: float | None) -> None:
        self.retry_after = retry_after
        super().__init__(f"Gate rate limit exhausted; Retry-After={retry_after}")


class GateServerError(GateError):
    pass


class GateCatalogueMismatch(GateError):
    def __init__(self, mismatches: Sequence[str]) -> None:
        self.mismatches = tuple(mismatches)
        super().__init__("Gate catalogue mismatch: " + "; ".join(self.mismatches))


@dataclass(frozen=True)
class GateMapping:
    canonical_id: str
    symbol: str
    instrument: str
    quote: str


@dataclass(frozen=True)
class GateCandleEnvelope:
    mapping: GateMapping
    candle: CanonicalCandle
    source_payload_hash: str
    raw_payload: tuple[str, ...]


@dataclass(frozen=True)
class GateHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class GateRetryPolicy:
    max_attempts: int = 3
    default_retry_seconds: float = 1.0
    max_retry_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.default_retry_seconds < 0:
            raise ValueError("default_retry_seconds must be non-negative")
        if self.max_retry_seconds < self.default_retry_seconds:
            raise ValueError("max_retry_seconds must be >= default_retry_seconds")

    def delay(self, attempt: int, *, random_value: float | None = None) -> float:
        """Full-jitter bounded exponential delay for retryable failures.

        ``random_value`` is injectable for deterministic tests. Retry-After is
        handled separately because it is an explicit server directive.
        """
        if attempt < 1:
            raise ValueError("attempt must be positive")
        cap = min(self.max_retry_seconds, self.default_retry_seconds * (2 ** (attempt - 1)))
        value = random.random() if random_value is None else random_value
        return max(0.0, min(1.0, value)) * cap


@dataclass
class GateRequestStats:
    """Mutable request counters used only for auditable bootstrap evidence."""

    http_calls: int = 0
    retries: int = 0
    rate_limits: int = 0
    server_errors: int = 0
    timeouts: int = 0
    client_errors: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "http_calls": self.http_calls,
            "retries": self.retries,
            "rate_limits": self.rate_limits,
            "server_errors": self.server_errors,
            "timeouts": self.timeouts,
            "client_errors": self.client_errors,
        }


class GateTransport(Protocol):
    def get(self, url: str, *, params: Mapping[str, Any], timeout: float) -> GateHttpResponse: ...


class UrllibGateTransport:
    """Minimal read-only transport; all behavior is tested through injected fakes."""

    def get(self, url: str, *, params: Mapping[str, Any], timeout: float) -> GateHttpResponse:
        query = urlencode({key: value for key, value in params.items() if value is not None})
        request = Request(
            f"{url}?{query}" if query else url,
            headers={"Accept": "application/json", "User-Agent": "crypto-breadth-v2/1"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return GateHttpResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except HTTPError as exc:
            return GateHttpResponse(
                status=exc.code,
                headers=dict(exc.headers.items()) if exc.headers else {},
                body=exc.read(),
            )


def load_gate_mappings(bundle: ContractBundle) -> dict[str, GateMapping]:
    universe = bundle.definition("universe")
    source_policy = bundle.definition("source_policy")
    by_symbol = {member["symbol"]: member for member in universe["members"]}
    result: dict[str, GateMapping] = {}
    for symbol, row in source_policy["mappings"].items():
        if row.get("source") != "gate_spot":
            raise GateMappingError(f"Non-Gate mapping is forbidden in Gate adapter: {symbol}")
        member = by_symbol[symbol]
        result[symbol] = GateMapping(
            canonical_id=member["id"],
            symbol=symbol,
            instrument=row["instrument"],
            quote=row["quote"],
        )
    return result


def verify_gate_catalogue(
    mappings: Mapping[str, GateMapping], catalogue: Sequence[Mapping[str, Any]]
) -> tuple[str, ...]:
    """Require exact configured IDs; never infer or substitute an instrument."""
    by_id = {row.get("id"): row for row in catalogue if isinstance(row, Mapping)}
    mismatches: list[str] = []
    for symbol, mapping in mappings.items():
        row = by_id.get(mapping.instrument)
        if row is None:
            mismatches.append(f"{symbol}:{mapping.instrument}:MISSING")
            continue
        expected_base = mapping.instrument.removesuffix(f"_{mapping.quote}")
        if row.get("base") != expected_base:
            mismatches.append(
                f"{symbol}:{mapping.instrument}:BASE={row.get('base')!r}!={expected_base!r}"
            )
        if row.get("quote") != mapping.quote:
            mismatches.append(
                f"{symbol}:{mapping.instrument}:QUOTE={row.get('quote')!r}!={mapping.quote!r}"
            )
        if row.get("trade_status") != "tradable":
            mismatches.append(
                f"{symbol}:{mapping.instrument}:STATUS={row.get('trade_status')!r}"
            )
        if row.get("delisting_time") not in {None, "", 0, "0"}:
            mismatches.append(
                f"{symbol}:{mapping.instrument}:DELISTING={row.get('delisting_time')!r}"
            )
    if mismatches:
        raise GateCatalogueMismatch(mismatches)
    return tuple(sorted(mapping.instrument for mapping in mappings.values()))


class GateClient:
    def __init__(
        self,
        mappings: Mapping[str, GateMapping],
        *,
        transport: GateTransport | None = None,
        retry_policy: GateRetryPolicy = GateRetryPolicy(),
        timeout_seconds: float = 10.0,
        sleep: Callable[[float], None] = default_sleep,
        base_url: str = GATE_BASE_URL,
        stats: GateRequestStats | None = None,
    ) -> None:
        self._mappings = dict(mappings)
        self._transport = transport or UrllibGateTransport()
        self._retry_policy = retry_policy
        self._timeout = timeout_seconds
        self._sleep = sleep
        self._base_url = base_url.rstrip("/")
        self.stats = stats or GateRequestStats()

    def _request_json(self, path: str, params: Mapping[str, Any]) -> Any:
        last_timeout: BaseException | None = None
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                self.stats.http_calls += 1
                response = self._transport.get(
                    f"{self._base_url}{path}", params=params, timeout=self._timeout
                )
            except (TimeoutError, socket.timeout, URLError) as exc:
                self.stats.timeouts += 1
                last_timeout = exc
                if attempt == self._retry_policy.max_attempts:
                    raise GateTimeoutError("Gate request timed out after retries") from exc
                self.stats.retries += 1
                self._sleep(self._retry_policy.delay(attempt))
                continue

            if response.status == 429:
                self.stats.rate_limits += 1
                raw_retry_after = next(
                    (
                        value
                        for key, value in response.headers.items()
                        if key.lower() == "retry-after"
                    ),
                    None,
                )
                try:
                    retry_after = float(raw_retry_after) if raw_retry_after is not None else None
                except ValueError:
                    retry_after = None
                if attempt == self._retry_policy.max_attempts:
                    raise GateRateLimitError(retry_after)
                self.stats.retries += 1
                self._sleep(
                    retry_after
                    if retry_after is not None
                    else self._retry_policy.delay(attempt)
                )
                continue

            if 500 <= response.status <= 599:
                self.stats.server_errors += 1
                if attempt == self._retry_policy.max_attempts:
                    raise GateServerError(f"Gate returned HTTP {response.status} after retries")
                self.stats.retries += 1
                self._sleep(self._retry_policy.delay(attempt))
                continue
            if response.status >= 400:
                self.stats.client_errors += 1
                try:
                    detail = response.body.decode("utf-8")[:500]
                except UnicodeDecodeError:
                    detail = "<non-UTF-8 body>"
                raise GateInstrumentUnavailableError(
                    f"Gate returned HTTP {response.status} for {path}: {detail}"
                )
            try:
                return json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GateSchemaError("Gate response is not valid UTF-8 JSON") from exc
        raise GateTimeoutError("Gate request failed") from last_timeout

    def list_currency_pairs(self) -> list[Mapping[str, Any]]:
        payload = self._request_json("/spot/currency_pairs", {})
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise GateSchemaError("Gate currency-pair catalogue must be a list of objects")
        return payload

    def verify_live_catalogue(self) -> tuple[str, ...]:
        return verify_gate_catalogue(self._mappings, self.list_currency_pairs())

    def _mapping(self, symbol: str) -> GateMapping:
        try:
            return self._mappings[symbol]
        except KeyError as exc:
            raise GateMappingError(f"No frozen Gate mapping for symbol {symbol!r}") from exc

    def _parse_row(
        self,
        row: Any,
        *,
        mapping: GateMapping,
        timeframe: Timeframe,
        as_of: datetime,
    ) -> GateCandleEnvelope:
        if not isinstance(row, list) or len(row) != 8 or any(
            not isinstance(value, str) for value in row
        ):
            raise GateSchemaError("Gate candle must be an eight-string array")
        timestamp, quote_volume, close, high, low, open_, base_volume, closed = row
        if closed not in {"true", "false"}:
            raise GateSchemaError("Gate candle completion flag must be 'true' or 'false'")
        try:
            open_time = datetime.fromtimestamp(int(timestamp), tz=UTC)
            parsed_open = Decimal(open_)
            parsed_high = Decimal(high)
            parsed_low = Decimal(low)
            parsed_close = Decimal(close)
            parsed_base_volume = Decimal(base_volume)
            parsed_quote_volume = Decimal(quote_volume)
        except (InvalidOperation, ValueError, OverflowError) as exc:
            raise GateSchemaError("Gate candle contains an invalid timestamp or decimal") from exc
        try:
            expected_close = close_time(open_time, timeframe)
        except ValueError as exc:
            raise GateCandleValidationError(str(exc)) from exc
        try:
            candle = CanonicalCandle(
                asset_id=mapping.canonical_id,
                timeframe=timeframe,
                open_time=open_time,
                close_time=expected_close,
                open=parsed_open,
                high=parsed_high,
                low=parsed_low,
                close=parsed_close,
                base_volume=parsed_base_volume,
                quote_volume=parsed_quote_volume,
                provider_complete=closed == "true",
            )
            validate_candle(candle, as_of=as_of)
        except (CandleContractError, ValueError) as exc:
            raise GateCandleValidationError(str(exc)) from exc
        raw_payload = tuple(row)
        payload_hash = sha256(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return GateCandleEnvelope(mapping, candle, payload_hash, raw_payload)

    def fetch_candles(
        self,
        symbol: str,
        *,
        timeframe: Timeframe,
        as_of: datetime,
        limit: int | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> tuple[GateCandleEnvelope, ...]:
        timeframe = Timeframe(timeframe)
        if timeframe not in {Timeframe.FOUR_HOUR, Timeframe.DAILY}:
            raise GateMappingError("Gate Slice 3 supports only native 4h and 1d candles")
        mapping = self._mapping(symbol)
        if limit is not None and (from_time is not None or to_time is not None):
            raise ValueError("Gate limit cannot be combined with from/to")
        if limit is not None and not 1 <= limit <= GATE_MAX_CANDLES:
            raise ValueError("Gate limit must be between 1 and 1000")
        params: dict[str, Any] = {
            "currency_pair": mapping.instrument,
            "interval": timeframe.value,
        }
        if limit is not None:
            params["limit"] = limit
        if from_time is not None:
            if from_time.tzinfo is None or from_time.utcoffset() != timedelta(0):
                raise ValueError("from_time must be UTC")
            params["from"] = int(from_time.timestamp())
        if to_time is not None:
            if to_time.tzinfo is None or to_time.utcoffset() != timedelta(0):
                raise ValueError("to_time must be UTC")
            params["to"] = int(to_time.timestamp())
        payload = self._request_json("/spot/candlesticks", params)
        if not isinstance(payload, list):
            raise GateSchemaError("Gate candle response must be a list")
        if not payload:
            raise GateInstrumentUnavailableError(
                f"Gate returned no candles for frozen instrument {mapping.instrument}"
            )
        payload_for_parse = payload
        if to_time is not None:
            # Gate treats ``to`` as inclusive. The canonical range contract is
            # [from, to), so remove the boundary row before completion checks;
            # it may be the provider's still-forming candle.
            payload_for_parse = []
            for row in payload:
                try:
                    row_open = datetime.fromtimestamp(int(row[0]), tz=UTC)
                except (IndexError, TypeError, ValueError):
                    payload_for_parse.append(row)
                    continue
                if row_open < to_time:
                    payload_for_parse.append(row)
        if not payload_for_parse:
            raise GateInstrumentUnavailableError(
                f"Gate returned no candles in the requested closed range for {mapping.instrument}"
            )
        parsed = tuple(
            self._parse_row(
                row, mapping=mapping, timeframe=timeframe, as_of=as_of
            )
            for row in payload_for_parse
        )
        return tuple(sorted(parsed, key=lambda item: item.candle.open_time))

    def fetch_range(
        self,
        symbol: str,
        *,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        as_of: datetime,
        allow_empty_pages: bool = False,
    ) -> tuple[GateCandleEnvelope, ...]:
        timeframe = Timeframe(timeframe)
        if end <= start:
            raise ValueError("Gate range end must be after start")
        # Gate treats both ``from`` and ``to`` as inclusive. A span of 1000
        # intervals therefore requests 1001 rows and is rejected with 400;
        # leave one interval of headroom and keep the canonical [from,to)
        # filtering below deterministic.
        page_span = duration(timeframe) * (GATE_MAX_CANDLES - 1)
        cursor = start
        by_open: dict[datetime, GateCandleEnvelope] = {}
        while cursor < end:
            page_end = min(end, cursor + page_span)
            try:
                rows = self.fetch_candles(
                    symbol,
                    timeframe=timeframe,
                    as_of=as_of,
                    from_time=cursor,
                    to_time=page_end,
                )
            except GateInstrumentUnavailableError:
                if not allow_empty_pages:
                    raise
                rows = ()
            for row in rows:
                if not start <= row.candle.open_time < end:
                    continue
                existing = by_open.get(row.candle.open_time)
                if existing and existing.source_payload_hash != row.source_payload_hash:
                    raise GatePayloadConflictError(
                        f"Conflicting paginated Gate candle at {row.candle.open_time.isoformat()}"
                    )
                by_open[row.candle.open_time] = row
            cursor = page_end
        return tuple(by_open[key] for key in sorted(by_open))
