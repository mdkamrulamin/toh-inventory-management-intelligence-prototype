# (TOH) Inventory Management & Intelligence Prototype

A literature-informed academic medication inventory dashboard developed for the University of Ottawa’s ELG 5902 Industry Project, Group 5.

The prototype demonstrates how medication inventory information can support clinical availability review, procurement and ordering review, warehouse operations, and executive oversight.

All inventory values are synthetic. Where TOH-specific requirements have not been confirmed, the data fields, thresholds, interface behavior, and workflow interpretations remain project assumptions and team design proposals.

This application does not represent actual TOH operations or provide validated clinical or purchasing decisions.

## Current implementation

The application includes:

- A modular Streamlit application with four audience tabs.
- Short role labels, illustrated role icons, and audience-specific process descriptions.
- The Ottawa Hospital and uOttawa logos beside the project title.
- Shared typography, audience banners, responsive styling, and visible keyboard focus.
- Original and extended synthetic medication datasets.
- CSV loading, configurable column mapping, and basic data validation.
- Readable table labels separated from internal data-field names.
- Date-only table formatting using `YYYY-MM-DD`.
- Always-visible native table tools with readable labels.
- Native CSV downloads from the five medication tables.
- Clinical medication lookup and selected recorded-stock information.
- Stock-aware, nonpersisted Clinical request previews.
- Resetting of the Clinical selection and preview when leaving the Clinical tab.
- Shared inventory-review colors, badges, table styling, and explanatory legends.
- Compact stock charts separated by physical stock unit.
- Representative warehouse locations and historical count observations.
- Aggregate-only Executive snapshot summaries and synthetic inventory valuation.
- Clearly labelled placeholders for deferred features.
- An automated suite containing 39 test methods.

## Dashboard audiences

| Tab | Intended audience | Implemented information | Proposed process connection |
| --- | --- | --- | --- |
| Clinical | Doctors and nurses | Medication lookup, recorded stock and availability, selected inventory-review badge, and demo request previews | Medication request and availability review; clinical/pharmacy approval remains a human responsibility |
| Procurement | Procurement and inventory/ordering staff | Stock, consumption, costs, suppliers, expiry dates, optional thresholds and lead times, ordering-review context, and stock charts | Inventory verification, replenishment review, and supplier-order review |
| Warehouse | Warehouse and inventory operations staff | Recorded stock, representative locations, expiry dates, ordering-review context, historical count observations, and stock charts | Receiving, storage, distribution, physical counting, and reconciliation |
| Executive | Management and executive users | Aggregate sample SKU counts, zero-stock snapshot share, synthetic inventory value, and known suppliers | Overall inventory monitoring and policy review |

These process connections are project interpretations of the proposed workflow, not confirmation that the application implements TOH’s operational process.

All four tabs are available during the demonstration. Navigation does not implement authentication or role-based authorization.

There is no separate patient-facing, Pharmacist, Finance, or Reporting page. Financial information currently appears within Procurement and Executive.

## Sprint 4 implementation status

The four assigned Sprint 4 implementation tasks have been completed and pushed.

| Issue or change | Implemented behavior | Commit |
| --- | --- | --- |
| SCRUM-60 | Improved readability, illustrated role navigation, shared styling, and institutional header | `d83b077` |
| SCRUM-61 | Shared recorded-stock review rules, colors, badges, legends, and chart indicators | `17fdbc1` |
| SCRUM-62 | Always-visible, labelled native table tools merged with each table | `e18ae10` |
| SCRUM-68 | Clinical medication selection and preview clear when leaving Clinical | `d4e7503` |
| Toolbar follow-up | Removed the observed toolbar flicker when switching role tabs | `a1fd54a` |

The implementation checkpoint documented here is `a1fd54a`.

The developer reported the automated suite passing after SCRUM-68 and manually verified the subsequent CSS-only toolbar fix.

Independent interface acceptance verification under SCRUM-65 and the final regression/release checkpoint under SCRUM-66 remain separate closeout activities. This README update alone does not establish their completion.

### Historical MVP baseline

The frozen Sprint 3 MVP baseline remains:

`7269e0a363ecff9d70392458a75c2f8034a2953f`

