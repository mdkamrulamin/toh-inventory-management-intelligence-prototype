# (TOH) Inventory Management & Intelligence Prototype

An academic medication inventory dashboard developed for the University of Ottawa’s ELG 5902 Industry Project, Group 5.

The prototype demonstrates medication availability, synthetic request handoffs, inventory monitoring, simulated ordering and receiving, illustrative alternative review, and reporting.

All data are synthetic. Workflow rules, relationships and parameters reflect team research and project assumptions. They do not establish validated TOH policies or real clinical or purchasing decisions.

## Current implementation

The application provides six audience tabs:

| View | Main functionality |
| --- | --- |
| Clinical | Medication lookup, recorded availability, temporary request previews, synthetic request submission, illustrative alternative names and request progress |
| Pharmacist | Request review, return, release, recall, shortage escalation, post-receipt review and informational alternative-review records |
| Procurement | Linked shortage feedback, simulated orders, delivery-date updates, eligible cancellation, supplier/cost context and inventory analytics |
| Warehouse | Released-request fulfillment, full/partial synthetic receipts, order and receipt history, stock/location/expiry information and historical counts |
| Executive | Aggregate summaries of current session inventory |
| Reporting | Filtered inventory, analytics and request reports with native CSV exports |

Shared features include readable stock indicators, charts separated by stock unit, persistent table tools, illustrated navigation and institutional header images.

Tabs provide demonstration navigation. They do not authenticate users or enforce real access restrictions.

The synthetic workflow supports:

- **Available stock:** Clinical submits a request → Pharmacist explicitly reviews and authorizes demo release → Warehouse confirms full fulfillment.
- **Insufficient stock:** Pharmacist escalates a shortage → Procurement records feedback and confirms a simulated order → Warehouse records a receipt → Pharmacist explicitly reviews the request again → Warehouse fulfills it after valid release and sufficient stock.

Temporary previews do not create requests. Request submission, review, release and order creation do not reserve or deduct stock. Confirmed receipts increase active session stock; valid fulfillment deducts the full requested quantity once.

Orders support partial receipts and retained history. A receipt does not automatically authorize release or fulfill a request. Closing a request without fulfillment does not automatically cancel its linked order. Fulfilled requests close with a retained fulfilled outcome.

The **Alternatives (illustrative)** column shows recorded candidate names for red/yellow inventory rows. Pharmacist review provides detailed candidate information and three informational decisions:

- Keep for pharmacist consideration.
- Do not pursue in demo.
- Needs more review.

Each decision requires a reason and records an inventory snapshot. Decisions do not change the requested medication, quantity, urgency, workflow status or stock. Candidate availability follows live session inventory; earlier review snapshots remain unchanged. No clinical equivalence, dose conversion or automatic substitution is provided.

Supported analytics include illustrative financial ABC classification, monthly consumption-value analysis, stock coverage, gap below supplied reorder point and illustrative lead-time demand. Supplied reorder points, safety-stock quantities and lead times remain distinct from calculated outputs. Financial ABC is not clinical priority.

Reporting includes inventory snapshots, zero-stock records, replenishment context, supplier/cost information, expiry overviews, historical counts, inventory summaries, current requests, request summaries, stock analytics and ABC category totals.

Inventory summaries follow their selected filters. ABC classification retains the full medication-population basis before display filtering. Whole-population ABC totals and whole-session request summaries use their stated overall scope.

Normal reruns and role navigation retain submitted records within the active session. Leaving Clinical clears its medication lookup and temporary preview.

**Reset demo** restores starting inventory, clears requests, orders, receipts, alternative-review records and related inputs, and reloads the relationship fixture. Session data may be lost after browser refresh, disconnection or server restart. Separate browser sessions do not share transactions. Source CSV files are not changed by workflow actions.

## Demonstration datasets

| File | Contents | Records | Fields |
| --- | --- | ---: | ---: |
| `data/sample_medications.csv` | Original medication dataset | 6 | 10 |
| `data/sample_medications_extended.csv` | Extended medication dataset | 6 | 16 |
| `data/sample_substitute_relationships.csv` | Directed illustrative relationships | 2 | 8 |

