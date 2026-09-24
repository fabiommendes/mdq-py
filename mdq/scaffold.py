"""
Scaffold new question documents for each MDQ question type.

`render_template` returns the markdown for a bare-bones or a
feature-complete example of a given question type, so `mdq new` (and any
other caller) has one source of truth for what a freshly scaffolded
document looks like.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

from .models import Question

__all__ = ["QUESTION_TYPES", "default_output_path", "render_template"]


def _question_types() -> tuple[str, ...]:
    """Every `type` literal of the `Question` union, sorted."""
    # `Question` is `Annotated[Union[...], Field(discriminator="type")]`;
    # `get_args` on the annotated form's first argument peels off the
    # discriminator metadata to reach the union of question models.
    union = get_args(Question)[0]
    literals = (get_args(model.model_fields["type"].annotation)[0] for model in get_args(union))
    return tuple(sorted(literals))


#: Every question type `mdq new` can scaffold.
QUESTION_TYPES = _question_types()


def render_template(question_type: str, *, complete: bool = False) -> str:
    """
    Render the scaffold markdown for `question_type`.

    Args:
        question_type: One of `QUESTION_TYPES`.
        complete: Illustrate every feature the type supports instead of a
            minimal skeleton.

    Raises:
        KeyError: `question_type` isn't in `QUESTION_TYPES`.
    """
    templates = _COMPLETE_TEMPLATES if complete else _SIMPLE_TEMPLATES
    return templates[question_type]


def default_output_path(question_type: str) -> Path:
    """Default file to write a `question_type` scaffold to."""
    return Path(f"{question_type}.mdq.md")


_SIMPLE_TEMPLATES: dict[str, str] = {
    "multiple-choice": """\
---
title: Capital of Brazil
---

What is the capital of Brazil?

* [ ] Rio de Janeiro
* [*] Brasília
* [ ] São Paulo
""",
    "multiple-selection": """\
---
title: Brazilian biomes
---

Which of the following are biomes found in Brazil?

* [x] Amazon rainforest
* [x] Cerrado
* [ ] Sahara
* [ ] Tundra
""",
    "true-false": """\
---
title: Evolution and climate
---

Judge the alternatives.

* [F] The Earth is flat.
* [T] Species evolve through natural selection.
* [T] Human activity contributes to global warming.
""",
    "numeric": """\
---
title: Amazon River length
---

What is the approximate length of the Amazon River, in kilometers?

[numeric(km)]: 6992
""",
    "short-answer": """\
---
title: Capital of Brazil
---

What is the capital of Brazil?

[short-answer]: Brasília
""",
    "essay": """\
---
title: Greenhouse effect
type: essay
---

Explain how the greenhouse effect works and how it affects Earth's climate.

[essay]
""",
    "fill-in": """\
---
title: Brazilian capital
---

The capital of Brazil is [^capital]. It has approximately [^population]
million inhabitants.

[^capital]:
* [ ] Rio de Janeiro
* [*] Brasília
* [ ] São Paulo

[^population/numeric]: 3 +- 0.5
""",
    "ordering": """\
---
title: Fibonacci sequence
type: ordering
---

Sort the lines below to create a program that prints the first ten numbers
of the Fibonacci sequence.

[ordering]
```python
x, y = 1, 1
for _ in range(10):
    print(x)
    aux = x + y
    x = y
    y = aux
```
""",
}

_COMPLETE_TEMPLATES: dict[str, str] = {
    "multiple-choice": """\
---
id: mc-brazil-capital
uuid: 0afae28e-5544-411d-bc12-430fb02e219e
title: Capital of Brazil
type: multiple-choice
tags: [geography, brazil]
author: Joaquim Nabuco
locale: en-US
shuffle: true
grading: partial
meta:
  difficulty: easy
---

Brazil's political geography has shifted more than once since colonial
times.

What is the capital of Brazil?

* [ ] [rio] Rio de Janeiro
  > Rio was the capital until 1960, but it isn't anymore.
  ! A common wrong answer -- students often stop here.
* [*] [brasilia] Brasília
  > Correct! Brasília became the capital in 1960.
* [50%] [sao-paulo] São Paulo
  > São Paulo is Brazil's largest city, but it was never the capital.
* [ ] [salvador] Salvador
  > Salvador was the colonial capital, before Rio de Janeiro.

Brasília was purpose-built as the capital and inaugurated in 1960.
""",
    "multiple-selection": """\
---
id: ms-brazilian-biomes
uuid: fd0679ef-18bb-4de6-83dd-35d929d49538
title: Brazilian biomes
type: multiple-selection
tags: [geography, brazil]
author: Alexander von Humboldt
locale: en-US
shuffle: true
grading: partial
meta:
  difficulty: medium
---

Brazil is home to a wide range of ecosystems, from rainforest to
semi-arid scrubland.

Which of the following are biomes found in Brazil?

* [x] [amazon] Amazon rainforest
  > Correct! The Amazon covers roughly half of Brazil's territory.
* [x] [cerrado] Cerrado
  > Correct! The Cerrado is a vast tropical savanna.
* [ ] [sahara] Sahara
  > The Sahara is in North Africa, not South America.
* [ ] [tundra] Tundra
  > Tundra requires a cold climate found near the poles, not in Brazil.

The Atlantic Forest and the Pantanal wetlands are two other major
Brazilian biomes not listed above.
""",
    "true-false": """\