Sprint 4 changes are subsequent improvements to that baseline.

The original Sprint 3 AT-08b navigation failure must remain in the historical acceptance record. The corrected behavior is recorded separately as a Sprint 4 retest.

## Demonstration datasets

| Dataset | Records | Fields | Purpose |
| --- | ---: | ---: | --- |
| `data/sample_medications.csv` | 6 | 10 | Original dataset and backward-compatibility checks |
| `data/sample_medications_extended.csv` | 6 | 16 | Default dataset with optional demonstration fields |

The extended dataset preserves the original records and fields, adding six optional fields.

### Field definitions

| Field | Meaning |
| --- | --- |
| `medication_id` | Unique sample medication identifier |
| `medication_name` | Medication name and strength |
| `category` | Dosage-form category; not ABC classification |
| `stock_unit` | Physical unit used for quantities, such as tablet, capsule, or vial |
| `current_stock` | Recorded quantity in the row’s stock unit |
| `unit_cost` | Synthetic CAD cost per stock unit |
| `average_monthly_consumption` | Synthetic stock units consumed per month |
| `expiry_date` | One representative expiry date associated with the medication record |
| `supplier` | Fictional supplier |
| `status` | Basic recorded-stock availability label |
| `primary_location` | Optional single representative storage location |
| `reorder_point` | Optional illustrative reorder threshold, using the row’s stock unit |
| `safety_stock_level` | Optional illustrative safety-stock quantity |
| `lead_time_days` | Optional synthetic replenishment lead time |
| `last_count_date` | Optional date of a historical synthetic count |
| `counted_stock` | Optional quantity observed during that historical count |

The optional fields are proposed demonstration inputs, not confirmed TOH fields or measurements.

Each row represents one medication/SKU with one representative location and expiry attribute. Multiple lots, simultaneous storage locations, transactions, and historical inventory balances are not modeled.

Historical counts never replace current recorded stock. For example:

- MED001 has recorded stock 1,200 and a past counted quantity of 1,195.
- MED004 has recorded stock 900 and a past counted quantity of 895.

Transactions since those counts are unknown. These differences do not establish current stock inaccuracy, loss, or shrinkage.

## Data loading and validation

The loader:

- Reads source values as strings to preserve identifiers with leading zeros.
- Trims surrounding header and value whitespace.
- Applies mappings configured in `src/data/schema.py`.
- Rejects duplicate field names after normalization or mapping.
- Requires `medication_id`, `medication_name`, and `current_stock`.
- Rejects empty datasets, missing identifiers, and duplicate medication IDs.
- Parses known numeric fields when present.
- Rejects nonnumeric, negative, and infinite numeric values.
- Requires a stock quantity for every record.
- Parses present date fields using `YYYY-MM-DD`.
- Rejects invalid date formats and invalid calendar dates.
- Preserves missing optional values rather than substituting zero.
- Preserves additional source columns for future features.
- Checks supplied availability labels against recorded stock.

Basic recorded availability is:

| Recorded stock | Availability |
| --- | --- |
| Greater than zero | In stock |
| Equal to zero | Out of stock |

Missing availability labels are derived. Conflicting supplied labels are rejected.

These labels do not confirm physical availability, usable expiry, clinical suitability, or availability elsewhere.

### Display formatting

Tables use presentation copies of the loaded data:

- Internal field names receive centrally configured readable labels.
- Dates display as `YYYY-MM-DD`.
- Missing display dates and stock units appear as `N/A`.
- Inventory-review cells receive shared color styling where applicable.
- Source CSV files and loaded datetime values are not modified.

Display formatting does not bypass loader validation of source dates.

## Clinical lookup and request previews

Clinical initially displays all six medication records.

Selecting a medication displays:

- Medication name and ID.
- Recorded stock.
- Stock unit.
- Basic recorded availability.
- An illustrative inventory-threshold review badge.

The medication lookup also restricts the availability table to the selected record.

A demo request accepts a positive whole-number quantity and compares it with the selected medication’s recorded stock.

