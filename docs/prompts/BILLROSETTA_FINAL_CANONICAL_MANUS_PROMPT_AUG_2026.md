BILLROSETTA — FINAL CANONICAL MANUS BUILD

AUGUST 2026

HARD RULE: ADDITIVE ONLY.

Do not overwrite, delete, rename, replace, flatten, or clean up any existing BillRosetta work.

Preserve the current site exactly as historical evidence.

Build the new canonical version beside it first.

Before doing anything:

- identify exact project

- identify current deployed URL

- inventory existing routes/files

- record current state

- preserve current screenshots

- state what will remain untouched

- state what new routes/components will be added

Do not replace the public default until the new version is validated.

==================================================

1. PRODUCT DECISION

==================================================

BillRosetta was important BEFORE the ACH/funding layer.

Do not reduce it to a financing product.

The original core remains:

BILLROSETTA

Deterministic healthcare reimbursement intelligence.

It resolves:

code

→ date

→ locality

→ setting

→ modifiers

→ authority/version

→ RVUs/GPCIs

→ adjustments

→ conversion factor

→ exceptions

→ arithmetic

→ result

→ evidence

→ next action

Core promise:

DECODE THE BILL.

PROVE THE MATH.

However:

THE ACH / FUNDING-AUTHORIZATION LAYER IS NOW THE CONTROLLING COMMERCIAL DIRECTION.

Why?

Because the same deterministic evidence engine can now support:

reimbursement audit

→ receivable verification

→ borrowing-base evidence

→ capital approval

→ funding authorization

→ ACH execution

So the architecture is:

                      BILLROSETTA CORE

                            │

              deterministic reimbursement engine

                            │

                  evidence / provenance

                            │

                    proof continuity

                            │

              ┌─────────────┴─────────────┐

              │                           │

              ▼                           ▼

      BILLROSETTA AUDIT          BILLROSETTA CAPITAL

      audit / recovery           receivable verification

      payment integrity          borrowing base

      appeals                    funding authorization

      evidence packets           capital handoff / ACH gate

ONE ENGINE.

TWO COMMERCIAL DOORS.

CAPITAL IS THE STRATEGIC DIRECTION.

Use:

billrosetta.com

with:

/audit

/capital

or equivalent.

Main navigation:

AUDIT | CAPITAL | HOW IT WORKS | EVIDENCE

==================================================

2. BILLROSETTA AUDIT

==================================================

Preserve the original value proposition.

Audiences:

providers

RCM

employers

attorneys

patients

payment-integrity teams

Flow:

UPLOAD / INGEST

→ EXTRACT

→ RESOLVE

→ CALCULATE

→ EXCEPTION CHECK

→ EXPLAIN

→ EVIDENCE

→ ACTION

Important rule:

If BillRosetta cannot establish a defensible benchmark,

it says so instead of inventing one.

Never allow generative AI to invent deterministic financial values.

==================================================

3. BILLROSETTA CAPITAL

==================================================

Hero:

BILLROSETTA CAPITAL

TURN HEALTHCARE RECEIVABLES

INTO FUNDING-READY EVIDENCE.

Supporting copy:

BillRosetta verifies the claim book, derives the eligible borrowing base,

preserves the evidence, and produces a deterministic funding authorization

for an independently approved capital transaction.

The payment rail executes the instruction.

It never chooses the amount.

Flow:

837 / RECEIVABLE BOOK

→ VERIFY

→ ELIGIBILITY

→ BORROWING BASE

→ ASSIGNMENT / TITLE

→ RESERVE

→ CAPITAL APPROVAL

→ FUNDING AUTHORIZATION

→ LIVE PAYOUT GATE

→ ACH EXECUTION

Large rules:

NO AUTHORIZATION → NO PAYOUT

THE RAIL NEVER PRICES THE RECEIVABLE

NO CAPITAL APPROVAL → NO ACH

DEMO / SPECIMEN → NEVER LIVE FUNDING

==================================================

4. ACTUAL FUNDING IMPLEMENTATION

==================================================

Use the current BillRosetta branch as implementation evidence:

Repository:

prestigesf/medicare-Billrosetta-

Branch:

feature/billrosetta-ach-payout-gate

Relevant new files:

tools/build_837_borrowing_base.py

tools/test_837_borrowing_base.py

pfs/funding_authorization.py

pfs/payout_adapter.py

tools/execute_funding_payout.py

tests/test_funding_authorization.py

Reported specimen:

837 SHA-256:

8fd7246c5ad17e7ae2c0a57e0f4f785dc515417afc290fb4df42724c31c27031

260 lines

24 Status X

48 modifier 26

Face:

$467,518.99

Eligible / PFS candidate:

