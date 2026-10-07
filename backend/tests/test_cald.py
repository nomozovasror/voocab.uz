"""`scripts/cald.py` (the CALD pilot): the parts that need no network and
no database -- the index parser, the matcher's rules, the sample draw, the
map-answer parser, the decision log and the review page.

Every fixture here is SYNTHETIC: invented entries in the shape of the
extract's ``entries.json``, with definitions written for these tests. No
CALD text is (or may ever be) in this repository -- see the script's own
docstring.
"""

import json
import re

import pytest

from app.services import lexicon_enrich as le
from scripts import cald

# --- A tiny dictionary in the extract's shape -------------------------------------

ENTRIES = {
    "colour": {"headword": "colour", "pron": {"uk": {"ipa": "x", "audio": "media/audio/c1.mp3"}},
               "blocks": [
        {"pos": "noun", "guideword": "HUE", "forms": ["colours"],
         "senses": [
             {"num": 1, "level": "A1", "definition": "test sense: the hue of a thing",
              "examples": ["A first made-up sentence.", "A second one."]},
             {"num": 2, "definition": ""},  # no definition: skipped, index kept
             {"num": 3, "level": "Z9", "definition": "test sense: liveliness",
              "examples": [{"pattern": "[+ that]", "text": "A patterned example."}]},
         ]},
        {"pos": "verb", "guideword": "PAINT",
         "verb_forms": {"present_simple": {"he/she/it": "colours"},
                        "present_participle": "colouring", "past_simple": "coloured",
                        "past_participle": "coloured"},
         "senses": [{"definition": "test sense: to give a hue to"}]},
    ]},
    "jeopardize": {"headword": "jeopardize", "blocks": [
        {"headword": "jeopardize", "pos": "verb", "variants": [{"label": "UK USUALLY",
                                                                "word": "jeopardise"}],
         "senses": [{"definition": "test sense: to put at risk"}]},
    ]},
    "defence": {"headword": "defence", "blocks": [
        {"pos": "noun", "guideword": "PROTECTION", "senses": [{"definition": "test sense: a shield"}]},
    ]},
    "vertebra": {"headword": "vertebra", "blocks": [
        {"headword": "verˈtebra", "pos": "noun", "forms": ["vertebrae"],
         "senses": [{"definition": "test sense: a small back bone"}],
         "derived": [
             {"headword": "vertebral", "pos": "adjective", "senses": [{"examples": ["Only an example."]}]},
             {"headword": "vertebrate-ish", "pos": "adjective",
              "senses": [{"definition": "test sense: derived with its own meaning"}]},
         ]},
    ]},
    "record": {"headword": "record", "blocks": [
        {"pos": "verb", "senses": [{"definition": "test sense: to store sound"}]},
    ]},
    "take sb/sth for granted": {"headword": "take sb/sth for granted", "blocks": [
        {"main_entry": "grant", "senses": [{"definition": "test sense: to fail to value"}]},
    ]},
    "keep": {"headword": "keep", "blocks": [
        {"pos": "verb", "guideword": "HAVE", "senses": [
            {"definition": "test sense: to continue having"},
            {"phrase": "keep your word/promise", "definition": "test sense: to do as promised"},
        ]},
    ]},
    "accordance": {"headword": "accordance", "blocks": [
        {"pos": "noun", "senses": [{"phrase": "in accordance with sth",
                                    "definition": "test sense: following a rule"}]},
    ]},
    "hinge on sth": {"headword": "hinge on sth", "blocks": [
        {"headword": "hinge on/upon sth", "pos": "phrasal verb", "base": "hinge",
         "senses": [{"definition": "test sense: to depend on"}]},
    ]},
    "adviser": {"headword": "adviser", "blocks": [
        {"pos": "noun", "senses": [{"definition": "test sense: someone who advises"}]},
    ]},
    "advisor": {"headword": "advisor", "blocks": [
        {"headword": "adviser", "pos": "noun", "senses": [{"definition": "test sense: someone who advises"}]},
    ]},
    "abandon": {"headword": "abandon", "blocks": [
        {"pos": "verb", "senses": [{"definition": "test sense: to leave behind"}]},
        {"headword": "abandonment", "pos": "noun", "senses": [{"examples": ["Only an example."]}]},
    ]},
    "aspect ratio": {"headword": "aspect ratio", "blocks": [
        {"pos": "noun", "senses": [{"definition": "test sense: width against height"}]},
    ]},
    "zib": {"headword": "zib", "blocks": [
        {"pos": "verb", "senses": [{"definition": "ZOB(Cf. ↑zob)"}]},
    ]},
    "zab": {"headword": "zab", "blocks": [
        {"pos": "noun", "senses": [{"definition": "ZOB(Cf. ↑zob) noun (TOPIC)"}]},
    ]},
    "zub": {"headword": "zub", "blocks": [
        {"pos": "verb", "senses": [{"definition": "QQQ(Cf. ↑qqq)"}]},
    ]},
    "zob": {"headword": "zob", "blocks": [
        {"pos": "noun", "guideword": "TOPIC", "senses": [{"definition": "test sense: a topical zob"}]},
        {"pos": "noun", "guideword": "OTHER", "senses": [{"definition": "test sense: another zob"}]},
        {"pos": "verb", "senses": [{"definition": "test sense: to zob something"}]},
    ]},
    "odd": {"headword": "odd", "blocks": [
        {"pos": "B1", "senses": [{"definition": "test sense: a scraping artefact pos"}]},
    ]},
}
ALIASES = {"aspect": "aspect ratio", "adviser": "adviser", "gone": "missing-key"}


