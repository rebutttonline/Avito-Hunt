from avito_hunt.review_comments import analyze_review_comment


def test_extracts_expert_reasons_from_free_form_comment() -> None:
    tags = analyze_review_comment(
        "Цена хорошая для перепродажи, но продавец — магазин и аккумулятор уставший"
    )

    assert tags == ("цена/маржа", "состояние", "продавец")


def test_unknown_comment_remains_valid_without_invented_tags() -> None:
    assert analyze_review_comment("мне такое не подходит") == ()
