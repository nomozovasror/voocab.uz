"""A catalogue to develop the practice page against.

The learner side of ``/listening`` is mostly a set of judgements about data —
which part a material belongs to, how hard it turned out to be, whether there
is enough evidence to say so — and a database with one material in it can't
show any of them. This writes a library that can: fifteen materials across all
four parts, every question type the editor can build, and a spread of
difficulty bands that only exists because other people have answered them.

Not fixtures and not a migration. Nothing here is required for the app to run
and nothing here is truth — it is scaffolding for a developer's own database,
and it is removable in one command.

Usage (from ``backend/``)::

    uv run python -m scripts.seed_practice           # add it
    uv run python -m scripts.seed_practice --clean   # take it away again
    uv run python -m scripts.seed_practice --reset   # both, in that order

Everything it writes is owned by the five accounts in :data:`AUTHORS` and
:data:`LEARNERS` (all ``@seed.voocab.local``), which is how ``--clean`` knows
what is its to delete and how it leaves anything you authored yourself alone.

It refuses to run unless ``DEV_LOGIN_ENABLED`` is on, because that setting is
the one thing in the config that already means "this is a development
machine". ``--force`` overrides it, and you should be very sure.

**Audio is borrowed, never invented.** A fabricated ``AudioBlob`` would point
at bytes that aren't there, and every seeded material would open a player that
404s. Instead the longest recording already in the database is claimed by each
seeded author (an ``AudioAsset`` over a shared blob is exactly what the real
upload path creates for two people who upload the same file), so a seeded
material really plays. Where the database has no audio at all, the materials
are written without any — a row with no clock on it, which is a state the page
has to handle anyway.
"""

import argparse
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.attempt import Attempt, AttemptStatus
from app.models.collection import Collection, CollectionItem
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup
from app.models.user import User
from app.services import difficulty as difficulty_service

SEED_DOMAIN = "seed.voocab.local"

#: Who "wrote" the catalogue. Four rather than one so the byline on a row
#: means something and the avatar beside it has more than one colour to be.
AUTHORS = {
    "nodira": ("nodira@" + SEED_DOMAIN, "Nodira Karimova"),
    "otabek": ("otabek@" + SEED_DOMAIN, "Otabek Yusupov"),
    "malika": ("malika@" + SEED_DOMAIN, "Malika Rasulova"),
    "dilshod": ("dilshod@" + SEED_DOMAIN, "Dilshod Aliyev"),
}

#: The people whose answers make a material Easy or Hard. Difficulty is
#: measured over everybody (app/services/difficulty.py), so a band can only
#: exist if somebody other than you has sat the paper.
LEARNERS = [
    ("learner1@" + SEED_DOMAIN, "Sardor T."),
    ("learner2@" + SEED_DOMAIN, "Kamola I."),
    ("learner3@" + SEED_DOMAIN, "Jasur R."),
]

#: Proportion correct to aim at for each band, comfortably inside the
#: thresholds in ``app.services.difficulty`` rather than on them — a seed that
#: sat exactly on 0.75 would flip band on a rounding change.
BAND_RATE = {"easy": 0.88, "medium": 0.62, "hard": 0.34}

#: How many answers a band needs behind it. ``new`` is deliberately well under
#: the threshold — a catalogue where everything has been measured can't show
#: what "not enough evidence yet" looks like, and it has to stay under it after
#: the reader's own attempts are added on top.
BAND_ANSWERS = {"easy": 36, "medium": 30, "hard": 32, "new": 6}


# --- Group builders ---------------------------------------------------------
#
# One function per shape of question group, each returning the rows to write.
# They exist so the catalogue below reads as content rather than as schema:
# a completion task is a template and its answers, and that is all it should
# take to write one down.


def completion(
    type_: str,
    instructions: str,
    template: str,
    answers: list[list[str]],
    *,
    word_limit: int | None = None,
    options: list[str] | None = None,
) -> dict:
    """A gap-fill of any kind — form, notes, table, flow chart, summary.

    ``answers[i]`` is every phrasing accepted for gap ``i + 1``; a boxed
    summary passes ``options`` instead and its answers are letters.
    """
    config: dict = {"template": template}
    if options:
        config["options"] = options
    return {
        "type": type_,
        "instructions": instructions,
        "word_limit": word_limit,
        "config": config,
        "questions": [
            {"number": n, "correct_answers": accepted, "config": None}
            for n, accepted in enumerate(answers, start=1)
        ],
    }


def choice(
    instructions: str,
    items: list[tuple[str, list[str], list[str]]],
    *,
    per_question: int = 1,
) -> dict:
    """Multiple choice: each item carries its own prompt and options, and the
    group carries how many letters to pick."""
    return {
        "type": "multiple_choice",
        "instructions": instructions,
        "word_limit": None,
        "config": {"answers_per_question": per_question},
        "questions": [
            {
                "number": n,
                "correct_answers": correct,
                "config": {"prompt": prompt, "options": options},
            }
            for n, (prompt, options, correct) in enumerate(items, start=1)
        ],
    }


def matching(
    instructions: str,
    options: list[str],
    items: list[tuple[str, str]],
    *,
    allow_reuse: bool = False,
) -> dict:
    """One lettered box above a list of items answered from it."""
    return {
        "type": "matching",
        "instructions": instructions,
        "word_limit": None,
        "config": {"options": options, "allow_reuse": allow_reuse},
        "questions": [
            {"number": n, "correct_answers": [letter], "config": {"prompt": prompt}}
            for n, (prompt, letter) in enumerate(items, start=1)
        ],
    }


# --- The catalogue ----------------------------------------------------------
#
# Part numbers are 1-based here and stored 0-based, which is the one place the
# translation happens. Each material names the band it should end up in; the
# answers that produce it are generated at the bottom of this file.