@pytest.fixture(scope="module")
def data():
    return cald.parse_entries(ENTRIES, ALIASES)


@pytest.fixture(scope="module")
def index(data):
    return cald.CaldIndex(data)


# --- index ------------------------------------------------------------------------


def test_refs_count_source_positions_and_skip_undefined_senses(data):
    noun = data["headwords"]["colour"][0]
    assert [s["ref"] for s in noun["senses"]] == ["colour#0#0", "colour#0#2"]
    assert noun["id"] == "colour#0"


def test_level_example_pos_class_and_pron(data):
    noun, verb = data["headwords"]["colour"]
    first, third = noun["senses"]
    assert first["level"] == "A1" and third["level"] is None  # only A1..C2 kept
    assert first["ex"] == "A first made-up sentence."
    assert third["ex"] == "A patterned example."  # the {"pattern", "text"} shape
    assert (noun["cls"], verb["cls"]) == ("n", "v")
    assert noun["pron"]["uk"]["audio"] == "media/audio/c1.mp3"  # entry pron as fallback
    assert data["headwords"]["hinge on sth"][0]["cls"] == "v"  # phrasal verb is a verb
    assert data["headwords"]["take sb/sth for granted"][0]["cls"] == "idiom"
    assert data["headwords"]["odd"][0]["cls"] == "?"


def test_inflections_stress_marks_redirects_and_derived(data):
    noun, verb = data["headwords"]["colour"]
    assert noun["forms"] == ["colours"]
    assert set(verb["forms"]) == {"colours", "colouring", "coloured"}
    vertebra = data["headwords"]["vertebra"]
    assert vertebra[0]["hw"] == "vertebra" and not vertebra[0]["redirect"]
    derived = vertebra[1]
    assert derived["hw"] == "vertebrate-ish" and derived["derived"]
    assert derived["senses"][0]["ref"] == "vertebra#0.d1#0"
    assert data["headwords"]["advisor"][0]["redirect"]
    assert not data["headwords"]["hinge on sth"][0]["redirect"]  # a `base` page
    assert data["undefined"]["vertebral"] == ["adj"]
    assert data["undefined"]["abandonment"] == ["n"]


def test_cross_reference_markup_is_cleaned_and_marked(data):
    sense = data["headwords"]["zib"][0]["senses"][0]
    assert sense["def"] == "zob" and sense["xref"] == ["zob"] and sense["xref_only"]
    text, targets, only = cald.clean_definition("a small kind of ZOB(Cf. ↑zob) noun (TOPIC)")
    assert text == "a small kind of zob noun (TOPIC)" and targets == ["zob"] and not only
    assert cald.clean_definition("ZOB(Cf. ↑zob) noun (TOPIC)")[2]


def test_aliases_keep_only_existing_targets(data):
    assert data["aliases"] == {"aspect": "aspect ratio", "adviser": "adviser"}


def test_build_index_round_trip(tmp_path):
    source = tmp_path / "src"
    (source / "data").mkdir(parents=True)
    (source / "data" / "entries.json").write_text(json.dumps(ENTRIES))
    (source / "data" / "aliases.json").write_text(json.dumps(ALIASES))
    out = tmp_path / "private"
    built = cald.build_index(source, out)
    loaded = cald.load_index_data(out)
    assert loaded["headwords"] == built["headwords"]
    assert loaded["version"] == cald.INDEX_VERSION and len(loaded["entries_sha256"]) == 64


