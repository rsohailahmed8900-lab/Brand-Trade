# Brand Traders – Streamlit Sales Analysis

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```
The 7 CSVs are in `data/`. You can also upload your own versions from the sidebar
(files must be named customers, employees, orders, order_details, products, categories, shippers .csv).

## Files
- `app.py` – Streamlit UI (7 tabs + sidebar filters)
- `analysis.py` – loading, joins, metrics, auto-written report (no Streamlit dependency)
- `data/` – the source CSVs
"# Brand-Trade" 
