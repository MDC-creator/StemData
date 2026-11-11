import pytest

from stemchub.process_csv import ProcessCsvError, ProcessValue, parse_process_csv


def test_comma_separated():
    text = "day,parameter,value,unit\n0,pH,7.21,\n0,glucose,3.9,g/L\n-2,glucose,4.5,g/L\n"
    assert parse_process_csv(text) == [
        ProcessValue(0, "pH", 7.21, None),
        ProcessValue(0, "glucose", 3.9, "g/L"),
        ProcessValue(-2, "glucose", 4.5, "g/L"),
    ]


def test_german_excel_export_with_bom_semicolons_and_decimal_comma():
    text = "﻿Day;Parameter;Value;Unit\r\n1;lactate;0,85;g/L\r\n\r\n"
    assert parse_process_csv(text) == [ProcessValue(1, "lactate", 0.85, "g/L")]


def test_unit_column_is_optional_and_last_duplicate_wins():
    text = "day,parameter,value\n3,pH,7.1\n3,pH,7.2\n"
    assert parse_process_csv(text) == [ProcessValue(3, "pH", 7.2, None)]


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "empty"),
        ("day,value\n1,2\n", "parameter"),
        ("day,parameter,value\nx,pH,7\n", "line 2"),
        ("day,parameter,value\n1,,7\n", "parameter is empty"),
    ],
)
def test_errors_are_explained(text, message):
    with pytest.raises(ProcessCsvError, match=message):
        parse_process_csv(text)