# --- normalisation rules ----------------------------------------------------------


@pytest.mark.parametrize(("word", "expected"), [
    ("jeopardise", "jeopardize"), ("specialised", "specialized"), ("analyze", "analyse"),
    ("defense", "defence"), ("flavor", "flavour"), ("behaviour", "behavior"),
    ("installment", "instalment"), ("traveling", "travelling"), ("center", "centre"),
    ("anemia", "anaemia"), ("catalog", "catalogue"), ("gray", "grey"),
    ("judgment", "judgement"), ("centered", "centred"),
])
def test_spelling_variants_one_step(word, expected):
    assert expected in cald.spelling_variants(word)


def test_spelling_variants_two_steps_and_never_word_final_ae():
    assert "manoeuvre" not in cald.spelling_variants("maneuver")
    assert "manoeuvre" in cald.spelling_variants("maneuver", depth=2)
    assert "mare" not in cald.spelling_variants("marae")
    assert "pile" not in cald.spelling_variants("pilae")


def test_singular_candidates():
    assert "vertebra" in cald.singular_candidates("vertebrae")
    assert "criterion" in cald.singular_candidates("criteria")
    assert "study" in cald.singular_candidates("studies")
    assert "identical twin" in cald.singular_candidates("identical twins")
    assert "child" in cald.singular_candidates("children")


def test_hyphen_variants():
    assert cald.hyphen_variants("on-board") == {"on board", "onboard"}
    assert cald.hyphen_variants("chess board") == {"chess-board", "chessboard"}


def test_phrase_forms():
    assert "take for granted" in cald.phrase_forms("take sb/sth for granted")
    assert cald.phrase_forms("make one's way") & cald.phrase_forms("make your way")
    assert "make way" not in cald.phrase_forms("make one's way")  # a different idiom
    assert "in keeping with" in cald.phrase_forms("in/out of keeping (with sth)")
    assert {"zob notion", "zob sense"} <= cald.phrase_forms("zob notion/sense")
    assert "wug of the zob" in cald.phrase_forms("(a) wug of the zob")


def test_alias_is_same():
    assert not cald.alias_is_same("aspect", "aspect ratio")  # a search fallback
    assert cald.alias_is_same("adapter", "adaptor")
    assert cald.alias_is_same("judgement", "judgment")
    assert not cald.alias_is_same("bridge", "bridgework")
    assert cald.alias_is_same("a bird in the hand", "a bird in the hand is worth two")


def test_compatible_pos():
    assert cald.compatible("n", "n", False)
    assert not cald.compatible("n", "v", False)  # never across a meaning-changing pos
    assert not cald.compatible("adj", "num", False)  # left for the owner to decide
    assert cald.compatible("phr", "n", True) and cald.compatible("", "adj", False)
    assert cald.compatible("v", "idiom", True) and not cald.compatible("v", "idiom", False)
    assert not cald.compatible("n", "?", False) and not cald.compatible("phr", "affix", True)


# --- the matcher ------------------------------------------------------------------


@pytest.mark.parametrize(("lemma", "pos", "kind", "how", "via"), [
    ("colour", "n", "exact", "exact", "colour"),
    ("jeopardise", "v", "variant", "cald-variant", "jeopardize"),
    ("defense", "n", "variant", "spelling", "defence"),
    ("color", "v", "variant", "spelling", "colour"),
    ("vertebrae", "n", "variant", "plural", "vertebra"),
    ("coloured", "v", "variant", "verb-form", "colour"),
    ("hinge", "v", "variant", "phrasal-verb", "hinge on/upon sth"),
    ("take for granted", "phr", "variant", "idiom", "take for granted"),
    ("keep one's word", "phr", "variant", "idiom-sense", "keep your word/promise"),
    ("vertebrate-ish", "adj", "exact", "exact", "vertebrate-ish"),
])
def test_match_steps(index, lemma, pos, kind, how, via):
    match = index.match(lemma, pos)
    assert (match.kind, match.how, match.via) == (kind, how, via)
    assert match.refs


def test_match_never_crosses_pos(index):
    match = index.match("record", "n")  # the extract has `record` only as a verb
    assert match.kind == "headword-only" and match.cald_classes == ["v"] and not match.refs


def test_phrase_senses_only_for_phrases_unless_the_word_has_nothing_else(index):
    keep = index.match("keep", "v")
    assert keep.refs == ["keep#0#0"]  # `keep your word` is not the word's meaning
    accordance = index.match("accordance", "n")
    assert accordance.kind == "exact" and accordance.refs == ["accordance#0#0"]


