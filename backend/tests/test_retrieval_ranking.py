from app.services import retrieval_service


def test_definition_author_hint_boosts_matching_source():
    hint = retrieval_service._definition_query("How does Chandler define strategy?")
    assert hint == "Chandler"
    assert hint.casefold() in "Chandler (1962) defines strategy".casefold()
