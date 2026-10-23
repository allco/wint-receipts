# Design notes

How the app looks and behaves, and why. The colours, spacing and components here are the ones the
code uses (`wint_receipts/app/theme.py`, `icons.py`, `empty_states.py`). The PNGs in `design/` are
exported from the design file. They're stored with Git LFS, so run `git lfs install` before cloning
to get the real images.

## Principles

- **AI does the reading, a person decides.** Everything Claude AI reads is labelled as AI output
  (*Read with AI*, *AI notes*, *VAT (AI-read)*, *AI cost*), and the sparkle icon marks AI actions.
  Nothing goes to Wint without a person approving it.
- **The scan is the source of truth.** The page image always sits next to the fields read from it,
  and everything is arranged around checking one against the other.
- **Show doubt, don't hide it.** Claude reports the fields it wasn't sure about. Those are marked
  amber, and errors that block approval are marked red. A clean form means there's nothing to check
  beyond a glance.
- **Nothing is final until it's uploaded.** Skipping, deleting, merging and editing can all be undone.
  Upload is the only step that writes to Wint, and it asks for confirmation first.
- **An empty pane explains itself.** Before there's anything to show, each pane says what will
  appear there and what to do next.
- **Same look on every desktop.** The app uses Qt's Fusion style with its own palette, so it looks the
  same on GNOME, KDE, Windows and macOS. That also means there's no dark mode yet.

## Layout

![Review screen](design/03-review.png)

The window has a toolbar, three panes side by side, and a status bar.

| Pane | Default width | Content |
|---|---|---|
| Pages | 420 px (min 320) | One row per page: status dot, page number, date · amount · category |
| Page image | flexible | The scan, plus the image bar under it: rotate, zoom, 1:1, Fit |
| Receipt | 560 px | AI-read fields, AI notes, check results, actions. Scrolls vertically only |

- The panes are separated by **1 px** splitter lines in the border colour, and can be resized.
- The **toolbar** holds the global actions, grouped by dividers: open / read with AI · previous/next ·
  preview/upload · reload/settings. Image controls live with the image, not in the toolbar.
- The **status bar** shows the company name, page counts by status, the AI cost so far, and
  whether uploads are on. When pages have been deleted, a *Restore deleted pages (N)* link appears on
  its left.

## Screens and states

| State | Pages pane | Image pane | Receipt pane |
|---|---|---|---|
| No PDF open | Explains the list and the status colours | Steps 1–3 and *Open PDF* | Explains the fields, the colours and the shortcuts |
| AI reading | Row shows "AI reading" | The scan | "Claude AI is reading this receipt…" |
| Failed / not read yet | Red or grey dot | The scan | Reason, plus *Read with AI* and *Skip page* |
| Review | Row summary | The scan | The editable form |

![Empty state](design/01-empty.png)

![AI reading](design/02-recognising.png)

## Colour

The palette is light only. All colours come from `theme.py`, and those values match the design
file's variables.

| Token | Value | Used for |
|---|---|---|
| `surface/window` | `#EFEFEF` | Window, toolbar, panes without content |
| `surface/base` | `#FFFFFF` | Inputs, buttons, page list, scan background |
| `surface/warning` | `#FBEFC9` | Field Claude wasn't sure about |
| `surface/error` | `#F8DADA` | Field that blocks approval |
| `border/default` | `#C9C9C9` | Input and button borders, dividers |
| `text/primary` | `#1F1F1F` | Text, icon strokes |
| `text/muted` | `#6E6E6E` | Secondary text, placeholders, disabled |
| `text/on-accent` | `#FFFFFF` | Text on accent backgrounds |
| `accent` | `#308CC6` | Primary button, selection, links, icon accents |

Not design variables, used only for interaction states: hover `#E3E3E3`, pressed `#D6D6D6`, accent
hover `#2878AB`.

**Page status** (dot colour):

| Status | Colour | | Status | Colour |
|---|---|---|---|---|
| waiting | `#9E9E9E` | | skipped | `#757575` |
| AI reading | `#1E88E5` | | uploading | `#1E88E5` |
| needs review | `#F9A825` | | uploaded | `#2E7D32` |
| approved | `#43A047` | | failed | `#E53935` |

A status is never shown by colour alone. Each row also has text (the summary, or "AI reading",
"failed", …) and a tooltip, so the dots work for colour-blind users too. Dots have a white outline
so they stay visible on the blue selected row.