| Recorded condition | Preview outcome |
| --- | --- |
| Stock equals zero | Unable to fulfill from recorded stock; pharmacy review is required |
| Positive stock is greater than or equal to the requested quantity | Sufficient recorded stock for that quantity; proposed next step is pharmacist verification |
| Positive stock is below the requested quantity | Requested quantity exceeds recorded stock; review is needed |

Every preview includes the selected medication, ID, requested quantity, stock unit, and recorded-stock comparison.

The zero-stock message describes possible review paths in the proposed process. It does not select a substitute, initiate redistribution, or trigger procurement.

### Preview and navigation behavior

- A preview appears only after pressing **Preview demo request**.
- Changing medication clears the previous preview.
- Committing a quantity change clears the previous preview.
- Leaving Clinical clears the selected medication and previous preview.
- Returning to Clinical shows the blank lookup and all six medication records.
- A fresh medication selection and Preview click are required.
- The navigation callback does not intentionally reset unrelated view state.

The application uses state-aware Streamlit tabs so role changes trigger a rerun.

Nothing is saved, submitted, sent, deducted, or approved.

### Threshold context is separate from request fulfillment

The inventory-review badge compares stock with an illustrative reorder point. The request preview compares stock with the requested quantity.

These answer different questions. A medication can be below its illustrative reorder point while still having enough recorded stock for a small demo request.

Neither comparison confirms physical stock or clinical suitability.

## Recorded-stock review indicators

The same service supplies inventory-review labels to the Clinical badge, Procurement replenishment table, Warehouse stock table, and Procurement/Warehouse stock charts.

| Condition | Color | Displayed review |
| --- | --- | --- |
| Recorded stock equals zero | Red | Recorded stock = 0 — availability/order review |
| Positive stock is at or below a supplied reorder point, with a known stock unit | Yellow | At/below illustrative reorder threshold — review |
| Positive stock exceeds a supplied reorder point, with a known stock unit | Green | Above illustrative reorder threshold |
| Positive stock has no supplied reorder point | Neutral | N/A — reorder point unavailable |
| Positive stock has a supplied reorder point but no usable stock unit | Neutral | N/A — stock unit unavailable |

Zero recorded stock takes precedence even when threshold or unit information is unavailable.

An explicitly supplied reorder point of zero is valid; it is not treated as missing.

Safety stock, lead time, expiry dates, and historical counts do not override these review results. No order quantity is calculated.

### Expected sample examples

| Medication | Extended dataset result |
| --- | --- |
| MED003 — Ibuprofen 200 mg | Red: recorded stock is zero |
| MED006 — Ceftriaxone 1 g | Yellow: stock 80 is below reorder point 90 |
| MED001 — Paracetamol 500 mg | Green: stock 1,200 exceeds reorder point 800 |

With the original dataset, positive-stock records have neutral review context because reorder points are absent. MED003 retains its red zero-stock result.

Color is accompanied by text and explanatory legends. These colors do not represent clinical urgency, treatment priority, optimal inventory, or guaranteed request fulfillment.

Audience banner colors identify dashboard roles and have a separate meaning.

## Stock charts

Procurement and Warehouse share a reusable stock-chart component.

Charts:

- Keep tablets, capsules, and vials in separate groups.
- Adjust height to the number of medications in each group.
- Display recorded quantities, medication labels, and review information.
- Use the shared recorded-stock review colors.
- Retain zero-stock medication categories.
- Add a visible marker for zero-stock records.
- Omit records with missing stock units and display an explanatory notice.

Unlike physical units are never summed into one stock total.

Executive does not display item-level stock charts.

## Table tools and CSV downloads

The five medication tables provide an always-visible native toolbar with readable labels:

- Show/hide columns.
- Download as CSV.
- Search.
- Fullscreen.

The toolbar and table appear as one panel. Toolbar positioning uses normal layout flow so it can wrap without the previous external positioning offsets.

### Tables available for export

With the supplied samples and default column visibility:

| View and table | Expected rows | Expected columns |
| --- | ---: | ---: |
| Clinical availability | 6 initially; 1 after medication selection | 4 |
| Procurement inventory | 6 | 8 |
| Procurement replenishment context | 6 | 8 |
| Warehouse representative stock | 6 | 8 |
| Warehouse historical counts | 6 | 6 |