$35,601.32

Sandbox advance:

$27,270.61

Reserve:

$8,330.71

Unbound 837:

eligible $0

advance $0

Demo packet in live mode:

BLOCKED

Reason:

fixture_mode must equal LIVE_PRODUCTION

Targeted tests:

8 passed

Full reported suite:

233 passed

4 pre-existing failures in untouched files

Do not claim independent verification unless Manus actually verifies it.

==================================================

5. CALCULATION CORRECTNESS RULE

==================================================

This ordering is absolute:

1. calculation correctness

2. rule/version correctness

3. code-level exceptions

4. QP vs non-QP routing

5. explainable evidence trail

6. security / attestation

Never attest until calculation path is proven.

A signed wrong answer is still wrong.

==================================================

6. FIX CURRENT SPECIMEN ERRORS

==================================================

The current site has visible inconsistencies.

Fix them in the NEW version only.

Do not alter the historical version.

Required fixes:

- never mix San Francisco and Alabama locality

- verify CPT 99214 descriptor/time; remove unsupported time language

- do not use stale $32.35 conversion factor

- verify 2026 QP / non-QP conversion-factor routing

- project values previously identified:

  QP $33.5675

  Non-QP $33.4009

- verify before publishing

- account for applicable 2026 -2.5% efficiency adjustment

- do not apply it universally

- resolve modifiers/status/exemptions

- never imply CMS benchmark automatically proves unlawful billing

Preferred language:

CALCULATED CMS BENCHMARK

DIFFERENCE FROM SELECTED BENCHMARK

ADDITIONAL PAYER / CONTRACT ANALYSIS MAY BE REQUIRED

==================================================

7. PRESTIGESF BUILD PROTOCOL

==================================================

Run this project through the full process automatically.

A. PRE-BUILD SWEEP

Ask:

What already exists?

What can be reused?

What must be proven?

What can be partnered instead of built?

B. TWO RECENT BREAKTHROUGHS ALREADY KNOWN

1. version-pinned deterministic rule evaluation

2. underwritable machine-verifiable evidence

Apply both.

C. FIND TWO MORE DEVELOPMENTS FROM THE LAST 30 DAYS

Prioritize:

CMS

HHS

OIG

Federal Register

MACs

healthcare payment integrity

healthcare receivable finance

bank/payment infrastructure

credible fintech/RCM developments

For each:

WHAT CHANGED

WHY IT MATTERS

BUILD / ADOPT / PARTNER / DISMISS

EXACT BILLROSETTA IMPLICATION

Only use developments that materially improve the product.

D. SIX-LAYER NOTHING WASTED

1. Objectives &amp; Outcome

2. People &amp; Process

3. Workflow

4. Technology

5. Audit

6. Policy

Apply all six explicitly.

E. SWISS CHEESE

Ask:

WHERE CAN THE WHOLE ECONOMIC LOOP FAIL

EVEN IF EACH INDIVIDUAL COMPONENT APPEARS TO WORK?

Inspect:

source authenticity

837 integrity

duplicate claims

claim eligibility

timely filing

recoupment

fraud

duplicate financing

assignment/title

provider identity

NPI

locality

date

setting

modifiers

QP/non-QP

CMS version

exceptions

capital approval

KYC/KYB

bank account verification

ACH authorization

settlement

reconciliation

repayment

disputes

credential compromise

evidence tampering

For each hole classify:

BUILD

ADOPT

PARTNER

HUMAN REVIEW

BLOCK

F. EXECUTION RULE

72 HOURS → EXIST

7 DAYS → VALIDATE

30 DAYS → TRACTION OR DOWNGRADE

Development does not earn more development time.

External evidence does.

Build for release, not endless development.

==================================================

8. NOTHING WASTED — SHARED INFRASTRUCTURE

==================================================

Reuse infrastructure conceptually where accurate:

Second Look

→ independent verification

VenturePilot

→ authority / deterministic gates

DeadlineSF pattern

→ versioned external rules

BillRosetta

→ healthcare deterministic engine

GoldTrac

→ provenance / proof continuity

BopCart / payment layer

→ deterministic economic execution

Do NOT claim integrations are live unless proven.

Differentiate:

ARCHITECTURAL REUSE

from

DEPLOYED INTEGRATION.

Future commercial doors may include:

BillRosetta API

BillRosetta Recovery

BillRosetta Evidence

BillRosetta Monitor

Do not build them now.

AUDIT + CAPITAL are the priority.

==================================================

9. VISUAL NORTH STAR

==================================================

The current mineral / Rosetta identity is good.

Do not throw it away.

But the BACKGROUND WORLD must be dramatically upgraded.

The current dead sky / flat background is unacceptable.