## Type

- **Font:** the system UI font. That's Noto Sans on Fedora, and the design file uses Noto Sans too.
- **Scale:** the whole UI is multiplied by *Settings → Font size* (0.5×–2.0× in steps of 0.1;
  the default is 1.5×). The change applies immediately.
- **Hierarchy:** form title is bold at 1.15×. The amount is bold: it's the number to check first,
  and it stays bold under the amber/red highlights. Empty-state titles are bold at 1.35×. Secondary text
  uses the muted colour at the same size, rather than a smaller one, so it stays readable when scaled.

## Components

![Components](design/components.png)

- **Button.** *Primary* (accent fill, white semibold label) is used for exactly one action per
  context: *Approve* in the form, *Open PDF* in the empty state. *Secondary* (white, 1 px border,
  5 px radius) is for everything else. *Disabled* is grey with muted text.
- **Status dot.** 12 px with a 1.5 px white ring, in the eight status colours above.
- **Page row.** Status dot plus a one-line summary, cut off with "…" at the end.
- **Field row.** Label column (about 130 px), then the input. *Default*, *Warning* (amber fill) and
  *Error* (red fill) variants.
- **Toolbar item.** 18 px icon at 1× scale, a 6 px gap, then the label. Flat, with a grey rounded
  background on hover.
- **Image bar.** Under the page image, in the toolbar style but with a border on top: *Rotate left*
  / *Rotate right* on the left; zoom out, the zoom percentage, zoom in, *1:1* and *Fit* on the right.
- **Page context menu.** White with a 1 px border and 6 px radius; the selected item is filled with
  the accent colour. It has *Delete page* (`Del`) and, when pages have been deleted, *Restore
  deleted pages (N)*.

## Icons

Nine of the app's own outline icons on a 24×24 grid: stroke 1.8 with round caps and joins, in the
text colour, with the accent colour on the part that carries the meaning:

| Icon | Action | Accent on |
|---|---|---|
| folder | Open PDF | the receipt lines |
| receipt + sparkles | Read with AI | the sparkles (the app's AI mark) |
| chevrons | Previous / Next | — |
| corner brackets | Fit image | — |
| page + `<>` | Preview request | the brackets |
| cloud + arrow | Upload approved | the arrow |
| circular arrows | Reload Wint data | — |
| sliders | Settings | the middle knob |
| page + curved arrow | Rotate left / right | the arrow |
| magnifier + − / + | Zoom out / in | the − / + |

The icons are drawn from SVG at the screen's real resolution, so they stay sharp at any scale. When
disabled, they turn the border grey. They grow with the font size.

## Interaction

| Action | How |
|---|---|
| Open a PDF | *Open PDF* (Ctrl+O), or drag a PDF onto the window |
| Approve | *Approve* or Ctrl+Enter; moves on to the next page that needs review |
| Next / previous page | PgDn / PgUp; deleted pages are skipped |
| Zoom the scan | Mouse wheel, or the image bar: − / + (Ctrl+− / Ctrl++), 1:1 (Ctrl+1), Fit (Ctrl+0); double-click to fit |
| Rotate a page | Image bar *Rotate left / right* (Ctrl+Shift+R / Ctrl+R). The turn is saved and used for the AI reading and the uploaded PDF page; the PDF file is untouched |
| Merge a two-page receipt | *Attach to previous*; *Separate receipt* undoes it |
| Remove a page | Right-click the page → *Delete page*, or `Del` in the list; Ctrl+Z restores |
| Settings | Ctrl+, |

- **Blank pages** never get a row; they count as deleted and can be restored.
- **Editing** an approved receipt sends it back to *needs review*.
- **Uploaded pages** are locked: they can't be edited, merged, rotated or deleted.
- **Sideways scans are turned automatically.** The AI reports the clockwise turn a page needs; the
  app applies it and says so in the AI notes. The rotate buttons override it.
- **The form shows only what goes to Wint:** date, amount, currency, category, payment method. The AI
  also reads the supplier and org number, but only to match learnings; they're neither shown nor sent.
- **Corrections teach the AI.** Changing the AI's category before approving adds a line to the AI
  learnings file. The next receipt from that supplier gets the corrected category, and
  the AI notes say so.

## Not designed yet

- Dark mode.
- Guests on representation receipts (`Persons`).
- What happens after upload in Wint (signing, payout status).