The extended medication dataset is the default. It preserves the original medication values and adds six optional fields.

Each medication record has one representative expiry date and, where supplied, a storage location. Multiple batches and simultaneous storage locations are not modeled. Historical counts remain separate from current recorded stock.

The relationship fixture contains unvalidated demonstration links between existing medication IDs. Relationships are directional; one direction does not imply the reverse. Missing relationships are shown as unavailable recorded information rather than invented suggestions.

Validated relationships remain fixed within a demo run. Editing the fixture requires a reset or new demonstration before its new contents are used.

### Field definitions

| Field | Description |
| --- | --- |
| `medication_id` | Unique synthetic medication identifier |
| `medication_name` | Recorded medication name and strength |
| `category` | Dosage-form category, separate from financial ABC classification |
| `stock_unit` | Quantity unit, such as tablet, capsule or vial |
| `current_stock` | Recorded quantity in the medication’s stock unit |
| `unit_cost` | Synthetic CAD cost per stock unit |
| `average_monthly_consumption` | Supplied synthetic average monthly use in stock units |
| `expiry_date` | Representative expiry date |
| `supplier` | Fictional supplier |
| `status` | Availability label derived from recorded stock |
| `primary_location` | Optional representative storage location |
| `reorder_point` | Optional supplied illustrative reorder threshold |
| `safety_stock_level` | Optional supplied illustrative safety-stock quantity |
| `lead_time_days` | Optional supplied synthetic replenishment lead time |
| `last_count_date` | Optional historical count date |
| `counted_stock` | Optional quantity observed during that count |

The relationship fixture records relationship/source/candidate IDs, illustrative wording, validation status, provenance, an optional comparison note and a fixture version. Candidate stock and indicators come from active inventory rather than being stored in the relationship file.

## Data loading and validation

The medication loader:

- Preserves string identifiers, including leading zeros.
- Normalizes whitespace and applies configured column mappings.
- Requires unique medication IDs, medication names and recorded stock.
- Rejects empty datasets, duplicate columns and missing required values.
- Validates known numeric fields as finite and nonnegative.
- Parses dates using `YYYY-MM-DD`.
- Preserves unavailable optional values rather than replacing them with zero.
- Checks or derives availability labels from recorded stock.

Relationship validation checks identifiers, directed pairs, required wording, provenance and version information. Invalid rows are ignored with visible diagnostics. Missing or unreadable relationship data do not prevent existing inventory and request functions from operating.

Workflow services validate positive whole-number transaction quantities, matching units, eligible statuses and current session context. Invalid, stale or duplicate actions are rejected without partial changes.

Tables and reports use display copies. Recorded stock does not establish physical stock confirmation, clinical suitability or usable expiry. Historical count comparisons do not establish loss, shrinkage or physical reconciliation.

## Requirements

- Python 3.12
- Git
- Dependencies pinned in `requirements.txt`

Core dependencies are Streamlit 1.65.0, Pandas 3.0.6 and Plotly 7.1.0. Automated tests use Python’s built-in `unittest` framework.

## Local setup — macOS

Clone the repository:

```bash
git clone https://github.com/mdkamrulamin/toh-inventory-management-intelligence-prototype.git
cd toh-inventory-management-intelligence-prototype
```

Create and activate a virtual environment:

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

Open the local URL printed in the terminal. Press `Ctrl+C` to stop the application.

For later sessions, run from the project root:

```bash
source .venv/bin/activate
python -m streamlit run app.py
```

## Select the demonstration dataset

Set `SAMPLE_MEDICATIONS_PATH` in `src/config.py`.

Extended dataset, used by default:

```python
SAMPLE_MEDICATIONS_PATH = PROJECT_ROOT / "data" / "sample_medications_extended.csv"
```

Original dataset:

