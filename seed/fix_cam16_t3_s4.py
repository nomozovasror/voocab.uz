"""Cut Cambridge 16 Test 3 Part 4's audioscript by hand, from the page.

The reader could not do it after three attempts and a stronger model, and
the way it failed is the way it fails everywhere: a Part 4 is one speaker
for five minutes, and the book prints the markers down the margin of that
one speech. Two of this page's paragraphs carry THREE markers each — Q31,
Q32, Q33 in the second and Q36, Q37, Q38 in the sixth — and the reader
handed out one marker per paragraph instead, which slid every marker after
the first onto a paragraph that does not answer it, and then wrote the last
paragraph out three times to use up the ones it had left.

Cut here at the lines the margin marks, which is what the reader is asked
to do: one turn per marker, the text word for word off pages 113 and 114.
"""
import json
import pathlib

TURNS = pathlib.Path(
    "/Users/asrornomozov/Desktop/voocab.uz/seed/work/cam16-t3-s4/turns.json"
)

SPOKEN = [
    (None, "Good morning everyone. So today we're going to look at an "
           "important creative activity and that's hand knitting. Ancient "
           "knitted garments have been found in many different countries, "
           "showing that knitting is a global activity with a long history."),
    ("Q31", "When someone says the word 'knitting' we might well picture an "
            "elderly person – a grandmother perhaps – sitting by the fire "
            "knitting garments for themselves or other members of the family."),
    ("Q32", "It's a homely image, but one that may lead you to feel that "
            "knitting is an activity of the past – and, indeed, during the "
            "previous decade, it was one of the skills that was predicted to "
            "vanish from everyday life."),
    ("Q33", "For although humans have sewn and knitted their own clothing for "
            "a very long time, many of these craft-based skills went into "
            "decline when industrial machines took over – mainly because they "
            "were no longer passed down from one generation to another. "
            "However, that's all changing and interest in knitting classes in "
            "many countries is actually rising, as more and more people are "
            "seeking formal instruction in the skill. With that trend, we're "
            "also seeing an increase in the sales figures for knitting "
            "equipment."),
    ("Q34", "So why do people want to be taught to knit at a time when a "
            "machine can readily do the job for them? The answer is that "
            "knitting, as a handicraft, has numerous benefits for those doing "
            "it. Let's consider what some of these might be. While many people "
            "knitted garments in the past because they couldn't afford to buy "
            "clothes, it's still true today that knitting can be helpful if "
            "you're experiencing economic hardship."),
    ("Q35", "If you have several children who all need warm winter clothes, "
            "knitting may save you a lot of money. And the results of knitting "
            "your own clothes can be very rewarding, even though the skills "
            "you need to get going are really quite basic and the financial "
            "outlay is minimal."),
    (None, "But the more significant benefits in today's world are to do with "
           "well-being. In a world where it's estimated that we spend up to "
           "nine hours a day online, doing something with our hands that is "
           "craft-based makes us feel good. It releases us from the stress of "
           "a technological, fast-paced life."),
    ("__BREAK__", ""),
    (None, "Now, let's look back a bit to early knitting activities. In fact, "
           "no one really knows when knitting first began, but archaeological "
           "remains have disclosed plenty of information for us to think "
           "about."),
    ("Q36", "One of the interesting things about knitting is that the earliest "
            "pieces of clothing that have been found suggest that most of the "
            "items produced were round rather than flat."),
    ("Q37", "Discoveries from the 3rd and 4th centuries in Egypt show that "
            "things like socks and gloves, that were needed to keep hands and "
            "feet warm, were knitted in one piece using four or five needles. "
            "That's very different from most knitting patterns today, which "
            "only require two. What's more, the very first needles people used "
            "were hand carved out of wood and other natural materials, like "
            "bone, whereas today's needles are largely made of steel or "
            "plastic and make that characteristic clicking sound when "
            "someone's using them."),
    ("Q38", "Ancient people knitted using yarns made from linen, hemp, cotton "
            "and wool, and these were often very rough on the skin. The "
            "spinning wheel, which allowed people to make finer yarns and "
            "produce much greater quantities of them, led to the dominance of "
            "wool in the knitting industry – often favoured for its warmth."),
    ("Q39", "Another interesting fact about knitting is that because it was "
            "practised in so many parts of the world for so many purposes, "
            "regional differences in style developed. This visual identity has "
            "allowed researchers to match bits of knitted clothing that have "
            "been unearthed over time to the region from which the wearer came "
            "or the job that he or she did."),
    ("Q40", "As I've mentioned, knitting offered people from poor communities "
            "a way of making extra money while doing other tasks. For many "
            "centuries, it seems, men, women and children took every "
            "opportunity to knit, for example, while watching over sheep, "
            "walking to market or riding in boats. So, let's move on to take "
            "a …"),
]

turns = [
    {
        "speaker": "__BREAK__" if marker == "__BREAK__" else "SPEAKER",
        "text": text,
        "marker": None if marker in (None, "__BREAK__") else marker,
        "answer": None,
    }
    for marker, text in SPOKEN
]
TURNS.write_text(json.dumps(turns, indent=2, ensure_ascii=False))
print(f"{len(turns)} turns, markers "
      f"{[t['marker'] for t in turns if t['marker']]}")