CATALOGUE: list[dict] = [
    {
        "title": "Library Membership Enquiry",
        "author": "nodira",
        "band": "easy",
        "days_ago": 1,
        "parts": {
            1: [
                completion(
                    "form_completion",
                    "Complete the form below. Write ONE WORD AND/OR A NUMBER for each answer.",
                    "# Library membership form\n"
                    "Name | Helen {{1}}\n"
                    "Address | 42 {{2}} Road\n"
                    "Postcode | {{3}}\n"
                    "Occupation | {{4}}\n"
                    "\n"
                    "## Membership\n"
                    "Type of card | {{5}}\n"
                    "Annual fee | £ {{6}}",
                    [
                        ["Brookes", "brookes"],
                        ["Chapel", "chapel"],
                        ["LS7 4QD", "ls7 4qd"],
                        ["teacher"],
                        ["standard"],
                        ["25", "25.00"],
                    ],
                    word_limit=2,
                )
            ]
        },
    },
    {
        "title": "Booking a Sports Centre Class",
        "author": "otabek",
        "band": "medium",
        "days_ago": 3,
        "parts": {
            1: [
                completion(
                    "form_completion",
                    "Complete the form below. Write NO MORE THAN TWO WORDS for each answer.",
                    "# Class booking\n"
                    "Class | {{1}}\n"
                    "Day | Tuesdays\n"
                    "Time | starts at {{2}}\n"
                    "Room | the {{3}} studio",
                    [["badminton"], ["6.30", "6.30 pm", "half past six"], ["upper", "upstairs"]],
                    word_limit=2,
                ),
                completion(
                    "short_answer",
                    "Answer the questions below. Write NO MORE THAN THREE WORDS for each answer.",
                    "- What should members bring with them? {{1}}\n"
                    "- Where is the visitors' car park? {{2}}\n"
                    "- Who should late arrivals speak to? {{3}}",
                    [
                        ["a towel", "towel"],
                        ["behind the pool", "at the back"],
                        ["the receptionist", "reception"],
                    ],
                    word_limit=3,
                ),
            ]
        },
    },
    {
        "title": "Homestay Application",
        "author": "malika",
        "band": "new",
        "days_ago": 4,
        "parts": {
            1: [
                completion(
                    "note_completion",
                    "Complete the notes below. Write ONE WORD AND/OR A NUMBER for each answer.",
                    "## Homestay application\n"
                    "- Student wants a room from {{1}} September\n"
                    "- Prefers a family with no {{2}}\n"
                    "- Is allergic to {{3}}\n"
                    "- Can pay up to £ {{4}} a week\n"
                    "- Needs to be near the {{5}} line",
                    [["12", "12th"], ["pets", "animals"], ["cats", "cat"], ["140"], ["bus"]],
                    word_limit=1,
                )
            ]
        },
    },
    {
        "title": "Car Insurance Claim Call",
        "author": "dilshod",
        "band": "hard",
        "days_ago": 6,
        "parts": {
            1: [
                completion(
                    "form_completion",
                    "Complete the form below. Write ONE WORD AND/OR A NUMBER for each answer.",
                    "# Claim record\n"
                    "Policy number | {{1}}\n"
                    "Date of accident | {{2}} March\n"
                    "Location | junction of Mill Street and {{3}} Avenue\n"
                    "Damage | broken {{4}} and a dented door",
                    [["AC4471", "ac4471"], ["19", "19th"], ["Preston", "preston"], ["wing mirror", "mirror"]],
                    word_limit=2,
                ),
                completion(
                    "table_completion",
                    "Complete the table below. Write NO MORE THAN TWO WORDS for each answer.",
                    "+ Cover | Excess | Courtesy car\n"
                    "+ Basic | £ {{1}} | no\n"
                    "+ Standard | £250 | {{2}}\n"
                    "+ Premium | £100 | yes, for {{3}} days",
                    [["500"], ["yes"], ["21", "twenty-one"]],
                    word_limit=2,
                ),
            ]
        },
    },
    {
        "title": "Riverside Park Redevelopment",
        "author": "nodira",
        "band": "medium",
        "days_ago": 8,
        "parts": {
            2: [
                choice(
                    "Choose the correct letter, A, B or C.",
                    [
                        (
                            "The redevelopment was paid for mainly by",
                            ["the city council", "a national grant", "local businesses"],
                            ["b"],
                        ),
                        (
                            "The speaker says the old play area was",
                            ["too small", "unsafe", "rarely used"],
                            ["b"],
                        ),
                        (
                            "The new café will open in",
                            ["April", "June", "September"],
                            ["c"],
                        ),
                    ],
                ),
                completion(
                    "note_completion",
                    "Complete the notes below. Write ONE WORD ONLY for each answer.",
                    "## Getting there\n"
                    "- The main gate is opposite the {{1}}\n"
                    "- Cyclists should use the {{2}} entrance\n"
                    "- Dogs must be kept on a {{3}} near the pond",
                    [["library"], ["north", "northern"], ["lead", "leash"]],
                    word_limit=1,
                ),
            ]
        },
    },
    {
        "title": "Whitby Museum Tour",
        "author": "otabek",
        "band": "easy",
        "days_ago": 11,
        "parts": {
            2: [
                choice(
                    "Choose TWO letters, A–E.",
                    [
                        (
                            "Which TWO rooms have been restored this year?",
                            [
                                "the reading room",
                                "the great hall",
                                "the kitchen",
                                "the chapel",
                                "the stables",
                            ],
                            ["a", "d"],
                        ),
                        (
                            "Which TWO items came from the shipwreck?",
                            ["a compass", "a clock", "a sword", "a chest", "a map"],
                            ["a", "d"],
                        ),
                    ],
                    per_question=2,
                ),
                completion(
                    "note_completion",
                    "Complete the notes below. Write NO MORE THAN TWO WORDS for each answer.",
                    "## Practical details\n"
                    "- The tour lasts {{1}} minutes\n"
                    "- Photography is allowed except in the {{2}}\n"
                    "- The shop closes at {{3}}",
                    [["45", "forty-five"], ["chapel"], ["5.30", "5.30 pm"]],
                    word_limit=2,
                ),
            ]
        },
    },
    {
        "title": "Volunteering at the City Farm",
        "author": "malika",
        "band": "hard",
        "days_ago": 13,
        "parts": {
            2: [
                matching(
                    "Which task is done on each day? Choose FIVE answers from the box.",
                    [
                        "feeding the animals",
                        "repairing fences",
                        "school visits",
                        "the vegetable beds",
                        "the farm shop",
                        "cleaning the barn",
                    ],
                    [
                        ("Monday", "d"),
                        ("Tuesday", "c"),
                        ("Wednesday", "f"),
                        ("Thursday", "b"),
                        ("Friday", "e"),
                    ],
                ),
            ]
        },
    },
    {
        "title": "Tutorial: Renewable Energy Essay",
        "author": "dilshod",
        "band": "hard",
        "days_ago": 16,
        "parts": {
            3: [
                choice(
                    "Choose the correct letter, A, B or C.",
                    [
                        (
                            "What does the tutor think is wrong with the introduction?",
                            [
                                "It is too long.",
                                "It states no argument.",
                                "It repeats the title.",
                            ],
                            ["b"],
                        ),
                        (
                            "The students disagree about",
                            [
                                "how many sources to use",
                                "which sources are reliable",
                                "how to reference sources",
                            ],
                            ["b"],
                        ),
                        (
                            "The tutor suggests the case study should be",
                            ["shortened", "moved", "removed"],
                            ["b"],
                        ),
                    ],
                ),
                matching(
                    "What does the tutor say about each section? Choose FOUR answers from the box.",
                    [
                        "needs more evidence",
                        "is well argued",
                        "should be rewritten",
                        "is too descriptive",
                        "is off topic",
                    ],
                    [
                        ("Methodology", "a"),
                        ("Results", "b"),
                        ("Discussion", "d"),
                        ("Conclusion", "c"),
                    ],
                ),
            ]
        },
    },
    {
        "title": "Field Trip Planning Meeting",
        "author": "nodira",
        "band": "new",
        "days_ago": 18,
        "parts": {
            3: [
                matching(
                    "Who is responsible for each task? Choose FIVE answers from the box.",
                    ["Anna", "Ben", "Carla", "Dan", "the department"],
                    [
                        ("booking the minibus", "d"),
                        ("collecting consent forms", "a"),
                        ("the risk assessment", "e"),
                        ("the equipment list", "b"),
                        ("contacting the site", "c"),
                    ],
                    allow_reuse=True,
                ),
            ]
        },
    },
    {
        "title": "Dissertation Feedback Session",
        "author": "otabek",
        "band": "medium",
        "days_ago": 21,
        "parts": {
            3: [
                completion(
                    "sentence_completion",
                    "Complete the sentences below. Write NO MORE THAN TWO WORDS for each answer.",
                    "- The literature review should end with a clear {{1}}\n"
                    "- The supervisor wants the sample size raised to {{2}}\n"
                    "- The next draft is due at the end of {{3}}",
                    [["gap", "research gap"], ["60", "sixty"], ["term", "the term"]],
                    word_limit=2,
                ),
                choice(
                    "Choose the correct letter, A, B or C.",
                    [
                        (
                            "The student is most worried about",
                            ["the deadline", "the statistics", "the word count"],
                            ["b"],
                        ),
                        (
                            "The supervisor recommends reading",
                            ["a textbook chapter", "two recent papers", "a conference report"],
                            ["b"],
                        ),
                    ],
                ),
            ]
        },
    },
    {
        "title": "Lecture: The History of Salt",
        "author": "malika",
        "band": "easy",
        "days_ago": 24,
        "parts": {
            4: [
                completion(
                    "note_completion",
                    "Complete the notes below. Write ONE WORD ONLY for each answer.",
                    "## Salt in the ancient world\n"
                    "- Roman soldiers were sometimes paid in {{1}}\n"
                    "- Salt was carried across the Sahara by {{2}}\n"
                    "- In China it was first taxed in the {{3}} century\n"
                    "\n"
                    "## Preservation\n"
                    "- Salting removes {{4}} from food\n"
                    "- Cod was preserved on board {{5}}",
                    [["salt"], ["camel", "camels"], ["seventh", "7th"], ["water", "moisture"], ["ships", "boats"]],
                    word_limit=1,
                )
            ]
        },
    },
    {
        "title": "Lecture: Urban Beekeeping",
        "author": "dilshod",
        "band": "medium",
        "days_ago": 27,
        "parts": {
            4: [
                completion(
                    "summary_completion",
                    "Complete the summary using the list of words, A–F.",
                    "City bees often do better than rural ones because parks and gardens "
                    "flower for a longer {{1}}. The main risk to a rooftop hive is not "
                    "cold but {{2}}, and beginners are advised to start with a single "
                    "{{3}} rather than several.",
                    [["c"], ["a"], ["e"]],
                    options=["wind", "disease", "season", "traffic", "colony", "harvest"],
                )
            ]
        },
    },
    {
        "title": "Lecture: How Paper Is Recycled",
        "author": "nodira",
        "band": "hard",
        "days_ago": 30,
        "parts": {
            4: [
                completion(
                    "flow_chart_completion",
                    "Complete the flow chart below. Write ONE WORD ONLY for each answer.",
                    "> Paper is collected and sorted by {{1}}\n"
                    "> Mixed with water to make a {{2}}\n"
                    "> Ink is removed using {{3}}\n"
                    "> The fibres are pressed and {{4}}",
                    [["grade", "type"], ["pulp", "slurry"], ["soap", "chemicals"], ["dried"]],
                    word_limit=1,
                )
            ]
        },
    },
    {
        "title": "Practice Test 1 — Complete",
        "author": "otabek",
        "band": "medium",
        "days_ago": 34,
        # Ten questions a part, forty in all, because that is what a full
        # test is — a row reading "Full test · 4 parts · 13 questions" is a
        # row nobody believes.
        "parts": {
            1: [
                completion(
                    "form_completion",
                    "Complete the form below. Write ONE WORD AND/OR A NUMBER for each answer.",
                    "# Gym registration\n"
                    "Surname | {{1}}\n"
                    "Contact number | {{2}}\n"
                    "Email | {{3}}@webmail.com\n"
                    "Preferred class | {{4}}\n"
                    "Start date | {{5}} April\n"
                    "\n"
                    "## Membership\n"
                    "Length | {{6}} months\n"
                    "Monthly fee | £ {{7}}\n"
                    "Locker | number {{8}}\n"
                    "Induction with | {{9}}\n"
                    "Bring | a {{10}} and trainers",
                    [
                        ["Whitfield"],
                        ["07700 900412"],
                        ["h.whitfield", "hwhitfield"],
                        ["pilates"],
                        ["3", "3rd"],
                        ["12", "twelve"],
                        ["34", "34.00"],
                        ["27"],
                        ["Marco", "marco"],
                        ["towel"],
                    ],
                    word_limit=2,
                )
            ],
            2: [
                choice(
                    "Choose the correct letter, A, B or C.",
                    [
                        ("The festival began in", ["1985", "1995", "2005"], ["b"]),
                        ("Tickets are cheapest", ["online", "at the gate", "by phone"], ["a"]),
                        ("Parking is free for", ["all visitors", "campers", "nobody"], ["b"]),
                        ("The main stage closes at", ["10 pm", "11 pm", "midnight"], ["b"]),
                        ("Food stalls are found", ["by the river", "behind the stage", "at the entrance"], ["a"]),
                    ],
                ),
                completion(
                    "note_completion",
                    "Complete the notes below. Write ONE WORD ONLY for each answer.",
                    "## Getting to the site\n"
                    "- A free {{1}} runs from the station\n"
                    "- Campers should follow the {{2}} signs\n"
                    "- The nearest cash machine is in the {{3}}\n"
                    "- Lost property is kept at the {{4}} tent\n"
                    "- Take a {{5}} for the evening",
                    [["shuttle", "bus"], ["green"], ["village"], ["information", "info"], ["jacket", "coat"]],
                    word_limit=1,
                ),
            ],
            3: [
                matching(
                    "What does each speaker say about the project? Choose FIVE answers.",
                    [
                        "it was too ambitious",
                        "it ran late",
                        "it changed direction",
                        "it went well",
                        "it needed more people",
                        "it was under-funded",
                    ],
                    [("Sam", "b"), ("Priya", "c"), ("Tom", "d"), ("Ella", "a"), ("Nick", "f")],
                ),
                completion(
                    "sentence_completion",
                    "Complete the sentences below. Write NO MORE THAN TWO WORDS for each answer.",
                    "- The group met every {{1}} to review progress\n"
                    "- Most of the data came from a {{2}}\n"
                    "- The biggest delay was caused by the {{3}}\n"
                    "- They will present their work at the {{4}}\n"
                    "- The report must be submitted by {{5}}",
                    [
                        ["Thursday", "thursday"],
                        ["survey", "questionnaire"],
                        ["equipment", "software"],
                        ["conference"],
                        ["Friday", "friday"],
                    ],
                    word_limit=2,
                ),
            ],
            4: [
                completion(
                    "note_completion",
                    "Complete the notes below. Write ONE WORD ONLY for each answer.",
                    "## Coastal erosion\n"
                    "- Soft rock cliffs retreat by up to {{1}} metres a year\n"
                    "- Sea walls shift the problem {{2}} along the coast\n"
                    "- Planting {{3}} stabilises the dunes\n"
                    "- Groynes trap {{4}} as it moves along the beach\n"
                    "- Rock armour is the cheapest {{5}} defence\n"
                    "\n"
                    "## Managed retreat\n"
                    "- Land is allowed to {{6}}\n"
                    "- New {{7}} habitat forms behind the old wall\n"
                    "- Farmers receive {{8}} for the lost fields\n"
                    "- The approach is unpopular with {{9}}\n"
                    "- Long term it costs the least to {{10}}",
                    [
                        ["2", "two"],
                        ["further", "down"],
                        ["grass", "marram"],
                        ["sand", "sediment"],
                        ["sea"],
                        ["flood"],
                        ["marsh", "saltmarsh"],
                        ["compensation", "payment"],
                        ["residents", "locals"],
                        ["maintain"],
                    ],
                    word_limit=1,
                )
            ],
        },
    },
    {
        "title": "Practice Test 2 — Complete",
        "author": "malika",
        "band": "hard",
        "days_ago": 38,
        "parts": {
            1: [
                completion(
                    "note_completion",
                    "Complete the notes below. Write ONE WORD AND/OR A NUMBER for each answer.",
                    "## Removals enquiry\n"
                    "- Moving on {{1}} May\n"
                    "- Two bedrooms plus a {{2}}\n"
                    "- Needs boxes delivered {{3}} days before\n"
                    "- Current address: {{4}} Street\n"
                    "- New address is above a {{5}}\n"
                    "- No lift, so everything goes up {{6}} flights\n"
                    "- Piano to be moved by a {{7}}\n"
                    "- Quote of £ {{8}} including packing\n"
                    "- Deposit of {{9}} per cent\n"
                    "- Contact: ask for {{10}}",
                    [
                        ["16", "16th"],
                        ["study", "office"],
                        ["4", "four"],
                        ["Alma", "alma"],
                        ["bakery", "shop"],
                        ["3", "three"],
                        ["specialist"],
                        ["680"],
                        ["20", "twenty"],
                        ["Dawn", "dawn"],
                    ],
                    word_limit=2,
                )
            ],
            2: [
                completion(
                    "table_completion",
                    "Complete the table below. Write NO MORE THAN TWO WORDS for each answer.",
                    "+ Walk | Distance | Difficulty | Starts\n"
                    "+ Lakeside | {{1}} km | easy | {{2}}\n"
                    "+ Ridge path | 9 km | {{3}} | 9.30 am\n"
                    "+ Old quarry | 12 km | {{4}} | {{5}}\n"
                    "+ Woodland | {{6}} km | easy | 2 pm",
                    [
                        ["5", "five"],
                        ["10 am", "10am"],
                        ["moderate"],
                        ["difficult", "hard"],
                        ["8 am", "8am"],
                        ["7", "seven"],
                    ],
                    word_limit=2,
                ),
                choice(
                    "Choose the correct letter, A, B or C.",
                    [
                        ("Walkers should book", ["a week ahead", "the day before", "on arrival"], ["b"]),
                        ("The guide recommends bringing", ["a map", "a packed lunch", "walking poles"], ["b"]),
                        ("Dogs are allowed", ["on all walks", "on two walks", "on no walks"], ["b"]),
                        ("In bad weather the walks are", ["cancelled", "shortened", "moved indoors"], ["b"]),
                    ],
                ),
            ],
            3: [
                choice(
                    "Choose the correct letter, A, B or C.",
                    [
                        (
                            "The students chose the topic because",
                            ["it is original", "there is data available", "the tutor suggested it"],
                            ["b"],
                        ),
                        ("They will present their findings using", ["a poster", "slides", "a handout"], ["a"]),
                        ("The main problem with the first survey was", ["its length", "its wording", "its timing"], ["c"]),
                        ("They decided to interview", ["students", "staff", "both"], ["c"]),
                        ("The tutor offers to help with", ["the analysis", "the design", "the writing"], ["a"]),
                    ],
                ),
                matching(
                    "What does each student agree to do? Choose FIVE answers.",
                    [
                        "write the introduction",
                        "run the interviews",
                        "make the slides",
                        "check the references",
                        "analyse the numbers",
                    ],
                    [("Ana", "b"), ("Ben", "e"), ("Chen", "a"), ("Dara", "c"), ("Eve", "d")],
                ),
            ],
            4: [
                completion(
                    "summary_completion",
                    "Complete the summary below. Write ONE WORD ONLY for each answer.",
                    "Early clocks relied on the flow of water, which made them "
                    "inaccurate in cold {{1}}. The pendulum, introduced in the "
                    "seventeenth century, cut the daily error to a few {{2}}, and "
                    "made accurate {{3}} at sea possible for the first time. "
                    "Marine chronometers had to survive both the motion of a ship "
                    "and changes in {{4}}, which is why Harrison used two metals "
                    "with different rates of {{5}}. The prize was eventually paid "
                    "only after a voyage to {{6}}, and within a century every naval "
                    "{{7}} carried one. Quartz replaced the mechanism in the "
                    "{{8}}, and today the standard is kept by counting the "
                    "vibrations of an {{9}} of caesium, accurate to a second every "
                    "few million {{10}}.",
                    [
                        ["weather"],
                        ["seconds"],
                        ["navigation"],
                        ["temperature"],
                        ["expansion"],
                        ["Jamaica", "jamaica"],
                        ["vessel", "ship"],
                        ["1970s", "seventies"],
                        ["atom"],
                        ["years"],
                    ],
                    word_limit=1,
                )
            ],
        },
    },
    # --- Six shorter papers ------------------------------------------------
    #
    # One task group each rather than two, and that is what they are for: a
    # catalogue of fifteen long papers cannot fill a collection of sixteen,
    # and the courses list has a "Long (16+)" band that would otherwise be a
    # menu option nobody could ever see. They are also what makes a Part 1
    # drill or a lecture set a real course rather than four papers that
    # happen to share a number.
    {
        "title": "Booking a Taxi to the Airport",
        "author": "nodira",
        "band": "easy",
        "days_ago": 26,
        "parts": {
            1: [
                completion(
                    "form_completion",
                    "Complete the booking below. Write ONE WORD AND/OR A NUMBER for each answer.",
                    "# Airport transfer\n"
                    "Name | Mr {{1}}\n"
                    "Pick-up | {{2}} Street\n"
                    "Date | {{3}} March\n"
                    "Time | {{4}} am\n"
                    "Passengers | {{5}}\n"
                    "Fare quoted | £ {{6}}",
                    [
                        ["Brennan"],
                        ["Hillcrest"],
                        ["14", "14th", "fourteenth"],
                        ["5.45", "5:45"],
                        ["3", "three"],
                        ["38", "38.00"],
                    ],
                    word_limit=1,
                )
            ]
        },
    },
    {
        "title": "Registering at the Health Centre",
        "author": "malika",
        "band": "medium",
        "days_ago": 28,
        "parts": {
            1: [
                completion(
                    "form_completion",
                    "Complete the form below. Write ONE WORD AND/OR A NUMBER for each answer.",
                    "# New patient registration\n"
                    "Surname | {{1}}\n"
                    "Date of birth | {{2}} 1998\n"
                    "Previous doctor | Dr {{3}}\n"
                    "Allergies | {{4}}\n"
                    "Preferred day | {{5}}\n"
                    "Registration fee | £ {{6}}",
                    [
                        ["Whitcombe"],
                        ["9 July", "9th July"],
                        ["Ahmed"],
                        ["penicillin"],
                        ["Thursday"],
                        ["0", "nothing", "free"],
                    ],
                    word_limit=1,
                )
            ]
        },
    },
    {
        "title": "Enquiring About a Cookery Course",
        "author": "otabek",
        "band": "medium",
        "days_ago": 30,
        "parts": {
            1: [
                completion(
                    "note_completion",
                    "Complete the notes below. Write NO MORE THAN TWO WORDS AND/OR A NUMBER for each answer.",
                    "## Evening cookery course\n"
                    "- Runs for {{1}} weeks\n"
                    "- Classes start at {{2}}\n"
                    "- Held in the {{3}} building\n"
                    "- Bring your own {{4}}\n"
                    "- Deposit of {{5}} is not refundable\n"
                    "- Ask for {{6}} on arrival",
                    [
                        ["8", "eight"],
                        ["6.30", "6:30", "6.30 pm"],
                        ["annexe", "annex"],
                        ["apron"],
                        ["£25", "25"],
                        ["Fiona"],
                    ],
                    word_limit=2,
                )
            ]
        },
    },
    {
        "title": "Guided Walk on the Coast Path",
        "author": "dilshod",
        "band": "easy",
        "days_ago": 32,
        "parts": {
            2: [
                completion(
                    "note_completion",
                    "Complete the notes below. Write NO MORE THAN TWO WORDS for each answer.",
                    "## Saturday coast walk\n"
                    "- Meet by the {{1}} at the harbour\n"
                    "- The path is closed near the {{2}}\n"
                    "- Wear boots — the section past the {{3}} is wet\n"
                    "- Lunch stop at the old {{4}}\n"
                    "- Back by {{5}}",
                    [
                        ["lifeboat station"],
                        ["quarry"],
                        ["stream", "brook"],
                        ["lighthouse"],
                        ["4.15", "4:15"],
                    ],
                    word_limit=2,
                )
            ]
        },
    },
    {
        "title": "Lecture: Why Cities Flood",
        "author": "nodira",
        "band": "hard",
        "days_ago": 34,
        "parts": {
            4: [
                completion(
                    "note_completion",
                    "Complete the notes below. Write ONE WORD ONLY for each answer.",
                    "## Urban flooding\n"
                    "- Rain cannot soak through {{1}} surfaces\n"
                    "- Victorian drains were built for a smaller {{2}}\n"
                    "- Rivers were put into {{3}} beneath the streets\n"
                    "- The worst damage follows a short, intense {{4}}\n"
                    "- New schemes hold water in the {{5}} instead",
                    [
                        ["hard", "paved"],
                        ["population"],
                        ["culverts", "pipes"],
                        ["storm"],
                        ["park", "parks"],
                    ],
                    word_limit=1,
                )
            ]
        },
    },
    {
        "title": "Seminar: Choosing a Research Question",
        "author": "malika",
        "band": "new",
        "days_ago": 36,
        "parts": {
            3: [
                choice(
                    "Choose the correct letter, A, B or C.",
                    [
                        (
                            "What does the tutor say about the first draft question?",
                            [
                                "it is too broad to answer",
                                "it repeats an earlier study",
                                "it needs more sources",
                            ],
                            ["a"],
                        ),
                        (
                            "Why does she suggest narrowing it to one city?",
                            [
                                "the data is easier to obtain",
                                "the comparison would be unfair",
                                "the deadline is close",
                            ],
                            ["a"],
                        ),
                        (
                            "What should the students do before the next meeting?",
                            [
                                "write the method section",
                                "read two of the papers listed",
                                "email their supervisor",
                            ],
                            ["b"],
                        ),
                    ],
                )
            ]
        },
    },
]


