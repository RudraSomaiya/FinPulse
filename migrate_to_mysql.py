import pandas as pd
import os
from sqlalchemy import create_engine

# Configuration - Replace with your DB URL
# Format: mysql+pymysql://<user>:<password>@<host>/<dbname>
DB_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:password@localhost/finpulse")

def migrate():
    engine = create_engine(DB_URL)
    
    files = {
        "transactions": "cleaned_data.xlsx",
        "client_details": "client-details.xlsx",
        "recommendations": "recommendationOutput.xlsx",
        "reminders": "reminders.xlsx"
    }
    
    for table_name, file_path in files.items():
        if os.path.exists(file_path):
            print(f"Migrating {file_path} to table '{table_name}'...")
            df = pd.read_excel(file_path)
            
            # Basic cleanup: remove spaces from column names for better SQL compatibility
            # df.columns = [c.replace(' ', '_').replace('(', '').replace(')', '') for c in df.columns]
            
            # For reminders, ensure ID is string
            if table_name == "reminders" and "ReminderId" in df.columns:
                df["ReminderId"] = df["ReminderId"].astype(str)
            
            # Write to SQL
            df.to_sql(table_name, engine, if_exists='replace', index=False)
            print(f"Successfully migrated {len(df)} rows.")
        else:
            print(f"Skipping {file_path} (file not found).")

if __name__ == "__main__":
    # You will need to install: pip install sqlalchemy pymysql openpyxl
    try:
        migrate()
        print("\nAll migrations completed successfully!")
    except Exception as e:
        print(f"\nMigration failed: {e}")