This should feel like:

ANCIENT KNOWLEDGE

×

PRECIOUS MINERAL

×

FORENSIC FINANCIAL SYSTEM

×

SCIENTIFIC INSTRUMENT

×

INSTITUTIONAL TRUST

NOT A WEBSITE WITH A BACKGROUND.

A WORLD THAT CONTAINS THE WEBSITE.

==================================================

10. LIVING 3D WORLD

==================================================

Target visual quality:

8K visual feel

high-resolution source assets

2026 premium interactive web design

cinematic depth

real material response

continuous subtle motion

Create:

FOREGROUND

floating glass/mineral fragments, evidence particles

MIDGROUND

Rosetta slabs, formulas, evidence structures

BACKGROUND

living atmospheric sky / mineral horizon

DISTANT WORLD

slow geological/crystalline forms creating scale

Use:

volumetric cloud depth

atmospheric perspective

slow cloud drift

moving sunlight

refraction

light scattering

aerial haze

subtle particles

environment reflections

parallax

depth-of-field

perspective scale

occlusion

responsive lighting

scroll-driven camera movement

The world must remain subtly alive even when the user stops scrolling.

No dead gradient sky.

==================================================

11. MINERAL MATERIALS

==================================================

Make materials physically believable.

OBSIDIAN

dark controlled reflection

AMETHYST

internal violet refraction

TEAL / EMERALD

transmission + cyan/green light scattering

GOLD

warm environmental highlights

Reflections subtly respond to:

cursor

touch

scroll

camera position

Avoid fake chrome and cheap glow.

==================================================

12. SCROLL EXPERIENCE

==================================================

Hero:

camera approaches the three Rosetta slabs

Scroll:

layers separate

Continue:

camera moves between them

Obsidian reveals raw medical/837 evidence

Amethyst resolves code/rule/calculation structure

Gold/teal resolves evidence / action / authorization

Then transition into BillRosetta Capital.

Capital world becomes:

more structured

architectural

institutional

controlled

Funding gate:

the world narrows toward a deterministic gate.

BLOCK:

motion/path visibly stops.

AUTHORIZED:

path opens into the final evidence object.

Do not animate money magically appearing.

==================================================

13. 2026 INTERACTION QUALITY

==================================================

Use selectively where performant:

WebGL / Three.js

GPU transforms

scroll-driven animation

depth-aware interaction

shader effects

procedural light

responsive 3D

view transitions

premium 3D hover/touch controls

animated formulas

animated locality resolution

animated modifier resolution

evidence graph assembly

receipt sealing

borrowing-base visualization

reserve split visualization

funding-gate state changes

Do not use technology for spectacle alone.

Every effect must improve:

DEPTH

CLARITY

LUXURY

MOVEMENT

UNDERSTANDING

==================================================

14. THREE ROSETTA LAYERS

==================================================

Turn the current visual metaphor into product logic.

LAYER 1 — OBSIDIAN

RAW EVIDENCE

bill

EOB

837

denial

claim data

LAYER 2 — AMETHYST

RESOLVED STRUCTURE

code

date

locality

setting

modifiers

authority

version

rules

exceptions

LAYER 3 — GOLD / TEAL

ACTIONABLE EVIDENCE

benchmark

finding

audit packet

borrowing base

authorization

receipt

==================================================

15. SIGNATURE VISUAL — CALCULATION TRACE

==================================================

Build:

CPT

→ DATE

→ LOCALITY

→ SETTING

→ MODIFIERS

→ RVUs

→ GPCIs

→ 2026 ADJUSTMENT

→ CONVERSION FACTOR ROUTE

→ EXCEPTIONS

→ RESULT

Each node illuminates only after resolution.

If a required field cannot be proven:

STOP.

Display:

DEFENSIBLE BENCHMARK NOT AVAILABLE

==================================================

16. SIGNATURE VISUAL — CAPITAL TRACE

==================================================

Build:

837

→ HASH

→ CLAIM LINES

→ ELIGIBILITY

→ EXCLUSIONS

→ PFS CANDIDATE

→ ASSIGNMENT / TITLE

→ BORROWING BASE

→ ADVANCE RATE

→ RESERVE

→ CAPITAL APPROVAL

→ AUTHORIZATION

→ PAYOUT GATE

Show WHY every step passed or failed.

==================================================

17. CAPITAL SPECIMEN

==================================================

Create:

SIMULATED FUNDING AUTHORIZATION SPECIMEN

Display:

FACE

$467,518.99

ELIGIBLE AR

$35,601.32

ILLUSTRATIVE ADVANCE

$27,270.61

RESERVE

$8,330.71

Animate three states:

UNBOUND BOOK