# --- The collections --------------------------------------------------------
#
# Enough of them, and varied enough, that every state the courses list can be
# in is on the screen at once: in progress, untouched and finished; short,
# medium and long; a part drill, a lecture set and a pair of mock tests; one
# with no summary at all and one with a title long enough to be cut off.
#
# ``titles`` names materials by their catalogue title rather than by index, so
# reordering the catalogue above cannot silently rewrite a course. A title
# that does not match is a loud failure rather than a quiet one — see
# :func:`_write_collections`.
#
# ``sit`` is how many of the course the dev account has already worked
# through, counted from the start, which is what puts it in one of the three
# states. ``None`` means "leave it to whatever they have really done", which
# is the honest state for a course made of papers they may have sat anyway.

COLLECTIONS: list[dict] = [
    {
        "title": "Part 1 from scratch",
        "author": "nodira",
        "summary": "Six form-filling papers in the order they get harder. Start here if Part 1 is where the marks go.",
        "sit": 2,
        "titles": [
            "Library Membership Enquiry",
            "Booking a Taxi to the Airport",
            "Homestay Application",
            "Registering at the Health Centre",
            "Booking a Sports Centre Class",
            "Car Insurance Claim Call",
        ],
    },
    {
        "title": "Two full mock tests",
        "author": "dilshod",
        "summary": "Sit them under exam conditions, a week apart.",
        "sit": 2,
        "titles": ["Practice Test 1 — Complete", "Practice Test 2 — Complete"],
    },
    {
        "title": "The lecture set",
        "author": "malika",
        "summary": "Part 4 only. One long turn each, no conversation to lean on.",
        "sit": 0,
        "titles": [
            "Lecture: The History of Salt",
            "Lecture: Urban Beekeeping",
            "Lecture: How Paper Is Recycled",
            "Lecture: Why Cities Flood",
        ],
    },
    {
        # No summary. A course is allowed to be just a name, and the row and
        # the card both have to look deliberate when it is.
        "title": "Maps and matching",
        "author": "otabek",
        "sit": 1,
        "titles": [
            "Riverside Park Redevelopment",
            "Volunteering at the City Farm",
            "Whitby Museum Tour",
        ],
    },
    {
        # Long enough to be cut off in every place it appears. Real courses do
        # have names like this, and a design that has only been looked at with
        # short ones is a design that has not been looked at.
        "title": "Everything, in the order I would work through it with a student preparing over eight weeks",
        "author": "nodira",
        "summary": "The whole library, sequenced. Two papers a week, mock tests at the end.",
        "sit": 3,
        "titles": [
            "Library Membership Enquiry",
            "Booking a Taxi to the Airport",
            "Homestay Application",
            "Registering at the Health Centre",
            "Booking a Sports Centre Class",
            "Car Insurance Claim Call",
            "Enquiring About a Cookery Course",
            "Whitby Museum Tour",
            "Guided Walk on the Coast Path",
            "Riverside Park Redevelopment",
            "Volunteering at the City Farm",
            "Field Trip Planning Meeting",
            "Tutorial: Renewable Energy Essay",
            "Dissertation Feedback Session",
            "Seminar: Choosing a Research Question",
            "Lecture: The History of Salt",
            "Lecture: Urban Beekeeping",
            "Lecture: How Paper Is Recycled",
            "Lecture: Why Cities Flood",
            "Practice Test 1 — Complete",
            "Practice Test 2 — Complete",
        ],
    },
    {
        # Resolved at seed time from what the reader has NOT sat, rather than
        # named. `sit: 0` is not enough to produce an untouched course: the
        # dev account has its own history over most of the catalogue, so a
        # course the seed never sat on their behalf still comes out half done.
        # This is the only way to guarantee the "Not started" state exists,
        # and the summary is literally true of it.
        "title": "New this month",
        "author": "otabek",
        "summary": "The most recent papers, none of which you have sat.",
        "fresh": 4,
        "titles": [],
    },
    {
        "title": "Just the tutorials",
        "author": "dilshod",
        "summary": "Part 3. Three or four voices, and the answer is usually what somebody objects to.",
        "sit": 0,
        "titles": [
            "Tutorial: Renewable Energy Essay",
            "Field Trip Planning Meeting",
            "Dissertation Feedback Session",
            "Seminar: Choosing a Research Question",
        ],
    },
    {
        # Left unpublished. The studio list has a draft state and a blocker
        # line, and neither can be looked at against a database where every
        # course is finished.
        "title": "Weak spots — Part 2 (draft)",
        "author": "otabek",
        "summary": "Half built. Not published.",
        "draft": True,
        "sit": 0,
        "titles": ["Whitby Museum Tour"],
    },
]


