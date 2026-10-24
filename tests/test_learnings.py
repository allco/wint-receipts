from wint_receipts.core import recognize
from wint_receipts.core.learnings import Learnings, supplier_key


def test_supplier_key_ignores_case_punctuation_and_company_form():
    assert supplier_key("EasyPark AB") == supplier_key("EASYPARK") == supplier_key("Easypark Aktiebolag")
    assert supplier_key("Clas Ohlson") != supplier_key("EasyPark")


def test_learn_category_then_apply_by_name_or_org(tmp_path):
    lr = Learnings(tmp_path / "learnings.txt")
    lr.learn_category("EasyPark AB", "556626-7893", 86914, "Parkering")
    text = (tmp_path / "learnings.txt").read_text(encoding="utf-8")
    assert text.startswith("# Wint receipts: AI learnings")
    assert 'category: "EasyPark AB" (org 556626-7893) = "Parkering" [86914]' in text
    by_name = lr.apply("EASYPARK", None, 7)
    assert by_name.category_id == 86914 and "Parkering" in by_name.notes[0]
    by_org = lr.apply("Some other name", "5566267893", None)
    assert by_org.category_id == 86914
    assert lr.apply("Clas Ohlson", None, 7).category_id == 7  # no rule → AI's choice stays


def test_new_rule_replaces_old_one_for_same_supplier(tmp_path):
    lr = Learnings(tmp_path / "l.txt")
    lr.learn_category("Mr Wok", None, 1, "Representation")
    lr.learn_category("MR WOK", None, 2, "Personalrepresentation")
    rules = lr.category_rules()
    assert len(rules) == 1 and rules[0].category_id == 2


def test_supplier_alias_and_user_lines_survive(tmp_path):
    path = tmp_path / "l.txt"
    path.write_text("# my notes\nReceipts from Mr Wok are Representation.\n")
    lr = Learnings(path)
    lr.learn_supplier("EASYPARK", "EasyPark AB")
    text = path.read_text(encoding="utf-8")
    assert "# my notes" in text and "Receipts from Mr Wok are Representation." in text
    assert lr.apply("easypark", None, None).supplier_name == "EasyPark AB"
    assert lr.hints() == ["Receipts from Mr Wok are Representation."]
    section = lr.prompt_section()
    assert "Mr Wok are Representation" in section and '"EasyPark AB"' in section


def test_prompt_includes_learnings_only_when_present():
    assert "corrected earlier readings" not in recognize.build_prompt("p.png", [])
    p = recognize.build_prompt("p.png", [], '- "EasyPark AB" → category 86914 ("Parkering")')
    assert "corrected earlier readings" in p and "86914" in p