---
id: tf-evolution-climate
uuid: 4cb3998a-0428-4a0f-9f05-b56e4384eb82
title: Evolução e clima
type: true-false
tags: [science, biology, climate]
author: Charles Darwin
locale: pt-BR
shuffle: true
grading: symmetric
meta:
  difficulty: medium
---

Estas afirmações tratam de evolução biológica e mudança climática.

Julgue as afirmações a seguir.

* [F] [terra-plana] A Terra é plana.
  > Falso: a Terra é um geoide, praticamente esférico.
* [V] [selecao-natural] A seleção natural explica a evolução das espécies.
  > Verdadeiro: é o mecanismo central da teoria de Darwin.
* [V] [aquecimento-global] O aquecimento global tem influência humana.
  > Verdadeiro: o consenso científico aponta os gases de efeito estufa
  > como principal causa.
* [F] [evolucao-instantanea] A evolução ocorre em uma única geração.
  > Falso: é um processo cumulativo ao longo de muitas gerações.

A teoria da evolução de Darwin e a ciência climática são dois pilares da
ciência moderna.
""",
    "numeric": """\
---
id: num-amazon-length
uuid: f7cf0512-7458-4f4d-9bde-aad1e48a3582
title: Length of the Amazon River
type: numeric
tags: [geography, brazil]
author: Alexander von Humboldt
locale: en-US
unit: km
domain: decimal
decimalPlaces: 2
meta:
  difficulty: hard
---

Estimates vary depending on which tributary is counted as the river's
true source.

What is the approximate length of the Amazon River, in kilometers?

[numeric(km)]: 6992.06 +- 5% +- 50

Some measurements place it slightly ahead of the Nile as the longest
river on Earth.
""",
    "short-answer": """\
---
id: sa-independence-date
uuid: 1a99bd45-a08a-4acd-9615-daa6308fda83
title: Brazilian independence
type: short-answer
tags: [history, brazil]
author: Joaquim Nabuco
locale: pt-BR
meta:
  difficulty: medium
---

Brazil declared its independence from Portugal in the 19th century.

Write the date of Brazilian independence in the `YYYY-MM-DD` format.

[short-answer]: /1822-0?9-0?7/

The declaration is traditionally associated with Dom Pedro I's "Grito do
Ipiranga".
""",
    "essay": '''\
---
id: essay-code-fibonacci
uuid: 52652419-e34c-49bc-b407-a2a1db64ed23
title: Fibonacci in Python
type: essay
tags: [programming, python, algorithms]
author: Ada Lovelace
locale: en-US
input: code
highlight: python
meta:
  difficulty: medium
---

The Fibonacci sequence appears throughout nature, from sunflower seed
patterns to the branching of trees.

Write a Python function `fib(n)` that returns the n-th Fibonacci number,
with `fib(0) == 0` and `fib(1) == 1`. You may use either an iterative or
a recursive approach.

[essay]

Aim for a solution that runs in O(n) time.

## [answer-key]

A simple iterative solution:

```python
def fib(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
```

A recursive solution is also acceptable, though it should ideally use
memoization to avoid exponential blow-up for large `n`.
''',
    "fill-in": """\
---
id: fill-in-solar-system
uuid: bbfe02e0-1b87-47fe-bfcc-6deb3234e951
title: The Solar System
type: fill-in
tags: [astronomy, science]
author: Carl Sagan
locale: en-US
shuffle: true
grading: partial
meta:
  difficulty: medium
---

Jupiter dominates the outer Solar System both in size and in the number
of moons discovered orbiting it.

The [^planet] is the largest planet in the Solar System, and it has
approximately [^moons] known moons. Its Great Red Spot is a [^feature].

[^planet/short-answer]: Jupiter

[^moons/numeric]: 95 +- 5

[^feature]:
* [ ] [mountain] mountain
  ! Students sometimes confuse the Red Spot with a surface feature.
* [*] [storm] storm
  > Correct! It is a giant, centuries-old anticyclonic storm.
* [ ] [crater] crater

New moons are still being discovered, so the exact count keeps changing.
""",
    "ordering": '''\
---
id: ordering-circle-area-perimeter
uuid: 5a5d7ca7-9d26-4513-a324-732adad9e94e
title: Area and perimeter of a circle
type: ordering
tags: [mathematics, geometry, python]
author: Euclides
locale: en-US
meta:
  difficulty: medium
---

A circle's area and perimeter both depend only on its radius, so the two
computations do not depend on each other.

Sort the lines below into a program that reads a radius and prints the
circle's area and perimeter.

[ordering]
```python
import math

radius = float(input("radius: "))
area = math.pi * radius ** 2
perimeter = 2 * math.pi * radius
print(area, perimeter)
```

## [extra]
```python
area = math.pi * radius * 2
```

## [accept]

> The area and the perimeter each depend only on `radius`, so either one
> may be computed first.

```python
import math

radius = float(input("radius: "))
perimeter = 2 * math.pi * radius
area = math.pi * radius ** 2
print(area, perimeter)
```

## [reject]

> `area` uses the perimeter formula instead of `pi * radius ** 2`, so the
> printed area is wrong.

! Confusing area with perimeter is a common mistake.

```python
import math

radius = float(input("radius: "))
area = math.pi * radius * 2
perimeter = 2 * math.pi * radius
print(area, perimeter)
```
''',
}
