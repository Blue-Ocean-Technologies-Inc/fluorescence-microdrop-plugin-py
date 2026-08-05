# User-defined fit equations

Date: 2026-08-05
Status: approved

The fit is currently one of six built-in models. This lets the user
type any equation instead — `F(x) = a + b*exp(-c*x)` — fit it, save it
as a preset, and read its fitted parameters as table columns.

Inspired by pyCftool's custom-equation box, with two departures noted
below.

## The equation field

The fit-equations popup grows a header:

```
Fit  [ Sigmoid        v ]     [+ Add to presets]
F(x) = a + (b - a)/(1 + exp(-c*(x - d)))
```

Selecting a preset fills the field with its expression. Typing in the
field switches the fit to that expression (the dropdown reads
"Custom"). The **Add to presets** button enables only when the text
parses *and* is not already a preset; it asks for a name and saves.

`x` is elapsed seconds. `t` is accepted as a synonym, since the
built-in equations have always printed in `t`.

## Parsing

Every identifier that is not `x`/`t`, a known function, or a known
constant is a fit parameter. Parameters are ordered **by first
appearance in the text**, which is also the column order in the table.

*Departure from pyCftool #1:* it collects parameters with
`list(set(...))`, so their order — and therefore which initial guess
and which reported value belongs to which name — varies between runs
once string hashing is randomized. Order of appearance is stable and
reads the way the user wrote it.

*Departure from pyCftool #2:* it splits the text with a regex and
`eval`s the result. This walks Python's own `ast` instead. That buys
real error messages ("unknown function `sine`" rather than a failed
fit), and it rejects anything that is not arithmetic — attribute
access, subscripts, lambdas, calls to anything outside the whitelist —
so a typo cannot reach into the interpreter. `eval` runs with no
builtins.

`^` is rewritten to `**` before parsing, so the field accepts the
notation the equations are written in.

Allowed: `+ - * / ** %`, unary minus, numbers, parentheses, the
constants `pi`/`e`, and the functions `exp log log10 sqrt abs sin cos
tan asin acos atan sinh cosh tanh expit erf`.

An invalid expression shows its error under the field and leaves the
previous fit alone. It is never raised at the user as a traceback.

## Fitting

`curve_fit` over the compiled expression, exactly as the built-ins use
it.

**Initial guesses** are the weak point of any arbitrary-equation
fitter, and pyCftool's all-zeros seed fails on the commonest case
(`a*exp(b*x)` has zero gradient at `a = 0`). Instead a ladder of
uniform seeds is tried — 1.0, 0.0, mean(y), range(y), and **±1/span**
— and the converged fit with the best R² wins. Six solves of a handful
of parameters take about 16 ms, and the ladder is deterministic.

The ±1/span pair was added after measuring: a rate seeded at 1.0 puts
`exp(1·t)` past the float ceiling for any real time axis, and
**−1/span is the only seed of the six that recovers an exponential
decay** — the shape a bleaching fluorescence series actually has. The
first draft of this design omitted it and fitted that case at R² 0.80.

**Per-parameter starting values** sit beside the table, one row per
parameter of the current fit — parameters as *rows*, so no dynamic
columns are involved. Blank means "seed this one automatically", and a
set is used only when every parameter has a number: a seed is a
vector, and filling the gaps with invented values would be a different
starting point than the one asked for. **Seed from fit** fills them
all with what the fit just found, so nudging never means typing a
whole vector from nothing; **Auto** clears them.

They are honoured rather than second-guessed. A complete set is tried
first and stands if it reaches any usable fit — even a poor one, since
a bad fit from the values you asked for is honest feedback with its R²
next to it, where silently substituting a better automatic fit would
make the field look broken. Only a seed that reaches *nothing* usable
(no finite R² at all) is abandoned, and then the automatic ladder runs
and the popup says it did. The values are stored per experiment with
the equation.

**Solving is insulated from ambient warning filters.** An optimizer
exploring a typed equation overflows `exp` routinely, which numpy
reports as a warning. Under a `warnings-as-errors` filter — pytest's
posture, and any caller that sets one — those transients become
exceptions, and the seed that would have won is silently discarded in
favour of a worse one that happened not to trip a warning. The solve
therefore runs under `np.errstate(all="ignore")` and suppressed
warnings; whether the *result* is finite is what decides it, and that
is checked explicitly.

Evaluating the equation carries the same guard for a sharper reason:
numpy issuing a warning from inside code eval'd with no builtins sends
CPython's warnings machinery looking for `__import__` in those
globals, and it surfaces as `KeyError: '__import__'` — not something
any caller could have handled. Every consumer of `predict()`, the plot
included, is covered by silencing it at the source.

**Derivatives are numeric** for custom equations — central differences
on the fitted domain — where the built-ins carry analytic ones. This
is what makes the feature cheap: the d²-extrema markers and the
fastest-change view already sample the derivative on a 512-point grid,
so a numeric closure satisfies the existing `FitResult` contract with
no change to any consumer. A custom fit reports no analytic
inflection, so "fastest change" searches the grid, a path that already
exists for the polynomial models.

## Presets

Built-ins keep their hand-written implementations — better
conditioned, exact derivatives, and the sigmoid's inflection — and
gain a display template so the field shows something real when one is
selected. Each template names the parameters that model actually
reports (`c1*x + c0`, not `m*x + b`), so the equation on display and
the table's columns say the same thing; typing a *different* spelling
of the same shape is simply a custom fit, with the names as typed.

Saved presets are name + expression, stored **app-wide** in the
fluorescence preferences (as JSON in one string trait), because a
preset the user had to re-type per experiment is not a preset. The
expression currently in use is *also* persisted per experiment, so
reopening an experiment reproduces its fit whether or not the equation
was ever saved.

`fit_method` changes from an `Enum` to a `Str`, the set of choices no
longer being fixed at import time. A method that no longer resolves (a
preset deleted since) falls back to "no fit" rather than failing.

## The table

The single Equation column is replaced by one column per parameter,
built from the fit's own parameter names — so a custom `a, b, c` and
the sigmoid's `amplitude, rate, midpoint, offset` are displayed by the
same mechanism.

Columns: ROI | *one per parameter* | R², plus a fit-range column when
the trim option dropped a tail (that note used to be glued onto the
equation text).

Each ROI is fitted independently, as now, so the columns are the
parameter names and the rows are each ROI's values for them.

Editing the equation refits and repopulates in place — the popup is
modeless and the field is the point of it, so it can no longer be a
snapshot taken when it opened.

## Testing

The parser and the fitter are Qt-free and get unit tests: parameter
discovery and ordering, every rejection path, `^` rewriting, a round
trip that recovers known parameters from generated data, numeric
derivatives against the analytic ones of a built-in, and the preset
JSON round trip. The popup itself is exercised by an offscreen smoke.
