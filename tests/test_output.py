import csv
import os
import stat
from dataclasses import fields

from extractor.listpage import ListEntry
from extractor.output import COLUMNS, append_rows, merge_rows, write_unmatched
from extractor.pipeline import Row

import datetime as dt

OLD_COLUMNS = [f.name for f in fields(Row)][:13]


def mk(file, page=1, folder="", subject="", date="1970-11-02") -> Row:
    return Row(file, page, "", date, "", "Words here now please", "YES", "YES", "95", "95", "en", "no", "",
               subject=subject, folder=folder)


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_old_csv_is_migrated_not_rejected(tmp_path):
    path = tmp_path / "r.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(OLD_COLUMNS)
        w.writerow(["0001.jpg", 1, "1", "1969-01-09", "January 9, 1969", "Words here now please", "YES", "YES",
                    "95", "95", "en", "no", ""])
    append_rows(path, [mk("0002.jpg")])
    rows = read(path)
    assert list(rows[0]) == COLUMNS and [r["file"] for r in rows] == ["0001.jpg", "0002.jpg"]
    assert rows[0]["subject"] == "" and rows[0]["release_date"] == "1969-01-09"


def test_unknown_columns_are_still_refused(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("a,b\n1,2\n")
    try:
        append_rows(path, [mk("x.jpg")])
    except ValueError as e:
        assert "different columns" in str(e)
    else:
        raise AssertionError("expected a refusal")


def test_merge_replaces_the_folders_pages_and_keeps_the_rest(tmp_path):
    path = tmp_path / "r.csv"
    append_rows(path, [mk("a.pdf", folder="f1"), mk("a.pdf", 2, folder="f1"), mk("a.pdf", folder="f2"),
                       mk("b.pdf", folder="f1")])
    merge_rows(path, [mk("a.pdf", folder="f1", subject="New")], {("a.pdf", 1), ("a.pdf", 2)}, "f1")
    got = [(r["folder"], r["file"], r["page"], r["subject"]) for r in read(path)]
    assert got == [("f2", "a.pdf", "1", ""), ("f1", "b.pdf", "1", ""), ("f1", "a.pdf", "1", "New")]


def test_legacy_rows_without_a_folder_are_replaced_by_the_same_page(tmp_path):
    path = tmp_path / "r.csv"
    append_rows(path, [mk("a.pdf"), mk("z.pdf")])
    merge_rows(path, [mk("a.pdf", folder="f1", subject="S")], {("a.pdf", 1)}, "f1")
    assert [(r["file"], r["subject"]) for r in read(path)] == [("z.pdf", ""), ("a.pdf", "S")]


def test_merge_creates_the_file_privately_and_keeps_it_private(tmp_path):
    path = tmp_path / "sub" / "r.csv"
    merge_rows(path, [mk("a.pdf", folder="f1")], {("a.pdf", 1)}, "f1")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    os.chmod(path, 0o644)
    merge_rows(path, [mk("b.pdf", folder="f1")], {("b.pdf", 1)}, "f1")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir()] == ["r.csv"]  # no temp file left behind


def test_formula_like_text_is_neutralised(tmp_path):
    path = tmp_path / "r.csv"
    merge_rows(path, [mk("a.pdf", folder="f1", subject="=SUM(A1)")], {("a.pdf", 1)}, "f1")
    assert read(path)[0]["subject"] == "'=SUM(A1)"


def test_unmatched_report_is_replaced_per_folder(tmp_path):
    path = tmp_path / "u.csv"
    e = lambda s, d: ListEntry(dt.date(1970, 11, d), s, "", 90.0, 0, 0, ["month read as 'Now'; taken as Nov"])  # noqa: E731
    write_unmatched(path, "f1", [e("Football", 3), e("Soccer", 4)])
    write_unmatched(path, "f2", [e("Tennis", 5)])
    write_unmatched(path, "f1", [e("Rowing", 6)])
    assert [(r["folder"], r["list_date"], r["subject"]) for r in read(path)] == [
        ("f2", "1970-11-05", "Tennis"), ("f1", "1970-11-06", "Rowing")]
    write_unmatched(path, "f1", [])
    assert [r["folder"] for r in read(path)] == ["f2"]
