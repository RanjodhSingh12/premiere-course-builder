"""Unit tests for the text/voice matching (no media, no Premiere).   .venv/bin/python -m pytest tests"""
from pcb.assemble import assign_clips, content_tokens, find_phrase


def words(text, start=0.0, step=0.4):
    out, t = [], start
    for w in text.split():
        out.append({"w": "".join(c for c in w.lower() if c.isalnum() or c == "'"), "raw": w, "t": t, "e": t + step})
        t += step
    return out


VO = words("A small team reviews a new travel policy by trying it themselves. Everything works so the policy goes "
           "everywhere. Within a week a night shift worker can't book a late train and a contractor is "
           "locked out of the one booking application.")


def t_of(word, after=0.0):
    return next(w["t"] for w in VO if w["w"] == word and w["t"] >= after)


def test_numbers_match_spoken_form():
    assert "twentyfour" in content_tokens("Compare twenty-four combinations")
    assert "twentyfour" in content_tokens("gives you 24 combinations")


def test_paraphrased_bullet_found_where_spoken():
    t, score = find_phrase(VO, "Send the policy everywhere because everything works", after=0)
    assert score >= 0.6 and abs(t - t_of("everything")) < 0.01


def test_tight_cluster_beats_scattered_words():
    # "policy" appears early; the bullet should land on the later, tighter phrase
    t, _ = find_phrase(VO, "Contractor locked out of one application", after=0)
    assert abs(t - t_of("contractor")) < 0.01


def test_short_text_needs_full_match():
    t, _ = find_phrase(VO, "Determine how you:", after=0)
    assert t is None


def test_clips_follow_scenes_in_order():
    scenes = [{"title": "A week after the change", "name": "Hook", "ost": ["Scenario", "Review a new policy"]},
              {"title": "Purpose of reviews", "name": "Overview", "ost": ["Goal beyond proving it works"]}]
    clips = [["A week after the change", "Scenario", "Review a new policy"],
             ["A week after the change", "Issue"],
             ["Purpose of reviews", "Goal beyond proving it works"]]
    order, _ = assign_clips(clips, scenes)
    assert order == [0, 0, 1]
