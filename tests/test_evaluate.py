import csv

from extractor.evaluate import evaluate
from extractor.output import COLUMNS


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def result(file, subject="", subject_verified="", page_count="1", review="no"):
    base = {c: "" for c in COLUMNS}
    base.update(file=file, page="1", release_date="1970-11-02", first_five_words="Day-long public symposium on",
               date_verified="YES", words_verified="YES", needs_review=review, subject=subject,
               subject_verified=subject_verified, page_count=page_count)
    return base


def test_subject_and_page_count_are_scored_when_the_key_has_them(tmp_path, capsys):
    write(tmp_path / "r.csv", COLUMNS, [
        result("a.pdf", "TVR Transportation", "YES", "2"),
        result("b.pdf", "Susan Wolf - Co-op", "YES"),       # verified but wrong
        result("c.pdf", "", "NO", review="YES"),            # no subject given
    ])
    write(tmp_path / "t.csv", ["file", "release_date", "first_five_words", "subject", "page_count"], [
        {"file": "a.pdf", "release_date": "1970-11-02", "first_five_words": "Day-long public symposium on",
         "subject": "TVR Transportation", "page_count": "2"},
        {"file": "b.pdf", "release_date": "1970-11-02", "first_five_words": "Day-long public symposium on",
         "subject": "Susan Wolfe - Co-op", "page_count": "1"},
        {"file": "c.pdf", "release_date": "1970-11-02", "first_five_words": "Day-long public symposium on",
         "subject": "John Ward - Co-op", "page_count": "1"},
    ])
    assert evaluate(tmp_path / "r.csv", tmp_path / "t.csv") == 1  # a verified subject is wrong
    out = capsys.readouterr().out
    assert "subject (3 checked)" in out and "page_count (3 checked)" in out
    subject_block = out.split("subject (3 checked)")[1].split("page_count")[0]
    assert "VERIFIED BUT WRONG (must be 0)" in subject_block and "b.pdf" in subject_block
    assert "no answer from tool" in subject_block


def test_keys_without_subject_columns_still_work(tmp_path, capsys):
    write(tmp_path / "r.csv", COLUMNS, [result("a.pdf")])
    write(tmp_path / "t.csv", ["file", "release_date", "first_five_words"],
          [{"file": "a.pdf", "release_date": "1970-11-02", "first_five_words": "Day-long public symposium on"}])
    assert evaluate(tmp_path / "r.csv", tmp_path / "t.csv") == 0
    assert "subject" not in capsys.readouterr().out


def test_template_has_subject_columns_only_for_list_page_results(tmp_path):
    from extractor.evaluate import make_template

    write(tmp_path / "r.csv", COLUMNS, [result("a.pdf"), result("a.pdf"), result("b.pdf")])
    make_template(tmp_path / "r.csv", tmp_path / "t.csv")
    assert list(csv.reader(open(tmp_path / "t.csv")))[0] == ["file", "release_date", "first_five_words", "subject", "page_count"]
    assert [r["file"] for r in read(tmp_path / "t.csv")] == ["a.pdf", "b.pdf"]
    old = COLUMNS[:13]  # a results file from before subjects existed
    write(tmp_path / "old.csv", old, [{c: "x" for c in old}])
    make_template(tmp_path / "old.csv", tmp_path / "t_old.csv")
    assert list(csv.reader(open(tmp_path / "t_old.csv")))[0] == ["file", "release_date", "first_five_words"]


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
