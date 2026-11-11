"""Reads a run's process data (exported from the bioreactor / lab sheet).

Accepted format — "long" CSV, one value per row (comma or semicolon separated, decimal point or comma):

    day,parameter,value,unit
    0,pH,7.21,
    0,glucose,3.9,g/L
"""

import csv
import io
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessValue:
    day: int
    parameter: str
    value: float
    unit: str | None


class ProcessCsvError(ValueError):
    pass


def parse_process_csv(text: str) -> list[ProcessValue]:
    text = text.lstrip("﻿")
    sample = text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None:
        raise ProcessCsvError("empty file")
    fields = {f.strip().lower(): f for f in reader.fieldnames}
    missing = {"day", "parameter", "value"} - fields.keys()
    if missing:
        raise ProcessCsvError(f"missing column(s): {', '.join(sorted(missing))}")

    values: dict[tuple[int, str], ProcessValue] = {}
    for line_no, row in enumerate(reader, start=2):
        raw_day = (row[fields["day"]] or "").strip()
        raw_value = (row[fields["value"]] or "").strip().replace(",", ".")
        parameter = (row[fields["parameter"]] or "").strip()
        if not raw_day and not parameter and not raw_value:
            continue  # blank line
        try:
            day, value = int(raw_day), float(raw_value)
        except ValueError as exc:
            raise ProcessCsvError(f"line {line_no}: cannot read day/value ({raw_day!r}, {raw_value!r})") from exc
        if not parameter:
            raise ProcessCsvError(f"line {line_no}: parameter is empty")
        unit = None
        if "unit" in fields:
            unit = (row.get(fields["unit"]) or "").strip() or None
        values[(day, parameter)] = ProcessValue(day, parameter, value, unit)  # last row wins
    return list(values.values())
