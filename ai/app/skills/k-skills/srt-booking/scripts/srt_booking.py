from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run SRT actions through SRTrain.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search")
    _add_route_args(search_parser)
    search_parser.add_argument("--limit", type=int, default=5)

    reserve_parser = subparsers.add_parser("reserve")
    _add_route_args(reserve_parser)
    reserve_parser.add_argument("--train-index", type=int, default=0)
    reserve_parser.add_argument("--adult-count", type=int, default=1)
    reserve_parser.add_argument(
        "--seat",
        choices=("general-first", "general-only", "special-first", "special-only"),
        default="general-first",
    )

    reservations_parser = subparsers.add_parser("reservations")
    reservations_parser.add_argument("--limit", type=int, default=20)

    cancel_parser = subparsers.add_parser("cancel")
    cancel_parser.add_argument("--reservation-index", type=int, required=True)

    args = parser.parse_args(argv)
    try:
        result = _run(args)
    except Exception as error:
        _emit(
            {
                "ok": False,
                "error": {
                    "code": _error_code(error),
                    "message": str(error),
                    "type": type(error).__name__,
                },
            }
        )
        return 1
    _emit({"ok": True, **result})
    return 0


def _add_route_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--departure", required=True)
    parser.add_argument("--arrival", required=True)
    parser.add_argument("--date", required=True, help="YYYYMMDD")
    parser.add_argument("--time", required=True, help="HHMMSS")
    parser.add_argument("--time-limit", default=None, help="Optional HHMMSS search upper bound.")


def _run(args: argparse.Namespace) -> dict[str, Any]:
    srt_module = _load_srt_module()
    srt = srt_module.SRT(_required_env("KSKILL_SRT_ID"), _required_env("KSKILL_SRT_PASSWORD"))

    if args.command == "search":
        trains = _search(srt, args)
        return {
            "command": "search",
            "count": len(trains),
            "trains": [_serialize(item) for item in trains[: max(args.limit, 0)]],
        }
    if args.command == "reserve":
        return _reserve(srt, args, adult_factory=srt_module.Adult, seat_type=srt_module.SeatType)
    if args.command == "reservations":
        reservations = list(srt.get_reservations())
        return {
            "command": "reservations",
            "count": len(reservations),
            "reservations": [_serialize(item) for item in reservations[: max(args.limit, 0)]],
        }
    if args.command == "cancel":
        reservations = list(srt.get_reservations())
        if args.reservation_index < 0 or args.reservation_index >= len(reservations):
            raise ValueError(f"reservation-index out of range: {args.reservation_index}")
        reservation = reservations[args.reservation_index]
        cancelled = srt.cancel(reservation)
        return {
            "command": "cancel",
            "cancelled": bool(cancelled) if cancelled is not None else True,
            "reservation": _serialize(reservation),
        }
    raise ValueError(f"unsupported command: {args.command}")


def _reserve(srt: Any, args: argparse.Namespace, *, adult_factory: Any, seat_type: Any) -> dict[str, Any]:
    # Reserve against the same ordered list exposed by search, including sold-out rows.
    # This keeps --train-index stable between "search" and "reserve"; selecting a sold-out
    # row should fail instead of silently shifting to a different available train.
    trains = _search(srt, args, available_only=False)
    if args.train_index < 0 or args.train_index >= len(trains):
        raise ValueError(f"train-index out of range: {args.train_index}")
    selected = trains[args.train_index]
    reservation = srt.reserve(
        selected,
        passengers=[adult_factory(max(args.adult_count, 1))],
        special_seat=_seat_type(seat_type, args.seat),
    )
    return {
        "command": "reserve",
        "train": _serialize(selected),
        "reservation": _serialize(reservation),
    }


def _search(srt: Any, args: argparse.Namespace, *, available_only: bool | None = None) -> list[Any]:
    kwargs: dict[str, Any] = {"available_only": args.command != "search" if available_only is None else available_only}
    if args.time_limit:
        kwargs["time_limit"] = args.time_limit
    return list(srt.search_train(args.departure, args.arrival, args.date, args.time, **kwargs))


def _load_srt_module() -> Any:
    try:
        import SRT  # type: ignore
    except ImportError as error:
        raise RuntimeError("SRTrain is not installed. Run: python -m pip install SRTrain") from error
    return SRT


def _seat_type(seat_type: Any, value: str) -> Any:
    mapping = {
        "general-first": "GENERAL_FIRST",
        "general-only": "GENERAL_ONLY",
        "special-first": "SPECIAL_FIRST",
        "special-only": "SPECIAL_ONLY",
    }
    return getattr(seat_type, mapping[value])


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _serialize(value: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"text": str(value)}
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        for key, attr_value in attrs.items():
            if _is_sensitive_key(str(key)):
                continue
            payload[str(key)] = _json_safe(attr_value)
    return payload


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if not _is_sensitive_key(str(key))
        }
    return str(value)


def _is_sensitive_key(key: str) -> bool:
    return any(token in key.lower() for token in ("password", "passwd", "token", "secret", "credential"))


def _error_code(error: Exception) -> str:
    text = str(error).lower()
    if "missing required environment variable" in text:
        return "missing_credentials"
    if "srtrain is not installed" in text:
        return "missing_dependency"
    if isinstance(error, ValueError):
        return "invalid_arguments"
    return "srt_action_failed"


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
