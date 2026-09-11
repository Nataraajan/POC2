# Validation — 11 September 2026

`python -m pytest tests -q`: **6 passed**, 7.07 seconds on the final formatted code.

- Default Short-Term forecast matches the original engine across every numeric column.
- Application volume scales forecast results correctly; switching views retains inputs.
- Combined results equal the sum of both products.
- Applying historical curves changes revenue; returning to manual restores saved assumptions.
- Gross CLAB, reserve and net revenue reconcile for every month.
- A 25-month forecast returns eight complete quarterly periods; reset returns to 24 months.
- Zero applications and zero yield produce the expected zero outputs.
- The unchanged standalone vintage app starts without a Streamlit exception.

Live browser checks at localhost:8501:

- Main dashboard, cards, default overlay, revenue plot and monthly schedule render.
- Historical-curve action selects the historical source and marks the plotted curve as applied.
- Changing applications from 30,000 to 60,000 changes total revenue from $147.39M to $294.77M.
- Forecast table tab renders the loan-book chart, period controls and exports.
- Monthly forecast CSV download triggers successfully.

Test environment: Python 3.11; Streamlit 1.63.0; pandas 3.0.5;
NumPy 2.4.6; Plotly 7.0.0; PyArrow 25.0.1; pytest 9.1.1.

No financial-engine or pipeline source changes. No new raw-loan aggregation
benchmark was performed. The 2M-row dataset is represented by its original
committed aggregate outputs; this work does not claim a fresh 2M-row run.