def test_redirect_copies_are_deduplicated(index):
    assert index.match("adviser", "n").refs == ["adviser#0#0"]


def test_no_definition_and_missing_headwords(index):
    assert index.match("abandonment", "n").kind == "no-definition"
    missing = index.match("aspect", "n")
    assert (missing.kind, missing.how, missing.via) == ("none", "alias-elsewhere", "aspect ratio")
    assert index.match("zzyzx", "n").kind == "none"


# --- sample, answers, log ---------------------------------------------------------


def _sense(i, lexeme, lemma="w"):
    return cald.OurSense(id=f"s{i:03}", lexeme_id=lexeme, lemma=lemma, pos="n", sense_rank=1,
                         definition_en="d", meaning_uz="u", meaning_uz_alt="", cefr="B1",
                         source_id="oewn")


def test_draw_sample_is_stratified_and_deterministic():
    senses = [_sense(i, f"L{i // 2}") for i in range(200)]
    matches = {f"L{i}": {"kind": "variant" if i % 10 == 0 else "exact"} for i in range(100)}
    matches["L99"] = {"kind": "none"}
    lexicon = cald.Lexicon(lexemes=[], senses=senses, saved_senses={f"s{i:03}" for i in range(5)},
                           word_list_senses={f"s{i:03}" for i in range(50, 150)},
                           word_list_lexemes=set(), material_senses={f"s{i:03}" for i in range(0, 200, 3)})
    first = cald.draw_sample(senses, matches, lexicon, 40, seed=3)
    again = cald.draw_sample(senses, matches, lexicon, 40, seed=3)
    assert [s.id for s, _ in first] == [s.id for s, _ in again]
    assert len({s.id for s, _ in first}) == 40
    strata = [stratum for _, stratum in first]
    assert strata.count("saved") == 5  # all there are
    assert strata.count("word_list") == 12
    assert all(s.lexeme_id not in ("L99",) for s, _ in first)  # unmatched never drawn
    siblings = [s.lexeme_id for s, st in first if st == "siblings"]
    assert siblings and all(siblings.count(lx) == 2 for lx in siblings)


def test_parse_map_answer():
    cands = [{"cid": "c1", "ref": "a#0#0"}, {"cid": "c2", "ref": "a#1#0"}]
    assert cald.parse_map_answer({"choice": "c2", "confidence": "high", "reason": "r"},
                                 cands) == {"ref": "a#1#0", "confidence": "high", "reason": "r"}
    assert cald.parse_map_answer({"choice": "none", "confidence": "medium"}, cands)["ref"] is None
    assert cald.parse_map_answer({"choice": "a#0#0"}, cands)["confidence"] == "low"
    assert cald.parse_map_answer({"choice": "c9"}, cands) is None  # not a shown id
    assert cald.parse_map_answer("nonsense", cands) is None


def test_decision_log_round_trip(tmp_path):
    path = tmp_path / "decisions.jsonl"
    log = cald.DecisionLog(path)
    log.put("map", "s1|h1", {"sense_id": "s1", "ref": "a#0#0"})
    log.put("map", "s1|h2", {"sense_id": "s1", "ref": "a#1#0"})
    reread = cald.DecisionLog(path)
    assert reread.get("map", "s1|h1")["ref"] == "a#0#0"
    assert reread.latest("map", "s1")["ref"] == "a#1#0"
    assert reread.get("translate", "s1|h1") is None


# --- the review page --------------------------------------------------------------