Executive has no medication table or corresponding table CSV download.

### Export behavior and limitations

- Downloads use Streamlit’s native table export.
- The format is CSV, not an Excel workbook.
- Exported columns and row order follow the native table state.
- Clinical medication selection restricts the underlying table and export.
- Cell selection does not create a selected-cells-only CSV.
- Native table search does not restrict the export to matching cells.
- CSV files contain values and headers, not the table’s colors or styling.
- Downloading does not change stock or submit a request.

Streamlit 1.65 generates a filename in this form:

`YYYY-MM-DDTHH-MM_export.csv`

The native toolbar does not expose a configurable filename. The timestamp filename is an accepted prototype limitation.

There is no separate custom download button.

Toolbar styling depends on Streamlit’s internal markup. Recheck toolbar visibility, labels, wrapping, fullscreen, and downloads before upgrading Streamlit.

## Executive snapshot summaries

Both complete sample datasets produce:

| Summary | Expected value |
| --- | ---: |
| Sample SKUs | 6 |
| Recorded zero-stock SKUs | 1 |
| Zero-stock share — snapshot | 16.7% |
| Sample inventory value | CAD 801.00 |
| Known demo suppliers | 3 |
| Inventory turnover | N/A — placeholder |

Zero-stock share is calculated as:

`zero-stock SKU count / total SKU count × 100`

This describes a snapshot, not a stockout rate over time.

Synthetic inventory value is calculated as:

`sum(current_stock × unit_cost)`

CAD values share a monetary unit and can be summed. Tablet, capsule, and vial quantities are not combined into a physical stock total.

If any unit cost is missing, valuation remains unavailable rather than displaying a partial total.

Supplier count remains unavailable when the supplier column or all supplier values are missing.

Inventory turnover is not calculated because its definition, reporting period, and supporting historical records remain to be confirmed.

## Requirements

- Python 3.12.
- Git.
- Dependencies pinned in `requirements.txt`.

Core application versions currently pinned:

| Package | Version |
| --- | --- |
| Streamlit | 1.65.0 |
| Pandas | 3.0.6 |
| Plotly | 7.1.0 |

Tests use Python’s built-in `unittest` framework. No additional test framework is required.

Use the pinned environment when reproducing behavior, particularly state-aware tabs and native toolbar styling.

## Local setup — macOS

Clone the repository:

```bash
git clone https://github.com/mdkamrulamin/toh-inventory-management-intelligence-prototype.git
cd toh-inventory-management-intelligence-prototype
```

Create and activate a virtual environment using Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the application:

```bash
python -m streamlit run app.py
```

Open the local URL printed in the terminal.

Press `Ctrl+C` to stop the application.

For later sessions, run these commands from the project root:

```bash
source .venv/bin/activate
python -m streamlit run app.py
```

If the repository was cloned into a differently named folder, use that folder as the project root.

## Select the demonstration dataset

The default is configured in `src/config.py`.

Extended dataset:

```python
SAMPLE_MEDICATIONS_PATH = PROJECT_ROOT / "data" / "sample_medications_extended.csv"
```

Original dataset:

```python
SAMPLE_MEDICATIONS_PATH = PROJECT_ROOT / "data" / "sample_medications.csv"
```

After changing the setting, save the file and stop/restart Streamlit so imported configuration and loader defaults are refreshed.

Restore the extended dataset after cross-dataset verification.

### Verify dataset shapes

From the project root:

```bash
python -c "from src.data.loader import load_medications; print(load_medications('data/sample_medications.csv').shape)"
```

Expected:

```text
(6, 10)
```

For the extended dataset:

```bash
python -c "from src.data.loader import load_medications; print(load_medications('data/sample_medications_extended.csv').shape)"
```

Expected:

```text
(6, 16)
```

## Project structure

