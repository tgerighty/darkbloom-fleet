from fleet import hourly


def test_letters_take_each_models_own_initial():
    letters = hourly._assign_letters(["gemma-4-26b-qat", "nvidia-nemotron-3.5-lightning"])
    assert letters == {"gemma-4-26b-qat": "G", "nvidia-nemotron-3.5-lightning": "N"}


def test_a_colliding_initial_falls_back_to_a_later_words_initial():
    # gemma-4-26b-qat appeared first and claimed G, so gpt-oss-20b takes O.
    letters = hourly._assign_letters(["gemma-4-26b-qat", "gpt-oss-20b"])
    assert letters == {"gemma-4-26b-qat": "G", "gpt-oss-20b": "O"}
    # First appearance decides who wins the G.
    flipped = hourly._assign_letters(["gpt-oss-20b", "gemma-4-26b-qat"])
    assert flipped == {"gpt-oss-20b": "G", "gemma-4-26b-qat": "Q"}


def test_with_no_free_letter_in_the_name_the_alphabet_decides():
    assert hourly._assign_letters(["alpha", "amber"]) == {"alpha": "A", "amber": "B"}


def test_no_rows_means_an_empty_panel(fake_pool):
    empty = hourly.hourly_jobs(fake_pool([]), "h", ["s1"], 10_000.0)
    assert empty == {"legend": [], "range_share": {}, "rows": []}


def test_buckets_letters_and_range_share(fake_pool):
    rows = [{"hour": 97_200.0, "model": "nvidia-nemotron-3.5-lightning", "n": 1},
            {"hour": 97_200.0, "model": "gemma-4-26b-qat", "n": 99},
            {"hour": 93_600.0, "model": "gemma-4-26b-qat", "n": 3},
            {"hour": 93_600.0, "model": "gpt-oss-20b", "n": 2}]
    pool = fake_pool(rows)
    panel = hourly.hourly_jobs(pool, "h", ["s1"], 100_000.0)
    # gemma and gpt-oss first appear in the older bucket, so gemma claims G.
    assert panel["legend"] == [{"letter": "G", "model": "gemma-4-26b-qat"},
                               {"letter": "O", "model": "gpt-oss-20b"},
                               {"letter": "N", "model": "nvidia-nemotron-3.5-lightning"}]
    assert panel["range_share"] == {"gemma-4-26b-qat": 97, "gpt-oss-20b": 2,
                                    "nvidia-nemotron-3.5-lightning": 1}
    assert panel["rows"] == [{"hour": 97_200, "jobs": 100,
                              "counts": {"gemma-4-26b-qat": 99, "nvidia-nemotron-3.5-lightning": 1}},
                             {"hour": 93_600, "jobs": 5,
                              "counts": {"gemma-4-26b-qat": 3, "gpt-oss-20b": 2}}]
    assert pool.calls == [(hourly._HOURLY_SQL, ("h", 100_000.0 - 86_400, ["s1"]))]


def test_more_than_36_models_share_the_overflow_glyph():
    from fleet.hourly import OVERFLOW, _assign_letters
    letters = _assign_letters([f"m{i}" for i in range(40)])
    assert len(letters) == 40
    assert sum(1 for v in letters.values() if v == OVERFLOW) == 4
    assert len({v for v in letters.values() if v != OVERFLOW}) == 36