# --- Writing it ------------------------------------------------------------


async def _get_or_create_user(session, email: str, name: str) -> User:
    user = (await session.exec(select(User).where(User.email == email))).first()
    if user is not None:
        return user
    user = User(email=email, display_name=name)
    session.add(user)
    await session.flush()
    return user


async def _borrowed_audio(session) -> AudioBlob | None:
    """The longest ready recording already in this database, if there is one.

    Longest because a full test is cut into four parts against it, and a
    six-second clip cut four ways is four parts of nothing.
    """
    blobs = (
        await session.exec(
            select(AudioBlob).where(AudioBlob.transcript_status == "ready")
        )
    ).all()
    ready = [b for b in blobs if b.duration_ms]
    if not ready:
        return None
    return max(ready, key=lambda b: b.duration_ms or 0)


async def _claim_audio(session, owner_id: uuid.UUID, blob: AudioBlob) -> AudioAsset:
    """This author's claim on the shared blob — one asset per owner, which is
    what ``UNIQUE(owner_id, blob_id)`` allows and what the upload path does
    when two people upload the same file."""
    existing = (
        await session.exec(
            select(AudioAsset).where(
                AudioAsset.owner_id == owner_id, AudioAsset.blob_id == blob.id
            )
        )
    ).first()
    if existing is not None:
        return existing
    asset = AudioAsset(owner_id=owner_id, blob_id=blob.id)
    session.add(asset)
    await session.flush()
    return asset