```python
SAMPLE_MEDICATIONS_PATH = PROJECT_ROOT / "data" / "sample_medications.csv"
```

The relationship fixture is configured separately:

```python
SUBSTITUTE_RELATIONSHIPS_PATH = PROJECT_ROOT / "data" / "sample_substitute_relationships.csv"
```

Stop and restart Streamlit after changing the configured medication dataset. Start a fresh demonstration when prompted.

Both medication datasets support the same synthetic workflow. Fields absent from the original dataset remain unavailable. Positive stock without a supplied reorder point has a neutral threshold indicator; zero recorded stock retains its zero-stock indicator.

### Verify dataset shapes

From the project root:

```bash
python -c "from src.data.loader import load_medications; print('Original:', load_medications('data/sample_medications.csv').shape); print('Extended:', load_medications('data/sample_medications_extended.csv').shape)"
```

Expected output:

```text
Original: (6, 10)
Extended: (6, 16)
```

## Project structure

| Location | Purpose |
| --- | --- |
| `app.py` | Application entry point and role rendering |
| `.streamlit/config.toml` | Streamlit presentation settings |
| `.devcontainer/` | Development-container configuration |
| `src/config.py` | Labels, notices, icon mappings and data paths |
| `src/data/schema.py`, `src/data/loader.py` | Medication schema, mapping and validation |
| `src/data/substitute_schema.py`, `src/data/substitute_loader.py` | Relationship contracts and fixture validation |
| `src/services/clinical.py` | Temporary request-stock comparison |
| `src/services/replenishment.py` | Shared inventory threshold indicators |
| `src/services/analytics.py` | Supported stock analytics and financial ABC classification |
| `src/services/summary.py` | Aggregate inventory summaries |
| `src/services/workflow_models.py` | Shared session and transaction contracts |
| `src/services/workflow.py` | Request transitions, release, fulfillment and reset |
| `src/services/workflow_queries.py` | Read-only role-specific inventory and request queries |
| `src/services/orders.py`, `src/services/order_queries.py` | Simulated orders and role-specific order readers |
| `src/services/receipts.py`, `src/services/receipt_queries.py` | Synthetic receipt posting and readers |
| `src/services/substitute_reviews.py`, `src/services/substitute_queries.py` | Informational alternative reviews and readers |
| `src/services/reporting.py` | Report preparation and filtering |
| `src/ui/session.py` | Shared Streamlit session-state boundary |
| `src/ui/workflow_actions.py`, `src/ui/handoff_panels.py` | Request and handoff controls |
| `src/ui/order_actions.py`, `src/ui/order_panels.py` | Simulated-order controls |
| `src/ui/receipt_actions.py`, `src/ui/receipt_panels.py` | Synthetic-receipt controls |
| `src/ui/substitute_actions.py`, `src/ui/substitute_panels.py` | Alternative information, review controls and history |
| `src/ui/components.py` | Inventory tables, stock charts and placeholders |
| `src/ui/workflow_components.py` | Shared request, order and receipt presentation |
| `src/ui/views/` | Six audience view modules |
| `src/ui/navigation.py` | Role navigation and Clinical lookup reset |
| `src/ui/styles.py`, `src/ui/styles.css` | Shared presentation |
| `src/ui/icons.py`, `src/ui/stock_indicators.py` | Role icons and stock-indicator presentation |
| `data/` | Synthetic medication datasets and relationship fixture |
| `assets/` | Role icons, logos and credits |
| `tests/` | Automated tests |
| `requirements.txt` | Pinned Python dependencies |

## Run automated tests

Run commands from the project root with the virtual environment active.

### Run the complete suite

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

A successful run ends with `OK`.

### Loader tests

```bash
python -m unittest discover -s tests -p "test_loader.py" -v
```

### Clinical request-preview tests

```bash
python -m unittest discover -s tests -p "test_clinical.py" -v
```

### Replenishment-review tests

```bash
python -m unittest discover -s tests -p "test_replenishment.py" -v
```

### Navigation callback tests