def _review_inputs(index, tmp_path):
    items = [
        {"sense_id": "11111111-1111-1111-1111-111111111111", "lexeme_id": "L1",
         "lemma": "colour", "pos": "n", "stratum": "word_list", "sense_rank": 1,
         "definition_en": "our <b>hue</b> sense", "meaning_uz": "rang", "meaning_uz_alt": "tus",
         "cefr": "B1", "source_id": "oewn", "example": "A made-up passage line.",
         "match_kind": "exact", "match_how": "exact", "match_via": "colour",
         "refs": ["colour#0#0", "colour#0#2"], "refs_cut": 0},
        {"sense_id": "22222222-2222-2222-2222-222222222222", "lexeme_id": "L2",
         "lemma": "defense", "pos": "n", "stratum": "variant", "sense_rank": 2,
         "definition_en": "a sports team's guards", "meaning_uz": "himoya", "meaning_uz_alt": "",
         "cefr": None, "source_id": "model", "example": "", "match_kind": "variant",
         "match_how": "spelling", "match_via": "defence", "refs": ["defence#0#0"], "refs_cut": 0},
    ]
    sample = {"n": 2, "seed": 1, "run_id": "run123", "items": items}
    log = cald.DecisionLog(tmp_path / "d.jsonl")
    log.put("map", "k1", {"sense_id": items[0]["sense_id"], "answered": True, "ref": "colour#0#0",
                          "confidence": "high", "reason": "same hue"})
    log.put("map", "k2", {"sense_id": items[1]["sense_id"], "answered": True, "ref": None,
                          "confidence": "medium", "reason": "sport sense missing"})
    log.put("translate", cald.translate_key(items[0], "colour#0#0", "test sense: the hue of a thing"),
            {"sense_id": items[0]["sense_id"], "ref": "colour#0#0", "new_uz": "rang",
             "new_alt": "tus", "new_verdict": "same", "old_verdict": "unsure"})
    return sample, log


def test_review_rows(index, tmp_path):
    sample, log = _review_inputs(index, tmp_path)
    mapped, none = cald.review_rows(sample, log, index)
    assert mapped["decision"] == "mapped" and mapped["cald"]["def"] == "test sense: the hue of a thing"
    assert (mapped["cefr_final"], mapped["cefr_source"]) == ("A1", "cald")
    assert (mapped["v1_uz"], mapped["old_verdict"], mapped["new_verdict"]) == ("rang", "unsure", "same")
    assert mapped["v2"] is None  # round 2 not run in this log
    assert [c["chosen"] for c in mapped["candidates"]] == [True, False]
    assert none["decision"] == "none" and none["v1_uz"] == "" and none["cefr_source"] == "ours"


def test_render_review_is_self_contained_and_escaped(index, tmp_path):
    sample, log = _review_inputs(index, tmp_path)
    page = cald.render_review(cald.review_rows(sample, log, index), run_id="run123")
    assert page.startswith("<!doctype html>")
    assert not re.search(r"https?://|\bsrc=|<link\b|@import|url\(", page)
    assert "our &lt;b&gt;hue&lt;/b&gt; sense" in page and "<b>hue</b>" not in page
    mapped_id, none_id = (i["sense_id"] for i in sample["items"])
    for question in ("same", "uz"):
        assert page.count(f'name="{question}-{mapped_id}"') == 3  # yes / no / unsure
    assert page.count(f'name="none_correct-{none_id}"') == 3
    assert f'name="uz-{none_id}"' not in page
    assert 'data-storage-key="voocab-cald-pilot:run123"' in page
    assert 'id="export"' in page and "localStorage" in page


# --- round 2: pointers, translation v2, the comparison judge ------------------------



def _item(sense_id, lemma, pos, refs, uz="eski", alt=""):
    return {"sense_id": sense_id, "lexeme_id": "L", "lemma": lemma, "pos": pos,
            "stratum": "other", "sense_rank": 1, "definition_en": "our def", "meaning_uz": uz,
            "meaning_uz_alt": alt, "cefr": "B1", "source_id": "oewn", "example": "",
            "match_kind": "exact", "match_how": "exact", "match_via": lemma, "refs": refs,
            "refs_cut": 0}


def test_pointer_target_and_candidates(index):
    zib_block, zib = index.senses["zib#0#0"]
    assert cald.pointer_target(zib, zib_block["cls"]) == ("zob", "v", "")
    assert cald.pointer_candidates(index, "zib#0#0", "v") == ["zob#2#0"]  # same pos as the pointer
    zab_block, zab = index.senses["zab#0#0"]
    assert cald.pointer_target(zab, zab_block["cls"]) == ("zob", "n", "TOPIC")
    assert cald.pointer_candidates(index, "zab#0#0", "n") == ["zob#0#0"]  # narrowed by topic
    assert cald.pointer_candidates(index, "zub#0#0", "v") == []  # target not in the extract
    assert cald.pointer_candidates(index, "zib#0#0", "n") == []  # never across our pos


