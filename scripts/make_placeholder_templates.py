"""Generates placeholder template images and manifests.

Placeholders are laid out on a fixed 800x800 canvas with evenly stacked
slots, so box geometry is real and the renderer can be exercised properly.
Replace the PNGs with genuine meme images later and re-measure the boxes;
`zeitgeist validate-templates` will catch any that no longer fit.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw

TEMPLATES: list[tuple[str, str, list[str]]] = [
    (
        "drake",
        "rejecting option A in favour of preferred option B",
        ["rejected", "preferred"],
    ),
    (
        "left_exit_12",
        "swerving away from the expected choice toward another",
        ["straight_ahead", "exit", "driver"],
    ),
    (
        "buff_doge_vs_cheems",
        "a confident past self against a feeble present one",
        ["strong", "weak"],
    ),
    (
        "expanding_brain",
        "four takes, each more absurdly enlightened than the last",
        ["level1", "level2", "level3", "level4"],
    ),
    (
        "increasingly_buff_spongebob",
        "the same thing escalating to an extreme",
        ["stage1", "stage2", "stage3", "stage4"],
    ),
    (
        "panik_kalm_panik",
        "alarm, brief relief, then renewed alarm",
        ["panik1", "kalm", "panik2"],
    ),
    (
        "distracted_boyfriend",
        "being tempted away from A by a newer B",
        ["boyfriend", "girlfriend", "other_woman"],
    ),
    (
        "woman_yelling_at_cat",
        "a furious accusation meeting an unbothered response",
        ["accuser", "responder"],
    ),
    (
        "spiderman_pointing",
        "two identical things accusing each other",
        ["left", "right"],
    ),
    (
        "gru_plan",
        "a plan whose final step reveals it backfiring",
        ["step1", "step2", "step3", "step4"],
    ),
    (
        "surprised_pikachu",
        "shock at an entirely predictable consequence",
        ["setup", "consequence"],
    ),
    (
        "this_is_fine",
        "insisting all is well amid visible disaster",
        ["situation", "denial"],
    ),
    (
        "anakin_padme",
        "a confident claim meeting a horrified realisation",
        ["claim", "question", "silence", "repeat"],
    ),
    (
        "is_this_a_pigeon",
        "confidently misidentifying something obvious",
        ["subject", "object", "caption"],
    ),
    (
        "they_dont_know",
        "imagined superiority while standing alone",
        ["thought"],
    ),
    (
        "hide_the_pain_harold",
        "smiling through quiet discomfort",
        ["top", "bottom"],
    ),
    (
        "disaster_girl",
        "quiet satisfaction at chaos you caused",
        ["caption"],
    ),
    (
        "change_my_mind",
        "a provocative thesis stated flatly and defended",
        ["thesis"],
    ),
    (
        "two_buttons",
        "agonising over a false dilemma",
        ["button1", "button2", "label"],
    ),
    (
        "roll_safe",
        "misguided reasoning presented as cleverness",
        ["top", "bottom"],
    ),
    (
        "first_time",
        "weary recognition of a familiar ordeal",
        ["caption"],
    ),
    (
        "clown_makeup",
        "progressive self-humiliation, step by step",
        ["step1", "step2", "step3", "step4"],
    ),
    (
        "always_has_been",
        "a mundane truth revealed as having always been so",
        ["realisation", "response"],
    ),
    (
        "bernie_asking",
        "asking once again for a modest thing",
        ["request"],
    ),
]

WIDTH = HEIGHT = 800
MARGIN = 20
OUT = Path("zeitgeist/media/templates")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for template_id, shape, slot_names in TEMPLATES:
        image = Image.new("RGB", (WIDTH, HEIGHT), "#d9d9d9")
        draw = ImageDraw.Draw(image)

        band = (HEIGHT - MARGIN * (len(slot_names) + 1)) // len(slot_names)
        slots = []
        for index, name in enumerate(slot_names):
            top = MARGIN + index * (band + MARGIN)
            box = (MARGIN, top, WIDTH - MARGIN, top + band)
            draw.rectangle(box, outline="#8a8a8a", width=3)
            slots.append(
                {
                    "name": name,
                    "box": list(box),
                    "max_chars": max(20, (WIDTH - 2 * MARGIN) // 7),
                }
            )

        image.save(OUT / f"{template_id}.png")
        (OUT / f"{template_id}.json").write_text(
            json.dumps(
                {
                    "id": template_id,
                    "image": f"{template_id}.png",
                    "shape": shape,
                    "slots": slots,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    print(f"wrote {len(TEMPLATES)} placeholder templates to {OUT}")


if __name__ == "__main__":
    main()
