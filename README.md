# (TOH) Inventory Management & Intelligence Prototype

An academic medication inventory dashboard developed for the University of Ottawa’s ELG 5902 Industry Project, Group 5.

The prototype demonstrates medication availability review, synthetic request handoffs, inventory monitoring and reporting.

All data are synthetic. Workflow choices, fields and thresholds are based on team research and project assumptions unless confirmed otherwise. The application is not intended for real clinical or purchasing decisions.

## Current implementation

The application provides six audience tabs:

| View | Main functionality |
| --- | --- |
| Clinical | Medication lookup, recorded availability, temporary request previews, synthetic request submission and status tracking |
| Pharmacist | Request queue, explicit review, return decisions, release routing and shortage escalation |
| Procurement | Linked shortage feedback, routine inventory monitoring, supplier/cost context and replenishment review |
| Warehouse | Released-request queue, simulated full-quantity fulfillment, stock/location/expiry information and historical counts |
| Executive | Aggregate summaries calculated from current session inventory |
| Reporting | Filtered inventory reports, current request information, summaries and CSV exports |

Shared features include stock-review indicators, charts separated by stock unit, readable tables, persistent table tools, illustrated navigation and institutional header images.

Tabs provide demonstration navigation. They do not authenticate users or enforce real access restrictions.

The synthetic workflow supports two paths:

- Available stock: Clinical submits → Pharmacist reviews and authorizes demo release → Warehouse confirms full fulfillment.
- Unavailable or insufficient stock: Clinical submits → Pharmacist confirms a shortage → Procurement records feedback visible to Clinical and Pharmacist.

Preview does not create a request. Submission and review do not reserve or deduct stock. Valid Warehouse fulfillment deducts the full quantity once from active session inventory.

Fulfilled requests close with a retained fulfilled outcome. Closure without supply is recorded separately. Procurement feedback and illustrative delivery dates do not add inventory or create orders.

Normal reruns and tab navigation retain submitted requests. Leaving Clinical clears its medication lookup and temporary preview.

**Reset demo** restores starting inventory and clears requests, history and related inputs. Session data are temporary and may be lost after browser refresh, disconnection or server restart. Source CSV files remain unchanged.

Reporting includes inventory snapshots, zero-stock records, replenishment review, supplier/cost reports, expiry overviews, inventory summaries, historical count observations, current requests and a whole-session request summary.

Inventory summaries follow the selected inventory filters. The whole-session request summary always includes all session requests. Reports include synthetic-data notices and scope information and use the existing table toolbar for CSV downloads.

## Demonstration datasets

| Dataset | Records | Fields |
| --- | ---: | ---: |
| `data/sample_medications.csv` | 6 | 10 |
| `data/sample_medications_extended.csv` | 6 | 16 |

The extended dataset is the default. It preserves the original medication values and adds six optional fields.

Each record represents one medication with a representative expiry date and, where supplied, a location. Multiple batches and simultaneous storage locations are not modeled.

Historical counts remain separate from current recorded stock.

### Field definitions

| Field | Description |
| --- | --- |
| `medication_id` | Unique synthetic medication identifier |
| `medication_name` | Medication name and strength |
| `category` | Dosage-form category, not ABC classification |
| `stock_unit` | Quantity unit, such as tablet, capsule or vial |
| `current_stock` | Recorded quantity in the medication’s stock unit |
| `unit_cost` | Synthetic CAD cost per stock unit |
| `average_monthly_consumption` | Synthetic monthly use in stock units |
| `expiry_date` | Representative expiry date |
| `supplier` | Fictional supplier |
| `status` | Recorded-stock availability label |
| `primary_location` | Optional representative storage location |
| `reorder_point` | Optional illustrative reorder threshold |
| `safety_stock_level` | Optional illustrative safety-stock quantity |
| `lead_time_days` | Optional synthetic replenishment lead time |
| `last_count_date` | Optional historical count date |
| `counted_stock` | Optional quantity observed during that count |

