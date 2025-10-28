## Files:
- `app.py`: Contains the streamlit application (calendar)
- `integrated-timeline.ipynb`: Contains the code for deriving recommendations from clean data
- `rule-mining.ipynb`: Basic recommendation trial notebook (not required for deployment)
- `data.xlsx`: Uncleaned Raw data
- `cleaned_data.xlsx`: Cleaned data ready for processessing 
- `recommendationsOutput.xlsx`: Output file from `integrated-timeline.ipynb`

## Steps:
1. Create virtual Environment (one can use `UV` or `pip` for this project)
for UV
```bash
uv venv
uv sync
```
for pip
```bash
python -m venv venv
venv/scripts/activate # source venv/bin/activate for linux
pip install -r requirements.txt
```

2. If you want to get your own output file then go and run all the cells of `integrated-timeline.ipynb`

3. For running streamlit application:
```bash
streamlit run app.py
```