def _part_ranges(part_numbers: list[int], duration_ms: int | None) -> dict[int, tuple[int, int] | None]:
    """Where each part sits in the recording.

    A single-part material spans the whole clip, which is what NULL means on
    ``Part`` — so only a multi-part material gets ranges, and it gets equal
    slices. They are not where the parts really are (there is one recording
    being reused by fifteen materials), but they put a boundary marker in the
    take player, which is the thing being developed against.
    """
    if duration_ms is None or len(part_numbers) < 2:
        return {n: None for n in part_numbers}
    step = duration_ms // len(part_numbers)
    return {
        n: (i * step, (i + 1) * step if i < len(part_numbers) - 1 else duration_ms)
        for i, n in enumerate(part_numbers)
    }


async def _write_material(session, spec: dict, author: User, blob: AudioBlob | None) -> dict:
    """One material, its parts, groups and questions.

    Returns the question ids grouped by part number, which is what the attempt
    generator needs to make the statistics panel say anything true.
    """
    asset = await _claim_audio(session, author.id, blob) if blob else None
    material = Material(
        author_id=author.id,
        type="listening",
        title=spec["title"],
        visibility="public",
        audio_asset_id=asset.id if asset else None,
        created_at=datetime.now(timezone.utc) - timedelta(days=spec["days_ago"]),
    )
    session.add(material)
    await session.flush()

    part_numbers = sorted(spec["parts"])
    ranges = _part_ranges(part_numbers, blob.duration_ms if blob else None)

    questions_by_part: dict[int, list[uuid.UUID]] = {}
    for part_number in part_numbers:
        span = ranges[part_number]
        part = Part(
            material_id=material.id,
            # 0-based on the row, 1-based everywhere a person reads it. The
            # index IS the part number minus one — that is how a material
            # about Part 3 alone is still Part 3 (see the editor's picker).
            order_index=part_number - 1,
            title=f"Part {part_number}",
            audio_start_ms=span[0] if span else None,
            audio_end_ms=span[1] if span else None,
        )
        session.add(part)
        await session.flush()

        for order_index, group_spec in enumerate(spec["parts"][part_number]):
            group = QuestionGroup(
                part_id=part.id,
                order_index=order_index,
                type=group_spec["type"],
                instructions=group_spec["instructions"],
                word_limit=group_spec["word_limit"],
                config=group_spec["config"],
            )
            session.add(group)
            await session.flush()
            for q in group_spec["questions"]:
                question = Question(
                    group_id=group.id,
                    number=q["number"],
                    correct_answers=q["correct_answers"],
                    config=q["config"],
                )
                session.add(question)
                await session.flush()
                questions_by_part.setdefault(part_number, []).append(question.id)

    return {"material": material, "questions_by_part": questions_by_part}