async def test_follow_pointers_and_effective_mapping(index, tmp_path):
    log = cald.DecisionLog(tmp_path / "d.jsonl")
    items = [_item("s1", "zib", "v", ["zib#0#0"]), _item("s2", "zub", "v", ["zub#0#0"]),
             _item("s3", "colour", "n", ["colour#0#0"]), _item("s4", "colour", "n", ["colour#0#2"])]
    for item, ref, confidence in ((items[0], "zib#0#0", "high"), (items[1], "zub#0#0", "medium"),
                                  (items[2], "colour#0#0", "medium"),
                                  (items[3], "colour#0#2", "low")):
        log.put("map", item["sense_id"], {"sense_id": item["sense_id"], "answered": True,
                                          "ref": ref, "confidence": confidence, "reason": "r"})
    before = cald.effective_mapping(log, items[0], index)
    assert before["decision"] == "none" and "not resolved" in before["reason"]
    counts = await cald.follow_pointers({"items": items}, log, index, gemini=None, model="m")
    assert counts == {"single": 1, "unresolved": 1}
    followed = cald.effective_mapping(log, items[0], index)
    assert (followed["decision"], followed["ref"], followed["pointer_ref"]) == (
        "mapped", "zob#2#0", "zib#0#0")
    assert cald.effective_mapping(log, items[1], index)["decision"] == "none"
    assert cald.effective_mapping(log, items[2], index)["decision"] == "mapped"  # medium applies
    low = cald.effective_mapping(log, items[3], index)
    assert low["decision"] == "none" and low["reason"].startswith("[low")
    again = await cald.follow_pointers({"items": items}, log, index, gemini=None, model="m")
    assert again == {"reused": 2}


def test_parse_v2_item():
    entry = {"old_uz": "to'qnashmoq, urilmoq"}
    kept = cald.parse_v2_item({"uz": "to'qnashmoq, urilmoq.", "flag": "kept", "reason": "ok"}, entry)
    assert kept == {"uz": "to'qnashmoq, urilmoq", "flag": "kept", "flag_given": True,
                    "changed": False, "reason": "ok"}
    lying = cald.parse_v2_item({"uz": "urilmoq", "flag": "kept"}, entry)
    assert lying["flag"] == "kept" and lying["changed"]  # the model's flag, and the text fact
    unknown = cald.parse_v2_item({"uz": "urmoq", "flag": "rewrote"}, entry)
    assert (unknown["flag"], unknown["flag_given"]) == ("replaced", False)
    assert cald.parse_v2_item({"uz": "  ", "flag": "kept"}, entry) is None
    assert cald.parse_v2_item(["urmoq"], entry) is None


def test_compare_render_and_parse_undo_the_swap():
    entry = {"lemma": "smash", "pos": "v", "cald": {"def": "test sense", "gw": "MOVE"},
             "example": "", "old_uz": "eski", "old_alt": "", "new_uz": "yangi", "new_alt": "yangi2"}
    plain = cald.render_compare_item("k1", dict(entry, swap=False))
    swapped = cald.render_compare_item("k1", dict(entry, swap=True))
    assert 'A: "eski"' in plain and 'B: "yangi" / "yangi2"' in plain
    assert 'A: "yangi" / "yangi2"' in swapped and 'B: "eski"' in swapped
    reply = {"better": "a", "wrong_a": True, "wrong_b": "false", "reason": "x"}
    assert cald.parse_compare_item(reply, {"swap": False}) == {
        "better": "old", "wrong_old": True, "wrong_new": False, "reason": "x"}
    assert cald.parse_compare_item(reply, {"swap": True}) == {
        "better": "new", "wrong_old": False, "wrong_new": True, "reason": "x"}
    assert cald.parse_compare_item({"better": "maybe"}, {"swap": False}) is None


def _run(better, wrong_old=False, wrong_new=False):
    return {"better": better, "wrong_old": wrong_old, "wrong_new": wrong_new, "reason": ""}


@pytest.mark.parametrize(("runs", "keep", "loose", "flags"), [
    ([_run("new"), _run("equal")], "new", "new", []),
    ([_run("old"), _run("old")], "old", "old", []),
    ([_run("old"), _run("new")], "new", "old", ["disputed"]),
    ([_run("equal", wrong_new=True), _run("new", wrong_new=True)], "old", "old", []),
    ([_run("new", wrong_new=True), _run("new")], "new", "old", ["disputed"]),
    ([_run("old"), None], "new", "old", ["one-run", "disputed"]),
    ([None, None], "new", "new", ["no-verdict"]),
    ([_run("equal", True, True), _run("equal", True, True)], "old", "old", ["both_wrong"]),
])
def test_combine_comparison(runs, keep, loose, flags):
    combined = cald.combine_comparison(runs)
    assert (combined["keep"], combined["loose_keep"], combined["flags"]) == (keep, loose, flags)


