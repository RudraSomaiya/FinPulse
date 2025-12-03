import pandas as pd
df = pd.read_excel('data.xlsx')
df = df.drop(['Company Code','Adviser Code','Adviser Name','Adviser Date of Birth','Main Client NRIC','Main Client Name',
       'Main Client Address', 'Joint Client NRIC', 'Joint Client Name','Unnamed: 24','Remark','Transaction Type'],axis=1)
df.to_excel('cleaned_data.xlsx',index=False)
print('File Conversion Successful')