#: The shapes a wrong answer comes in, cycled through so the seeded mistakes
#: fall into the classifier's categories in roughly the proportions a real
#: candidate produces — spelling most, then not hearing it at all, then the
#: rest. Without this every seeded mistake was the literal string "seeded",
#: which classifies as "wrong answer" and makes the panel that exists to tell
#: those apart look like it can't.
WRONG_SHAPES = (
    "spelling",
    "missed",
    "spelling",
    "wrong",
    "spelling",
    "plural",
    "missed",
    "wrong",
    "spelling",
    "format",
)


def _wrong_answer(correct: str, shape: str) -> str:
    """A plausible wrong version of ``correct``, of the given shape."""
    if shape == "missed":
        return ""
    if shape == "plural":
        return correct + "s"
    if shape == "format":
        # A number written the other way round, or with a currency mark on it.
        return f"£{correct}" if correct[:1].isdigit() else f"the {correct}"
    if shape == "spelling" and len(correct) >= 5:
        # Two neighbouring letters swapped — the commonest typing slip there
        # is, and a transposition rather than a substitution so it stays one
        # edit away under the classifier's Damerau distance.
        i = len(correct) // 2
        return correct[:i] + correct[i + 1] + correct[i] + correct[i + 2 :]
    return "something else"


async def _submit(
    session,
    *,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    question_ids: list[uuid.UUID],
    answered: int,
    correct: int,
    days_ago: int,
    minutes: int = 9,
) -> None:
    """One submitted attempt and the per-question rows under it.

    Written straight to the tables rather than through the grading service on
    purpose: the point is to produce a *known* tally — 22 answers, 12 right —
    and going through grading would mean inventing answer strings that happen
    to score that.
    """
    if answered <= 0 or not question_ids:
        return
    # The real accepted answers, so a seeded mistake can be a plausible
    # mis-typing of the thing it was meant to be.
    answers: dict[uuid.UUID, str] = {}
    for question_id in set(question_ids):
        question = await session.get(Question, question_id)
        if question and question.correct_answers:
            answers[question_id] = str(question.correct_answers[0])
    submitted = datetime.now(timezone.utc) - timedelta(days=days_ago)
    attempt = Attempt(
        user_id=user_id,
        material_id=material_id,
        status=AttemptStatus.SUBMITTED,
        score=correct,
        total_questions=answered,
        started_at=submitted - timedelta(minutes=minutes),
        submitted_at=submitted,
        time_spent_ms=minutes * 60_000,
    )
    session.add(attempt)
    await session.flush()
    for i in range(answered):
        question_id = question_ids[i % len(question_ids)]
        expected = answers.get(question_id, "answer")
        right = ((i + 1) * correct) // answered != (i * correct) // answered
        session.add(
            QuestionAttempt(
                attempt_id=attempt.id,
                question_id=question_id,
                given_answer=(
                    expected
                    if right
                    else _wrong_answer(expected, WRONG_SHAPES[i % len(WRONG_SHAPES)])
                ),
                # Exactly `correct` of them, spread evenly rather than the
                # first N in a row — a run of right answers followed by a run
                # of wrong ones would give every per-question breakdown a
                # pattern that isn't there. Written as the difference between
                # two integer divisions because that lands the trues at even
                # intervals and still totals exactly `correct`, whatever the
                # ratio; the obvious `i % k` version silently produced 100%
                # whenever the attempt happened to cover each question once.
                is_correct=right,
            )
        )


