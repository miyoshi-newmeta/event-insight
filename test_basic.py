"""基本動作テスト: データストアの読み書き・インサイト用データ整形・Discord分割。

  python -m pytest test_basic.py -q
"""
import importlib
import os
import time


def _fresh_modules(tmp_path):
    os.environ["EI_DATA_DIR"] = str(tmp_path)
    import config
    importlib.reload(config)
    import datastore
    importlib.reload(datastore)
    import insight
    importlib.reload(insight)
    return datastore, insight


def test_datastore_roundtrip(tmp_path):
    datastore, _ = _fresh_modules(tmp_path)

    datastore.append_transcript("lt", "登壇者A", "AIで業務を自動化しました", raw="えーAIで業務を自動化しました")
    datastore.append_comment("参加者B", "すごい!")
    datastore.append_memo("g1", "参加者C", "RAGを試したい")

    lt = datastore.load_transcript("lt")
    assert len(lt) == 1
    assert lt[0]["speaker"] == "登壇者A"
    assert lt[0]["raw"].startswith("えー")

    assert datastore.load_comments()[0]["text"] == "すごい!"
    assert datastore.load_memos("g1")[0]["session"] == "g1"

    c = datastore.counts(["g1", "g2"])
    assert c["lt_transcript"] == 1
    assert c["comments"] == 1
    assert c["g1_memos"] == 1
    assert c["g2_memos"] == 0


def test_since_filter(tmp_path):
    datastore, _ = _fresh_modules(tmp_path)
    datastore.append_comment("A", "古いコメント")
    cutoff = time.time() + 1
    assert datastore.load_comments(since_ts=cutoff) == []
    assert len(datastore.load_comments()) == 1


def test_gather_data_scopes(tmp_path):
    datastore, insight = _fresh_modules(tmp_path)
    datastore.append_transcript("lt", "A", "LTの話")
    datastore.append_transcript("g2", "B", "グループ2の話")
    datastore.append_memo("g2", "B", "メモ")

    all_data = insight.gather_data("all", ["g1", "g2"])
    assert "LTの話" in all_data
    assert "グループ2の話" in all_data

    lt_only = insight.gather_data("lt", ["g1", "g2"])
    assert "LTの話" in lt_only
    assert "グループ2の話" not in lt_only

    g2_only = insight.gather_data("g2", ["g1", "g2"])
    assert "グループ2の話" in g2_only
    assert "LTの話" not in g2_only


def test_chunk_for_discord(tmp_path):
    _, insight = _fresh_modules(tmp_path)
    text = "\n".join(f"行{i} " + "あ" * 50 for i in range(100))
    chunks = insight.chunk_for_discord(text, limit=1900)
    assert all(len(c) <= 1900 for c in chunks)
    assert "".join(c.replace("\n", "") for c in chunks) == text.replace("\n", "")

    # 1行が制限を超えるケース
    long_line = "x" * 5000
    chunks = insight.chunk_for_discord(long_line, limit=1900)
    assert all(len(c) <= 1900 for c in chunks)
    assert "".join(chunks) == long_line