| Location | Purpose |
| --- | --- |
| `app.py` | Application entry point, shared loading, and role-view rendering |
| `.streamlit/config.toml` | Theme, typography, and native data-export configuration |
| `src/config.py` | Notices, role labels/icons, process context, field labels, and data path |
| `src/data/schema.py` | Required fields, numeric/date fields, optional fields, and column mapping |
| `src/data/loader.py` | CSV loading, parsing, validation, and recorded availability |
| `src/services/clinical.py` | Validated, nonmutating request-stock comparison |
| `src/services/replenishment.py` | Shared illustrative ordering-review classification |
| `src/services/summary.py` | Executive snapshot counts, share, and valuation |
| `src/ui/components.py` | Shared tables, stock charts, and feature placeholders |
| `src/ui/navigation.py` | Illustrated tabs and Clinical reset callback |
| `src/ui/stock_indicators.py` | Shared review colors, cell styles, badges, and legends |
| `src/ui/styles.py` | Stylesheet loading, branded header, role headings, and chart styling |
| `src/ui/styles.css` | Shared presentation, tab styling, and persistent native table toolbar |
| `src/ui/icons.py` | Loading local role icons for navigation and headings |
| `src/ui/views/__init__.py` | Mapping of stable role IDs to view functions |
| `src/ui/views/clinical.py` | Medication lookup, availability, and demo request previews |
| `src/ui/views/procurement_inventory.py` | Procurement inventory and replenishment context |
| `src/ui/views/warehouse.py` | Representative warehouse stock and historical counts |
| `src/ui/views/executive.py` | Aggregate Executive summaries and KPI placeholders |
| `assets/icons/` | Local illustrated role icons |
| `assets/icons/CREDITS.md` | Icon source references |
| `assets/logos/` | Institutional header images |
| `data/sample_medications.csv` | Original synthetic dataset |
| `data/sample_medications_extended.csv` | Extended synthetic dataset |
| `tests/test_loader.py` | Loader and dataset checks |
| `tests/test_clinical.py` | Clinical preview service checks |
| `tests/test_replenishment.py` | Inventory-review rules and missing-input checks |
| `tests/test_navigation.py` | Clinical reset callback checks |
| `tests/test_summary.py` | Executive calculations and missing-data checks |
| `requirements.txt` | Pinned Python dependencies |
| `.gitignore` | Files excluded from version control |
| `README.md` | Scope, setup, behavior, and verification instructions |

Package initialization files are included under `src/`.

The structure separates data loading, calculation services, shared presentation, and role-specific views so assumptions and requirements can be revised without combining everything in `app.py`.

## Run automated tests

Run all commands from the project root with the virtual environment active:

```bash
source .venv/bin/activate
```

### Run the complete suite

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

The current suite contains:

| Test module | Test methods |
| --- | ---: |
| `test_loader.py` | 11 |
| `test_clinical.py` | 8 |
| `test_replenishment.py` | 12 |
| `test_navigation.py` | 3 |
| `test_summary.py` | 5 |
| Total | 39 |

Expected successful summary:

```text
Ran 39 tests in ...

OK
```

Execution time varies. Several methods contain subcases, so the number of scenarios exceeds the method count.

### Loader tests

```bash
python -m unittest discover -s tests -p "test_loader.py" -v
```

Expected: **11 tests**.

Coverage includes original/extended dataset compatibility, optional field types, missing optional values, invalid numbers and dates, missing stock, availability consistency, leading-zero identifiers, duplicate identifiers, and required columns.

### Clinical request-preview tests

```bash
python -m unittest discover -s tests -p "test_clinical.py" -v
```

Expected: **8 tests**.

Coverage includes zero, sufficient, equal-to-stock, and insufficient-stock outcomes; identity and stock units; invalid quantities; historical-count separation; and source-record nonmutation.

### Replenishment-review tests

```bash
python -m unittest discover -s tests -p "test_replenishment.py" -v
```

Expected: **12 tests**.

Coverage includes:

- Zero-stock precedence.
- Below, equal, and above-threshold boundaries.
- Stock 91 against reorder point 90.
- Missing or blank reorder points.
- Explicit zero reorder points.
- Missing or blank stock units.
- Supporting fields not overriding recorded-stock classification.
- Expected results with both sample datasets.
- Source-data nonmutation.

### Navigation callback tests

```bash
python -m unittest discover -s tests -p "test_navigation.py" -v
```

Expected: **3 tests**.

Coverage includes:

