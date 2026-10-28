from app.scoring import module_score, overall_score


def test_clean_scan_is_100():
    score, per = overall_score({"secrets": {"findings": []}})
    assert score == 100
    assert per == {"secrets": 100}


def test_penalties_and_floor():
    assert module_score([{"severity": "high"}] * 2) == 70
    assert module_score([{"severity": "critical"}] * 10) == 0


def test_weighted_average_over_active_modules():
    results = {
        "secrets": {"findings": [{"severity": "high"}]},  # 85, weight 25
        "dependencies": {"findings": []},                  # 100, weight 25
    }
    score, _ = overall_score(results)
    assert score == round((85 * 25 + 100 * 25) / 50)