→ $0 AUTHORIZATION

SANDBOX SPECIMEN

→ AUTHORIZATION CREATED

SPECIMEN → LIVE

→ BLOCKED

Label:

TEST FIXTURE

NOT A CREDIT OFFER

NOT A FUNDING GUARANTEE

Make BLOCKING feel like product strength.

==================================================

18. EVIDENCE PACKET

==================================================

Make the final artifact feel valuable and institutional.

Show:

source hash

authority/version

calculation path

exceptions

eligibility

borrowing base

assignment state

capital approval reference

authorization digest

verification state

timestamp

retest state

provenance state

Visual principle:

THIS NUMBER HAS A HISTORY.

==================================================

19. CLAIM / PROOF INSPECTOR

==================================================

Every major claim should expose:

CLAIM

STATUS

SOURCE

IMPLEMENTATION

TEST

EVIDENCE

LAST VERIFIED

Allowed states:

PROVEN

PARTIALLY_PROVEN

IMPLEMENTED_NOT_INDEPENDENTLY_VERIFIED

DESIGNED

EXPERIMENTAL

UNVERIFIED

Never let marketing outrun evidence.

==================================================

20. HUMAN REVIEW + PARTNER BOUNDARIES

==================================================

Visible stop states:

LOCALITY UNRESOLVED

AMBIGUOUS MODIFIER

PAYER DATA REQUIRED

ASSIGNMENT NOT VERIFIED

TIMELY FILING UNVERIFIED

RECOUPMENT REVIEW REQUIRED

CAPITAL APPROVAL REQUIRED

BANK VERIFICATION REQUIRED

Display:

HUMAN REVIEW REQUIRED

Likely partner boundaries:

capital provider

bank

ACH originator

KYC/KYB

fraud intelligence

credit underwriting

legal assignment documentation

servicing

collections

Do not invent partners.

==================================================

21. MOBILE FIRST

==================================================

Mobile must be exceptional.

Use:

large readable typography

touch-friendly controls

readable formulas

no horizontal overflow

smooth 3D

responsive evidence graph

responsive Capital trace

lazy loading

compressed textures

LOD

AVIF/WebP

reduced-motion

device capability detection

60fps target where practical

Visual ambition must not destroy usability.

==================================================

22. DO NOT USE

==================================================

No:

dead gradient sky

static blue background

generic AI gradient

cheap neon

cyberpunk grid

random glowing blobs

stock doctors

hospital stock photography

cartoon money

flying coins

crypto imagery

generic fintech bank photos

==================================================

23. FINAL VISUAL TEST

==================================================

Ask:

If all text disappeared,

would the site still feel like an extraordinary interactive world?

If NO:

visual system is incomplete.

If the minerals look pasted onto the background:

incomplete.

If the sky feels static:

incomplete.

If nothing moves when scrolling stops:

incomplete.

==================================================

24. FINAL QA

==================================================

Test:

Audit route

Capital route

mobile

desktop

all CTAs

specimen

calculation trace

locality consistency

2026 source/version

QP/non-QP display

modifier path

STOP behavior

borrowing base

unbound $0

live-demo BLOCK

evidence packet

keyboard navigation

reduced motion

performance

browser-only upload claim

If browser-only cannot be proven,

use bundled synthetic data instead.

==================================================

25. FINAL RECEIPT

==================================================

Do not say DONE without reporting:

- original version preserved

- new routes/components

- factual corrections

- ACH/Capital additions

- visual/world upgrades

- Swiss Cheese holes

- Six-Layer Nothing Wasted result

- two additional recent developments

- BUILD / ADOPT / PARTNER / HUMAN REVIEW / BLOCK decisions

- verified claims

- partially verified claims

- designed/unverified claims

- partner-dependent capabilities

- mobile QA

- accessibility QA

- performance QA

- remaining launch blockers

==================================================

FINAL NORTH STAR

==================================================

BILLROSETTA:

“I can see exactly where this number came from.”

BILLROSETTA CAPITAL:

“I can see exactly why this receivable did or did not qualify

to reach a capital decision.”

BillRosetta was valuable before ACH.

ACH does not replace BillRosetta.

ACH reveals the larger economic consequence of BillRosetta’s

deterministic evidence engine.

The controlling direction is now:

EVIDENCE

→ UNDERWRITING-READY INFORMATION

→ AUTHORIZATION

→ EXECUTION

while preserving:

AUDIT

RECOVERY

PAYMENT INTEGRITY

EVIDENCE

ONE CORE ENGINE.

MULTIPLE COMMERCIAL DOORS.

BUILD ONCE.

PROVE IT.

LET IT LIVE.

REUSE THE PRIMITIVE.


Save all of this please