```bash
python -m unittest discover -s tests -p "test_navigation.py" -v
```

### Executive summary tests

```bash
python -m unittest discover -s tests -p "test_summary.py" -v
```

### Stock analytics tests

```bash
python -m unittest discover -s tests -p "test_analytics.py" -v
python -m unittest discover -s tests -p "test_analytics_integration.py" -v
```

### Shared workflow tests

```bash
python -m unittest discover -s tests -p "test_workflow.py" -v
```

### Workflow query tests

```bash
python -m unittest discover -s tests -p "test_workflow_queries.py" -v
```

### Session-state tests

```bash
python -m unittest discover -s tests -p "test_session.py" -v
```

### Clinical and Pharmacist action tests

```bash
python -m unittest discover -s tests -p "test_workflow_actions.py" -v
```

### Warehouse and Procurement handoff tests

```bash
python -m unittest discover -s tests -p "test_handoff_actions.py" -v
```

### Synthetic order tests

```bash
python -m unittest discover -s tests -p "test_orders.py" -v
python -m unittest discover -s tests -p "test_order_queries.py" -v
python -m unittest discover -s tests -p "test_order_actions.py" -v
```

### Receipt and post-receipt workflow tests

```bash
python -m unittest discover -s tests -p "test_receipts.py" -v
python -m unittest discover -s tests -p "test_post_receipt_workflow.py" -v
python -m unittest discover -s tests -p "test_receipt_queries_session.py" -v
python -m unittest discover -s tests -p "test_receipt_actions.py" -v
```

### Illustrative alternative and review tests

```bash
python -m unittest discover -s tests -p "test_substitute_loader.py" -v
python -m unittest discover -s tests -p "test_substitute_reviews.py" -v
python -m unittest discover -s tests -p "test_substitute_session.py" -v
python -m unittest discover -s tests -p "test_substitute_actions.py" -v
```

### Reporting tests

```bash
python -m unittest discover -s tests -p "test_reporting.py" -v
```

### Run one test method

Use `-k` with a method name from the verbose output:

```bash
python -m unittest discover -s tests -p "test_loader.py" -k "test_invalid_numbers_are_rejected" -v
```

Browser layout, scrolling, live input, cross-role navigation and actual CSV downloads also require manual checking.

## Research and implementation traceability

The prototype draws on the team’s literature review, medication-process analysis, inventory frameworks and dashboard requirements.

Supporting project documents distinguish research findings, implementation choices, team assumptions and deferred functionality. Illustrative relationships, workflow rules and supplied inventory parameters do not establish validated TOH policies or clinical eligibility.

## Deferred features and scope limitations

The prototype does not provide:

- Real clinical authorization, patient-specific processing or automatic substitution.
- Clinically validated alternative relationships, dose conversion or a substitute offer/acceptance workflow.
- Authentication, enforced user permissions or durable multi-user transaction storage.
- Real supplier orders, supplier integrations or verified physical shipment receiving.
- Receipt reversal/correction, multi-location transfers, batch-level FEFO or physical dispensing.
- Confirmed stock accuracy, reconciliation, loss or shrinkage.
- Governed clinical VEN classification, calculated safety stock or optimized reorder quantities.
- Historical hospital performance, supplier reliability, inventory turnover or validated cost savings.
- Live TOH/ERP integration, demand forecasting or AI functionality.

Synthetic receipts and fulfillment affect only active session inventory. Representative expiry dates, past counts and illustrative delivery dates are not physical verification or clinical suitability assessments.

## Assets and credits

Role icons are stored in `assets/icons/`. Source references are recorded in [assets/icons/CREDITS.md](assets/icons/CREDITS.md).

The Ottawa Hospital and uOttawa header images are stored in `assets/logos/`.

## Team and contributions

Developed by ELG 5902 Group 5:

- Md Kamrul Hasan Bin Amin
- Maria
- Maryam
- Mohtasim
- Sai Prasanna

The project combines team research, process analysis, inventory frameworks, dashboard requirements and software implementation.