async def _crowd(session, learners: list[User], written: list[dict]) -> None:
    """The answers that give each material its band.

    Spread over three learners rather than piled onto one, because a band
    resting on one person's morning is exactly what the evidence threshold in
    ``app.services.difficulty`` exists to refuse.
    """
    for index, row in enumerate(written):
        band = row["spec"]["band"]
        total = BAND_ANSWERS[band]
        rate = BAND_RATE.get(band, 0.5)
        all_questions = [q for qs in row["questions_by_part"].values() for q in qs]
        if not all_questions:
            continue
        share = max(total // len(learners), 1)
        for offset, learner in enumerate(learners):
            answered = share if offset < len(learners) - 1 else total - share * (len(learners) - 1)
            await _submit(
                session,
                user_id=learner.id,
                material_id=row["material"].id,
                question_ids=all_questions,
                answered=answered,
                correct=round(answered * rate),
                days_ago=(index + offset) % 20 + 1,
            )


async def _own_history(session, me: User, written: list[dict]) -> None:
    """The reader's own history, shaped so the panel beside the list has
    something to say and something to refuse to say.

    One part is answered well, one badly and one barely — so the panel shows
    all three of its tones and its refusal in the same screenshot. Part 3 is
    the badly-answered one, which makes it the weakest area and gives the
    panel's one action something to point at; Part 2 is deliberately left
    under the evidence threshold, because a dash and a muted row is a state
    the page has to show and a seed where every row has a bar can't show it.

    Whatever attempts you have made yourself are counted alongside these, so
    a part you have really practised will not read exactly as planned here.
    That is the data being honest rather than the seed being wrong.
    """
    # part, accuracy, how many materials, how many times each. Few materials
    # sat twice rather than many sat once, so most of the catalogue stays
    # unsat — a "Not done" filter over a library you have finished is a filter
    # with nothing to do — and so the row's "2 tries" has somewhere to appear.
    # part, accuracy, how many materials, how many times each.
    #
    # Eleven materials between them, because the trend card wants ten first
    # attempts before it will draw a line and a seed that stops at nine is a
    # seed that can't show the card it was written for. Two of them are sat
    # twice, so first-try and best-of averages are different numbers.
    plan = [
        (4, 0.88, 4, 1),
        (1, 0.81, 3, 2),
        (3, 0.52, 3, 2),
        (2, 0.57, 1, 1),
    ]
    for part_number, rate, material_count, tries in plan:
        taken = 0
        for index, row in enumerate(written):
            questions = row["questions_by_part"].get(part_number)
            if not questions or taken >= material_count:
                continue
            taken += 1
            for attempt_number in range(tries):
                # The second sitting goes better than the first, which is what
                # a "best score" column is for — capped short of perfect, so
                # a six-question paper doesn't round its way to a row of
                # 100%s and make the column look broken.
                accuracy = rate if attempt_number == 0 else min(rate + 0.15, 0.9)
                await _submit(
                    session,
                    user_id=me.id,
                    material_id=row["material"].id,
                    question_ids=questions,
                    answered=len(questions),
                    correct=round(len(questions) * accuracy),
                    days_ago=(index + 2) * 2 - attempt_number,
                    minutes=7 + index,
                )


async def seed() -> None:
    async with async_session_factory() as session:
        authors = {
            key: await _get_or_create_user(session, email, name)
            for key, (email, name) in AUTHORS.items()
        }
        learners = [
            await _get_or_create_user(session, email, name) for email, name in LEARNERS
        ]
        blob = await _borrowed_audio(session)
        if blob is None:
            print(
                "No ready audio in this database — seeding materials without a "
                "recording (rows will have no clock, which is a state the page "
                "handles)."
            )

        written = []
        for spec in CATALOGUE:
            row = await _write_material(session, spec, authors[spec["author"]], blob)
            written.append({**row, "spec": spec})

        await _crowd(session, learners, written)

        # Whoever is logged in locally. The dev account is the one the page is
        # actually looked at as, so its history is what fills the panel.
        me = (
            await session.exec(select(User).where(User.email == "dev@voocab.local"))
        ).first()
        if me is not None:
            await _own_history(session, me, written)
        else:
            print(
                "No dev@voocab.local user — the catalogue is seeded but the "
                "statistics panel will show the new-learner state. Sign in "
                "once with Dev login, then re-run with --reset."
            )

        await _write_collections(session, authors, written, me)

        await session.commit()

        # The bands are a projection now, refilled by the worker on a timer
        # (app/services/difficulty.py). A seed that stopped at the attempts
        # would leave every material reading "New" until that timer next
        # fired — a catalogue seeded specifically to show four difficulty
        # bands, showing one, on a dev box where the worker is very often not
        # running at all.
        written_count = await difficulty_service.recompute(session)
        print(f"Seeded {len(written)} materials by {len(authors)} authors.")
        print(f"Difficulty computed for {written_count} materials.")


async def _write_collections(session, authors: dict, written: list[dict], me) -> None:
    """The courses, and the reader's way into them.

    Materials are looked up by title and a miss is fatal rather than skipped:
    a course quietly one paper short is exactly the sort of seed bug that gets
    mistaken for a UI bug, and it is only ever caused by a typo here.

    Progress is not written. It is counted from attempts
    (app/services/collections.py), so a course is "in progress" because the
    dev account has actually sat the first two of its papers — which is also
    why ``sit`` submits attempts rather than setting a number anywhere.
    """
    by_title = {row["material"].title: row for row in written}

    # What the reader has already sat, so a course can be built out of what
    # they have not. Read after `_own_history` has run, which is why the
    # collections are written last.
    sat: set = set()
    if me is not None:
        sat = set(
            (
                await session.exec(
                    select(Attempt.material_id).where(
                        Attempt.user_id == me.id,
                        Attempt.status == AttemptStatus.SUBMITTED,
                    )
                )
            ).all()
        )

    for spec in COLLECTIONS:
        titles = list(spec["titles"])
        if spec.get("fresh"):
            titles = [
                row["material"].title
                for row in written
                if row["material"].id not in sat
            ][: spec["fresh"]]
            if len(titles) < 2:
                print(
                    f"Only {len(titles)} unsat material(s) left — "
                    f"{spec['title']!r} will not show the untouched state."
                )

        missing = [t for t in titles if t not in by_title]
        if missing:
            raise SystemExit(
                f"Collection {spec['title']!r} names materials that are not in "
                f"the catalogue: {missing}"
            )

        collection = Collection(
            author_id=authors[spec["author"]].id,
            title=spec["title"],
            summary=spec.get("summary", ""),
            visibility="private" if spec.get("draft") else "public",
        )
        session.add(collection)
        await session.commit()
        await session.refresh(collection)

        for index, title in enumerate(titles):
            session.add(
                CollectionItem(
                    collection_id=collection.id,
                    material_id=by_title[title]["material"].id,
                    order_index=index,
                )
            )
        await session.commit()

        # What puts the course in one of its three states, done the only way
        # that is true: by sitting the papers.
        if me is None:
            continue
        for title in titles[: spec.get("sit") or 0]:
            row = by_title[title]
            questions = [q for qs in row["questions_by_part"].values() for q in qs]
            if not questions:
                continue
            await _submit(
                session,
                user_id=me.id,
                material_id=row["material"].id,
                question_ids=questions,
                answered=len(questions),
                correct=round(len(questions) * 0.7),
                days_ago=5,
            )
            # Kept current as we go: a later course asking for material the
            # reader has not sat has to know about the papers this loop has
            # just sat on their behalf.
            sat.add(row["material"].id)

    print(f"Seeded {len(COLLECTIONS)} collections.")


async def clean() -> None:
    """Everything the seed wrote, and nothing else.

    Found by author rather than by a marker in the title, so the titles can
    read like real material. Attempts go first, then questions, groups, parts,
    the materials themselves, the borrowed audio claims, and finally the
    accounts — the same order the delete constraints demand everywhere else in
    this codebase.
    """
    async with async_session_factory() as session:
        emails = [email for email, _ in AUTHORS.values()] + [e for e, _ in LEARNERS]
        users = (await session.exec(select(User).where(User.email.in_(emails)))).all()  # type: ignore[attr-defined]
        author_ids = [u.id for u in users]
        if not author_ids:
            print("Nothing seeded here.")
            return

        # Collections first: they point at the materials, so they have to
        # stop pointing before the materials can go. Their items go with them
        # at the database level, but the ORM is happier being told.
        collections = (
            await session.exec(
                select(Collection).where(Collection.author_id.in_(author_ids))  # type: ignore[attr-defined]
            )
        ).all()
        for collection in collections:
            for item in (
                await session.exec(
                    select(CollectionItem).where(
                        CollectionItem.collection_id == collection.id
                    )
                )
            ).all():
                await session.delete(item)
            await session.flush()
            await session.delete(collection)
        await session.flush()

        materials = (
            await session.exec(
                select(Material).where(Material.author_id.in_(author_ids))  # type: ignore[attr-defined]
            )
        ).all()

        for material in materials:
            attempts = (
                await session.exec(
                    select(Attempt).where(Attempt.material_id == material.id)
                )
            ).all()
            for attempt in attempts:
                for qa in (
                    await session.exec(
                        select(QuestionAttempt).where(
                            QuestionAttempt.attempt_id == attempt.id
                        )
                    )
                ).all():
                    await session.delete(qa)
            await session.flush()
            for attempt in attempts:
                await session.delete(attempt)
            await session.flush()

            for part in (
                await session.exec(select(Part).where(Part.material_id == material.id))
            ).all():
                groups = (
                    await session.exec(
                        select(QuestionGroup).where(QuestionGroup.part_id == part.id)
                    )
                ).all()
                for group in groups:
                    for question in (
                        await session.exec(
                            select(Question).where(Question.group_id == group.id)
                        )
                    ).all():
                        await session.delete(question)
                await session.flush()
                for group in groups:
                    await session.delete(group)
                await session.flush()
                await session.delete(part)
            await session.flush()
            await session.delete(material)
        await session.flush()

        # The claims only — never the blob, which was here first and is
        # somebody else's recording.
        for asset in (
            await session.exec(
                select(AudioAsset).where(AudioAsset.owner_id.in_(author_ids))  # type: ignore[attr-defined]
            )
        ).all():
            await session.delete(asset)
        await session.flush()

        # Any attempt these seeded learners made on a material that wasn't
        # seeded — practising against your own real material while the seed
        # was in — would hold the user row hostage, so it goes too.
        for attempt in (
            await session.exec(
                select(Attempt).where(Attempt.user_id.in_(author_ids))  # type: ignore[attr-defined]
            )
        ).all():
            for qa in (
                await session.exec(
                    select(QuestionAttempt).where(
                        QuestionAttempt.attempt_id == attempt.id
                    )
                )
            ).all():
                await session.delete(qa)
            await session.flush()
            await session.delete(attempt)
        await session.flush()

        for user in users:
            await session.delete(user)
        await session.commit()
        print(
            f"Removed {len(materials)} seeded materials, "
            f"{len(collections)} collections and {len(users)} accounts."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true", help="remove seeded data")
    parser.add_argument("--reset", action="store_true", help="clean, then seed")
    parser.add_argument(
        "--force",
        action="store_true",
        help="run even where DEV_LOGIN_ENABLED is off (you had better be sure)",
    )
    args = parser.parse_args()

    if not settings.dev_login_enabled and not args.force:
        raise SystemExit(
            "Refusing to run: DEV_LOGIN_ENABLED is off, so this does not look "
            "like a development database. Pass --force if it is."
        )

    async def run() -> None:
        if args.clean or args.reset:
            await clean()
        if not args.clean:
            await seed()

    asyncio.run(run())


if __name__ == "__main__":
    main()