## Data loading and validation

The loader:

- Preserves string identifiers, including leading zeros.
- Normalizes whitespace and applies configured column mappings.
- Requires unique medication IDs, medication names and recorded stock.
- Rejects empty datasets, duplicate columns and missing required values.
- Validates known numeric fields as finite and nonnegative.
- Parses dates using `YYYY-MM-DD`.
- Preserves unavailable optional values rather than replacing them with zero.
- Checks or derives availability labels from recorded stock.

Request services require positive whole-number quantities and matching stock units. Invalid actions are rejected without partial workflow or inventory changes.

Tables and reports format display copies without modifying source data. Recorded availability does not establish physical stock confirmation, clinical suitability or usable expiry.

## Requirements

- Python 3.12
- Git
- Dependencies pinned in `requirements.txt`

Core dependencies are Streamlit 1.65.0, Pandas 3.0.6 and Plotly 7.1.0. Tests use Python’s built-in `unittest` framework.

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

Stop and restart Streamlit after changing the configured path. Start a fresh demonstration when switching datasets.

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
| `src/config.py` | Labels, notices, icon mappings and dataset path |
| `src/data/` | Schema, column mapping, loading and validation |
| `src/services/clinical.py` | Temporary request-stock comparison |
| `src/services/replenishment.py` | Shared stock-review classification |
| `src/services/summary.py` | Inventory summaries |
| `src/services/workflow_models.py` | Shared request and session contracts |
| `src/services/workflow.py` | Request transitions, fulfillment and reset |
| `src/services/workflow_queries.py` | Read-only role-specific queries |
| `src/services/reporting.py` | Report preparation and filtering |
| `src/ui/session.py` | Shared Streamlit session-state boundary |
| `src/ui/workflow_actions.py` | UI callbacks for workflow actions |
| `src/ui/handoff_panels.py` | Warehouse and Procurement handoff controls |
| `src/ui/components.py` | Inventory tables, charts and placeholders |
| `src/ui/workflow_components.py` | Request tables, selectors and details |
| `src/ui/views/` | Six audience view modules |
| `src/ui/navigation.py` | Role tabs and Clinical lookup reset |
| `src/ui/styles.py`, `src/ui/styles.css` | Shared presentation |
| `src/ui/icons.py`, `src/ui/stock_indicators.py` | Role icons and inventory indicators |
| `data/` | Original and extended synthetic CSV files |
| `assets/` | Role icons, logos and credits |
| `tests/` | Automated tests |
| `requirements.txt` | Pinned dependencies |

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

### Reporting tests

```bash
python -m unittest discover -s tests -p "test_reporting.py" -v
```

### Run one test method

Use `-k` with a method name from the verbose output:

```bash
python -m unittest discover -s tests -p "test_loader.py" -k "test_invalid_numbers_are_rejected" -v
```

Browser layout, scrolling, live input, navigation and actual CSV downloads also require manual checking.

## Research and implementation traceability

The prototype draws on the team’s literature review, process mapping, inventory frameworks and dashboard requirements.

Supporting project documentation distinguishes research findings, implementation choices, team assumptions and deferred functionality. These sources do not establish that the demonstration workflow or parameters are validated TOH policies.

## Deferred features and scope limitations

The prototype does not provide:

- Real clinical authorization, automatic substitution or patient-specific processing.
- Authentication, enforced user permissions or durable multi-user storage.
- Real purchase orders, supplier transactions or stock receiving.
- Multi-location transfers, batch-level FEFO or physical dispensing.
- Confirmed reconciliation, stock accuracy, loss or shrinkage.
- Implemented ABC/VEN classification or optimized order quantities.
- Historical hospital performance, supplier reliability or inventory turnover.
- Live TOH/ERP integration, forecasting or AI functionality.

Stock changes represent synthetic session fulfillment only. Historical count observations and illustrative supply dates must not be interpreted as physical inventory verification or confirmed delivery.

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