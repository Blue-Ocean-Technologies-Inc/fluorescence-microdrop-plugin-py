# Outlier removal and smoothing

Date: 2026-08-06
Status: approved

Two independent controls over each ROI's curve: drop points that do
not belong, and smooth what is drawn.

## Outliers — the Hampel test

Each point is compared with the median and spread of the window around
it, and dropped when it lies further than N scaled MADs away.

Robust by construction: the spike being tested cannot drag the median
it is measured against, where a mean-and-SD test lets one wild value
raise the very threshold that would have caught it.

**Parameters** are the user's: the threshold in MADs (default 3, about
what "3 sigma" means for clean data) and the window in points
(default 5).

**Where a window's spread collapses** — half its values identical, as
in a steady signal or a two-level flicker — the median deviation is
zero while the data plainly has spread. The scale then falls back to
the mean absolute deviation, and failing that to the whole series'. An
earlier version simply refused to flag anything without a scale, which
made the test silently do nothing on the commonest case there is: a
flat baseline with one bad frame.

**Its limit is the window.** Outliers close enough together to fill
much of one stop being unusual relative to each other and the test
goes quiet — three spikes inside a seven-point window are not found.
Isolated spikes, the usual case, are. A test pins this rather than
leaving it to be discovered.

A spike is only unusual against the LOCAL trend: one at a sigmoid's
midpoint, where the curve moves as much across the window as the spike
does, is not an outlier and is not treated as one.

## Smoothing — Savitzky-Golay or Butterworth

- **Savitzky-Golay**: a local polynomial fit (window, order). Keeps
  peak height and width where a moving average flattens them.
- **Butterworth**: a low-pass filter (order, cutoff), run forwards and
  back so nothing shifts in time.

Cutoff is a **fraction of the Nyquist frequency**, not Hz: a
burst-captured series is not evenly spaced in time, and only the point
spacing is knowable. Both filters treat points as evenly spaced, which
is the honest reading of what a window means here.

Gaps are filled for the filter and punched back out afterwards — a
missing measurement must not become an invented value — and a series
too short for the filter asked for is returned untouched rather than
not drawn.

## What reaches what

```
measured stats
   -> outliers dropped        <- feeds everything below
   -> standard correction
   -> visibility filter
   -> subtract first
   -> normalise
   -> FITS, CSV               <- fitted and exported from here
   -> smoothing               <- drawn only
```

**Outliers go first.** A spike inside a standard ROI would otherwise
be subtracted from every curve before anything tested it, and once
spread across them all the per-curve test cannot find it. Same reason
it precedes the baseline shift and the normalisation, either of which
one wild point would otherwise define.

**Smoothing goes last and no further than the lines.** Fitting a
smoothed curve reports a goodness it did not earn: neighbouring values
are no longer independent, which flatters R² and shrinks the parameter
uncertainties for the wrong reason.

One pipeline serves the plot and the export, so a saved fit and the
drawn one cannot disagree about which points they saw. The export
keeps hidden ROIs, the plot does not — a hidden ROI is a display
choice, and the CSV has always carried them all.

## Saying what was dropped

Removing data quietly is the thing to avoid. A removal leaves the same
gap a missing measurement does, and the two mean opposite things.

- The figure carries a count: "3 points dropped as outliers".
- The CSV keeps every row and adds an `outlier` column. The point was
  measured; it was flagged. Deleting the row would hide a judgement
  the reader may not share.

A count on the figure rather than a mark per point: by the time the
curve is drawn it may have been baseline-shifted or normalised, and
there is no honest y to draw the dropped value at.
