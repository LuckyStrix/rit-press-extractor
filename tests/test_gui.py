"""The window's logic (command line, progress tracking), tested without opening a window."""
from pathlib import Path

from extractor.gui import RunState, build_command, default_jobs


def test_command_runs_the_process_command_with_the_chosen_folders():
    cmd = build_command(Path("/in/f1"), Path("/out/r.csv"), 3)
    assert cmd[1:4] == ["-m", "extractor", "process"]
    assert cmd[4:] == [str(Path("/in/f1")), "-o", str(Path("/out/r.csv")), "-j", "3"]


def test_jobs_default_is_sensible():
    assert 1 <= default_jobs() <= 4


def test_progress_follows_the_files_read():
    st = RunState(total_files=4)
    st.feed("  read 0001.png p1")
    st.feed("  read 0002.png p1")
    st.feed("  read 0002.png p2")  # a second page of the same file is not another file
    assert st.fraction == 0.5 and "0002.png" in st.status


def test_results_are_counted_and_summaries_kept():
    st = RunState(total_files=2)
    for line in ["  read a.png p1", "  read b.png p1",
                 "  [ok    ] a.png p1: 1970-11-02 | Day-long public | TVR Transportation",
                 "  [REVIEW] b.png p1: 1970-11-03 | - | ",
                 "  f1: 1 list page(s), 3 entries; 2 releases: 1 with a subject, 0 undecided, 1 without; 2 entries matched no release",
                 "Done. 1 item(s) need review. Results saved to /out/r.csv"]:
        st.feed(line)
    assert (st.releases, st.review, st.done) == (2, 1, True)
    assert st.fraction == 1.0 and "1 need review" in st.status
    assert any("list page" in n for n in st.notes)


def test_an_error_is_surfaced_not_swallowed():
    st = RunState(total_files=1)
    st.feed("Traceback (most recent call last):")
    st.feed("RuntimeError: boom")
    st.finish(returncode=1)
    assert st.failed and "boom" in st.status


def test_cancel_is_reported_as_stopped():
    st = RunState(total_files=1)
    st.finish(returncode=-15, cancelled=True)
    assert not st.failed and "stopped" in st.status.lower()