def test_round2_review_rows_page_and_dump(index, tmp_path):
    sample, log = _review_inputs(index, tmp_path)
    item = sample["items"][0]
    entry = cald.v2_entry(item, "colour#0#0", index)
    log.put("translate2", cald.translate2_key(entry, le.MODEL_MAIN), {
        "sense_id": item["sense_id"], "answered": True, "uz": "rang", "flag": "kept",
        "flag_given": True, "changed": False, "reason": "current fits"})
    log.put("translate2", cald.translate2_key(entry, le.MODEL_ALT), {
        "sense_id": item["sense_id"], "answered": True, "uz": "rang, tus", "flag": "adjusted",
        "flag_given": True, "changed": True, "reason": "added a synonym"})
    entry.update(new_uz="rang", new_alt="rang, tus")
    runs = [_run("equal"), _run("new")]
    log.put("compare", cald.compare_key(entry, "judge-x"), {
        "sense_id": item["sense_id"], "judge_model": "judge-x", "per_run": runs,
        **cald.combine_comparison(runs)})
    mapped, _ = cald.review_rows(sample, log, index)
    v2 = mapped["v2"]
    assert (v2["uz"], v2["alt"], v2["flag"], v2["alt_flag"]) == ("rang", "rang, tus", "kept", "adjusted")
    assert v2["compare"]["judge-x"]["keep"] == "new"
    page = cald.render_review(cald.review_rows(sample, log, index), run_id="run123", round_tag="r2")
    assert 'data-storage-key="voocab-cald-pilot:run123:r2"' in page
    assert "v2 Uzbek is correct?" in page and "judge-x" in page and 'data-flag="kept"' in page
    assert not re.search(r"https?://|\bsrc=|<link\b", page)
    dump = cald.render_dump(cald.review_rows(sample, log, index))
    first, second = dump.strip().split("\n\n")
    assert first.startswith("#1 colour (n)") and "v2 uz:   rang  |  alt: rang, tus" in first
    assert "flag:    kept -- current fits" in first and "judge:   judge-x" in first
    assert "keep new" in first and "v1 uz:   rang  |  alt: tus" in first
    assert second.startswith("#2 defense (n)") and "map: none" in second and "v2 uz" not in second


# --- phase 2a: the fixed source's shape --------------------------------------------


FIXED = {
    "wug": {"headword": "wug",
            "pron": {"uk": {"ipa": "e-uk", "audio": "media/audio/e-uk.mp3",
                            "ipa_variants": ["e-weak"]},
                     "us": {"ipa": "e-us", "audio": "media/audio/e-us.mp3"}},
            "blocks": [
        {"headword": "wug", "pos": "noun", "guideword": "THING",
         "pron": {"uk": {"ipa": "n-uk", "audio": "media/audio/n-uk.mp3"},
                  "us": {"ipa": "n-us", "audio": "media/audio/n-us.mp3"}},
         "word_builder": {"nouns": ["wug"]}, "word_partners": ["a big wug"],
         "collocations": [{"group": "verbs", "items": []}], "images": ["media/images/x.jpg"],
         "common_mistakes": [{"title": "t", "points": []}], "forms": ["wugs"],
         "senses": [{"definition": "test sense: a made-up animal", "level": "B1",
                     "pron": {"uk": {"ipa": "s-uk", "audio": "media/audio/s-uk.mp3"}}}],
         "derived": [{"headword": "wuggish", "pos": "adjective",
                      "pron": {"uk": {"ipa": "d-uk", "audio": "media/audio/d-uk.mp3"}},
                      "senses": [{"definition": "test sense: like a wug"}]}]},
        {"headword": "wug", "pos": "verb", "guideword": "MOVE",
         "pron": {"uk": {"ipa": "v-uk", "audio": "media/audio/v-uk.mp3"},
                  "us": {"ipa": "v-us", "audio": "media/audio/v-us.mp3"}},
         "senses": [{"definition": "test sense: to move like a wug"}]},
        {"headword": "wug", "pos": "noun", "guideword": "SAME SOUND",
         "pron": {"uk": {"ipa": "n-uk", "audio": "media/audio/n-uk.mp3"},
                  "us": {"ipa": "n-us", "audio": "media/audio/n-us.mp3"}},
         "senses": [{"definition": "test sense: a second noun"}]},
        {"headword": "wug", "pos": "adjective",
         "senses": [{"definition": "test sense: no pron of its own"}]},
    ]},
    "wug out": {"headword": "wug out", "blocks": [
        {"headword": "wug (sth) out", "pos": "phrasal verb", "base": "wug",
         "pron": {"uk": {"ipa": "p-uk", "audio": "media/audio/p-uk.mp3"}},
         "base_pron": {"uk": {"ipa": "v-uk", "audio": "media/audio/v-uk.mp3"}},
         "senses": [{"definition": "test sense: to tire out"}]},
    ]},
}


