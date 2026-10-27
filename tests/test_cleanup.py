import datetime

from reels_autopublish import cleanup


def make_day(cfg, stamp):
    day = cfg.output_dir / stamp
    (day / "videos").mkdir(parents=True)
    (day / "videos" / f"{stamp}_a.mp4").write_bytes(b"")
    (day / "videos" / f"{stamp}_a.txt").write_text("caption")
    (day / "carousels" / "slug").mkdir(parents=True)
    return day


def test_uses_folder_date_not_file_age(cfg):
    make_day(cfg, "20261025")
    make_day(cfg, "20261026")
    today_dir = make_day(cfg, "20261027")
    (cfg.output_dir / "notes").mkdir()

    plan = cleanup.run(cfg, today=datetime.date(2026, 10, 27), use_drive=False, log=lambda _: None)

    assert [d.name for d in plan.days] == ["20261025", "20261026"]
    assert len(plan.videos) == 2 and len(plan.carousels) == 2
    assert sorted(p.name for p in cfg.output_dir.iterdir()) == ["20261027", "notes"]
    assert today_dir.exists()


def test_dry_run_deletes_nothing(cfg):
    day = make_day(cfg, "20261020")
    lines = []
    cleanup.run(cfg, today=datetime.date(2026, 10, 27), dry_run=True, log=lines.append)
    assert day.exists()
    assert lines and all(line.startswith("[dry-run]") for line in lines)


def test_no_output_dir(cfg):
    assert cleanup.run(cfg, use_drive=False).days == []