- Selecting another role clears the Clinical lookup.
- A callback with Clinical active does not itself clear the current selection.
- Unrelated session-state values are preserved.

These tests exercise the callback using mocked session state. They do not simulate real browser tab clicks or verify removal of rendered preview messages.

### Executive summary tests

```bash
python -m unittest discover -s tests -p "test_summary.py" -v
```

Expected: **5 tests**.

Coverage includes expected summaries with both datasets, missing costs, unavailable suppliers, empty snapshots, and source-data nonmutation.

### Run one test method

Use `-k` with a method name from verbose test output.

Loader numeric validation:

```bash
python -m unittest discover -s tests -p "test_loader.py" -k "test_invalid_numbers_are_rejected" -v
```

Clinical quantity above stock:

```bash
python -m unittest discover -s tests -p "test_clinical.py" -k "test_quantity_above_stock_requires_review" -v
```

Reorder boundary:

```bash
python -m unittest discover -s tests -p "test_replenishment.py" -k "test_below_and_equal_threshold_require_review" -v
```

Clinical selection reset:

```bash
python -m unittest discover -s tests -p "test_navigation.py" -k "test_other_roles_clear_clinical_selection" -v
```

Missing-cost handling:

```bash
python -m unittest discover -s tests -p "test_summary.py" -k "test_missing_cost_prevents_partial_valuation" -v
```

All subcases within the selected method run together.

Automated tests do not replace browser checks for navigation, toolbar layout, downloads, date display, chart readability, or preview visibility.

## Manual verification

Complete the relevant checks with both sample datasets. Restore the extended default afterward.

### Shared interface

- Exactly four tabs appear: Clinical, Procurement, Warehouse, and Executive.
- Institutional logos, title, subtitle, role icons, and process descriptions display correctly.
- Synthetic-data and demonstration-access notices remain visible.
- Tabs remain usable at normal and narrower browser widths.
- Keyboard focus is visible.
- Switching tabs does not produce the previously observed toolbar jump.
- Missing optional extension fields do not prevent views from loading.

### Clinical request behavior

- The initial table contains six medications.
- Selecting a medication restricts the table to that record.
- MED003, quantity 3, produces the zero-stock review outcome.
- MED001, quantity 3, produces the sufficient-recorded-stock outcome.
- MED001, quantity 1500, produces the insufficient-recorded-stock outcome.
- Capsule and vial records retain their correct units.
- Changing medication or committing a quantity edit clears the old preview.
- Generating previews does not change stock.
- Costs and supplier information are absent from Clinical.
- Clinical/pharmacy review, substitute information, and alerts remain placeholders.

### Sprint 4 AT-08b navigation retest

1. Open Clinical.
2. Select MED003 and enter quantity 3.
3. Press **Preview demo request**.
4. Confirm the zero-stock warning appears.
5. Switch to Procurement.
6. Return to Clinical.
7. Confirm the lookup is blank, the previous preview is absent, and all six records appear.
8. Select MED003 again and press Preview.
9. Confirm a fresh preview appears.
10. Repeat with MED001 and confirm recorded stock remains unchanged.

Record this as a new Sprint 4 result. Preserve the original Sprint 3 acceptance outcome.

### Procurement and Warehouse

- MED003 is red in the applicable review displays.
- With the extended dataset, MED006 is yellow and MED001 is green.
- With the original dataset, positive-stock records have neutral threshold context.
- Review text agrees across badges, tables, and chart hover information.
- Expiry and count dates display without time components.
- Missing optional locations, dates, counts, and thresholds display appropriately.
- Historical counts do not overwrite recorded stock.
- No purchase order, order quantity, stock movement, or reconciliation result is created.

### Stock charts

- Tablet, capsule, and vial quantities remain separate.
- Medication labels, values, and hover details remain readable.
- MED003 remains visible with a zero-stock marker.
- The one-item vial chart remains readable.
- Records without stock units are omitted with an explanatory notice.
- Executive remains free of item-level stock charts.

### Native table tools and downloads