def test_the_fixed_source_keeps_pronunciation_per_block():
    data = cald.parse_entries(FIXED, {})
    assert data["version"] == cald.INDEX_VERSION == 4
    noun, derived, verb, noun2, adj = data["headwords"]["wug"]
    # A heteronym: the noun and the verb blocks sound different.
    assert noun["pron"]["uk"] == {"ipa": "n-uk", "audio": "media/audio/n-uk.mp3"}
    assert verb["pron"]["uk"]["ipa"] == "v-uk" and noun["pron_from"] == "block"
    # No pron of its own: the entry's, said so; ipa_variants kept.
    assert adj["pron_from"] == "entry" and adj["pron"]["uk"]["ipa_variants"] == ["e-weak"]
    assert derived["hw"] == "wuggish" and derived["pron"]["uk"]["ipa"] == "d-uk"
    assert noun["senses"][0]["pron"]["uk"]["ipa"] == "s-uk"  # a sense's own pron
    assert noun["forms"] == ["wugs"] and noun["senses"][0]["level"] == "B1"
    # The new extract fields carry no definition and are not copied.
    assert not {"word_builder", "word_partners", "collocations", "images",
                "common_mistakes"} & set(noun)
    phrasal = data["headwords"]["wug out"][0]
    assert phrasal["base_pron"]["uk"]["ipa"] == "v-uk" and phrasal["pron"]["uk"]["ipa"] == "p-uk"
    # The headword's distinct pronunciations, each with the classes using it.
    by_ipa = {p["pron"]["uk"]["ipa"]: sorted(p["classes"]) for p in data["pron"]["wug"]}
    assert by_ipa == {"n-uk": ["n"], "v-uk": ["v"], "e-uk": ["adj"]}


def test_map_and_pointer_keys_carry_candidate_content():
    """A ref is a position in the source file: the same ref with another
    definition is another question (MAP_VERSION 3)."""
    item = _item("s1", "colour", "n", ["colour#0#0"])
    first = cald.CaldIndex(cald.parse_entries(ENTRIES, {}))
    changed = json.loads(json.dumps(ENTRIES))
    changed["colour"]["blocks"][0]["senses"][0]["definition"] = "test sense: something else"
    second = cald.CaldIndex(cald.parse_entries(changed, {}))
    key = lambda ix: cald.map_key(item, ix.candidates(item["refs"]))  # noqa: E731
    assert key(first) != key(second)
    assert key(first) == key(cald.CaldIndex(cald.parse_entries(ENTRIES, {})))
    assert cald.map_key(item, first.candidates(item["refs"])) != cald.map_key(
        dict(item, example="another sentence"), first.candidates(item["refs"]))


def test_revalidate_carries_only_unchanged_questions(tmp_path):
    old = cald.CaldIndex(cald.parse_entries(ENTRIES, {}))
    changed = json.loads(json.dumps(ENTRIES))
    changed["defence"]["blocks"][0]["senses"][0]["definition"] = "test sense: moved text"
    new = cald.CaldIndex(cald.parse_entries(changed, {}))
    same = _item("s1", "colour", "n", old.match("colour", "n").refs)
    moved = _item("s2", "defence", "n", old.match("defence", "n").refs)
    log = cald.DecisionLog(tmp_path / "d.jsonl")
    for item, ref in ((same, "colour#0#0"), (moved, "defence#0#0")):
        log.put("map", cald._pilot_map_key(item), {
            "sense_id": item["sense_id"], "answered": True, "ref": ref, "confidence": "high",
            "reason": "r", "cald_definition": old.senses[ref][1]["def"]})
    counts = cald.revalidate_pilot({"items": [same, moved]}, log, old, new)
    assert counts == {"carried": 1, "re-ask: a candidate's content changed": 1}
    carried = log.get("map", cald.map_key(same, new.candidates(same["refs"])))
    assert carried["ref"] == "colour#0#0" and carried["carried_from"]
    assert log.get("map", cald.map_key(moved, new.candidates(moved["refs"]))) is None
    assert cald.revalidate_pilot({"items": [same]}, log, old, new) == {"already carried": 1}
