import pandas as pd
import os
from sqlalchemy import create_engine

# Configuration - Replace with your Render Database URL
# Format: postgresql://<user>:<password>@<host>/<dbname>
DB_URL = os.getenv("DATABASE_URL")

def migrate():
    if not DB_URL:
        print("Error: DATABASE_URL environment variable not set.")
        return

    # Render uses postgresql://, but SQLAlchemy often prefers postgresql+psycopg2://
    url = DB_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    
    engine = create_engine(url)
    
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
            
            # For reminders, ensure ID is string
            if table_name == "reminders" and "ReminderId" in df.columns:
                df["ReminderId"] = df["ReminderId"].astype(str)
            
            # Write to SQL
            df.to_sql(table_name, engine, if_exists='replace', index=False)
            print(f"Successfully migrated {len(df)} rows.")
        else:
            print(f"Skipping {file_path} (file not found).")

if __name__ == "__main__":
    # You will need to install: pip install sqlalchemy psycopg2-binary openpyxl
    try:
        migrate()
        print("\nAll migrations completed successfully!")
    except Exception as e:
        print(f"\nMigration failed: {e}")