- All five tables show their tools without requiring hover.
- Toolbar controls have readable labels.
- Toolbar and table borders form one panel.
- Wrapped controls do not overlap the table.
- Search, column visibility, fullscreen, and CSV download work.
- Fullscreen can be entered and exited successfully.
- A downloaded CSV opens or re-imports successfully.
- Default exports contain the expected rows, columns, readable headers, dates, stock units, and zero-stock values.
- Clinical exports reflect the medication lookup selection.
- Timestamp-based filenames are accepted.
- Downloads do not change inventory.

### Executive

- Sample SKUs: 6.
- Recorded zero-stock SKUs: 1.
- Zero-stock snapshot share: 16.7%.
- Sample inventory value: CAD 801.00.
- Known demo suppliers: 3.
- Inventory turnover: N/A.
- Snapshot values are not described as actual TOH performance or historical trends.

### Invalid source data

Using a separate temporary CSV and a temporary application-path change, confirm that an invalid required stock value produces a clear loading error.

Do not overwrite the supplied sample datasets. Restore the extended default after the check.

## Verification records and closeout

Record:

- The tested commit.
- Environment and dataset.
- Actual test command and passing/failing totals.
- Browser acceptance outcomes.
- Relevant screenshot, recording, or downloaded-file references.
- Remaining defects or accepted limitations.

The automated suite was reported passing after SCRUM-68. The subsequent toolbar CSS fix was manually verified by the developer.

Final regression at the completed Sprint 4 checkpoint and independent acceptance remain separate verification steps.

Before committing changes, review:

```bash
git diff --check
git diff
git status --short
```

After committing and pushing, confirm:

```bash
git branch --show-current
git status --short
git log -1 --oneline
```

An empty `git status --short` output indicates a clean working tree.

## Research and implementation traceability

Project records distinguish:

- Supervisor guidance.
- Literature findings.
- Proposed process interpretations.
- Team design assumptions.
- Synthetic inputs.
- Derived demonstration results.
- Tested implementation.
- Deferred features.

The three-way request-stock comparison and illustrative threshold rules are project implementations using synthetic inputs. They are not validated TOH clinical or purchasing rules.

Date formatting, audience colors, icon choices, toolbar presentation, and navigation reset behavior are interface design decisions.

Maintain links between research findings, agreed assumptions, implementation paths, test/manual results, and commit references in the project traceability records.

Verifying a placeholder confirms its presentation and scope boundary; it does not mean the underlying workflow or analytics has been implemented.

## Deferred features and scope limitations

The following remain placeholders or outside the current implementation:

- Submitted medication requests and clinical/pharmacy approvals.
- Validated substitute-product relationships or recommendations.
- Confirmed clinical availability-alert rules.
- ABC financial classification and clinical-criticality classification.
- Replenishment-method selection and calculated order quantities.
- Purchase orders and supplier-order processing.
- Batch-specific expiry monitoring and FEFO decisions.
- Receiving, picking, dispatch, stock movements, and transfers.
- Count-time balances and reconciliation.
- Stock-accuracy, loss, or shrinkage conclusions.
- Inventory turnover and historical performance trends.
- Separate Pharmacist or Reporting views.
- Patient records and patient-facing workflows.
- Authentication and role-based authorization.
- Live TOH/ERP integration.
- Production databases, automated dispensing, forecasting engines, AI models, and advanced optimization.

The prototype uses local CSV files and a single-record-per-medication model. No request is submitted or approved, no stock is deducted, and no purchasing action is executed.

Emergency workflows are outside the proposed prototype process.

All data, comparisons, thresholds, and metrics are educational demonstrations and must not be used for clinical or purchasing decisions.

## Assets and credits

Role icons are stored locally in `assets/icons/`. Source references are recorded in [assets/icons/CREDITS.md](assets/icons/CREDITS.md).

Institutional header images are stored in `assets/logos/`.

The academic demonstration does not imply operational deployment or institutional endorsement.

## Team and contributions

Developed by ELG 5902 Group 5:

- Md Kamrul Hasan Bin Amin
- Maria
- Maryam
- Mohtasim
- Sai Prasanna

The prototype incorporates the team’s literature findings, process analysis, inventory frameworks, dashboard requirements, and software implementation.

TOH-specific requirements that have not been confirmed remain explicitly treated as assumptions or proposals.