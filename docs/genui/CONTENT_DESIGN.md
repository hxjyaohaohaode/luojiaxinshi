# Content-led composition

The model authors the information structure for each answer. The component catalog
is a vocabulary for composition, not a menu of available page templates. Gallery
scenes are explicitly fictional interaction examples and are not injected as model
few-shot layouts.

Start with the reader's purpose, the evidence available, the reading order, and
the decisions or questions that benefit from interaction. Qualitative material
does not need numeric metrics or charts. News, explanatory briefs, scenarios,
research notes, creative work, and plans can share the same primitives while
having different structures.

- `Section`: an unframed semantic region. `eyebrow` adds a small topic label;
  `level` sets heading level 2–4. Default `surface` is `plain`.
- `Prose`: safe Markdown with `body`, `lead`, `caption`, `eyebrow`, or `quote`
  typography. Quotes can carry `attribution`. Sources remain registered evidence;
  this component does not invent or validate citations on its own.
- `Choice`: a local single selection with optional option descriptions. Inline
  choices suit reading lenses; list choices suit substantive alternatives.
  A `null` initial value means unanswered. It supports arrow/Home/End keys and
  restores a selected scalar only if declared by the current options.
- `Compare`: qualitative comparison by dimension. Default `matrix` groups the
  same dimension across sources, supports safe Markdown and citations, and
  restacks by dimension on narrow screens. `columns` supports parallel readings.
- `Collection`, `Grid`, `Tabs`, `Accordion`, `visible`, and bounded state
  expressions connect arbitrary content, perspectives, and progressive detail.

Prefer typography, whitespace, alignment, and occasional rules to nested panels.
Legacy `Card` is unframed. The root answer has no enclosing border. Input focus
and selection remain visible; controls retain 44 px hit targets.

Every control must change meaningful content or record a meaningful choice.
Changing a reading lens must not alter source facts. Changing a scenario should
reset its answer and feedback. Local actions never imply a real submission.
Only explicit model follow-up buttons send the current selection/draft into the
conversation; UI changes do not execute arbitrary code or new network requests.

Validation covers narrow and wide layouts, qualitative comparisons, keyboard
selection, unanswered state, feedback, reset, snapshots, copy output, citation
previews, and the existing transport/evidence boundaries. Real model runs are
kept separate from deterministic gallery fixtures.

For continuous work, a Collection can bind its original state array and expose
per-record editable fields, such as `item.note`, while retaining unbound source
fields. Stable keys preserve record identity through filtering. Undo/redo, draft
copying, pending actions, and validated follow-up context belong to the runtime;
they are not separate page templates. See [continuous interaction](INTERACTION.md).
